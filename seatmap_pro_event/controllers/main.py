import json
import secrets

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.website_event_sale.controllers.main import WebsiteEventSaleController

OWNER_SESSION_KEY = 'seatmap_pro_owner'


class SeatmapEventController(WebsiteEventSaleController):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _seatmap_owner(self):
        """A random key in the buyer's session identifies the seats that this buyer holds."""
        owner = request.session.get(OWNER_SESSION_KEY)
        if not owner:
            owner = secrets.token_hex(16)
            request.session[OWNER_SESSION_KEY] = owner
        return owner

    def _seatmap_slot(self, event, slot_id):
        if not slot_id:
            return request.env['event.slot']
        try:
            slot_id = int(slot_id)
        except (TypeError, ValueError):
            return request.env['event.slot']
        return event.sudo().event_slot_ids.filtered(lambda slot: slot.id == slot_id)

    def _seatmap_seats_by_seatmap_id(self, event, seatmap_ids):
        ids = []
        for value in seatmap_ids or []:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return request.env['seatmap.seat'].sudo().search([('event_id', '=', event.id), ('seat_id', 'in', ids)])

    def _seatmap_parse_ids(self, value):
        if isinstance(value, str):
            value = [part for part in value.split(',') if part.strip()]
        return value or []

    # ------------------------------------------------------------------
    # Seat picker
    # ------------------------------------------------------------------

    @http.route(['/event/<model("event.event"):event>/seats'], type='http', auth='public', website=True, sitemap=False)
    def seatmap_seats(self, event, slot_id=None, registration_error_code=None, **post):
        event_sudo = event.sudo()
        if not event_sudo.seatmap_enabled:
            return request.redirect(f'/event/{event.id}/register')
        slot = self._seatmap_slot(event, slot_id)
        # The event layout also renders the standard registration modals, which need these values.
        values = self._prepare_event_register_values(event, **post)
        values.update({
            'seatmap_slots': event_sudo.event_slot_ids._filter_open_slots() if event_sudo.is_multi_slots else False,
            'event_slot': slot,
            'registration_error_code': registration_error_code,
            'seatmap_config': False,
        })
        if event_sudo.event_registrations_open and (slot or not event_sudo.is_multi_slots):
            config = event_sudo._seatmap_frontend_config(slot, self._seatmap_owner())
            values['seatmap_config'] = json.dumps(config)
        return request.render('seatmap_pro_event.seat_picker_page', values)

    @http.route(['/event/<model("event.event"):event>/seatmap/lock'], type='jsonrpc', auth='public', methods=['POST'], website=True)
    def seatmap_lock(self, event, seat_ids, slot_id=False, release=False):
        """Hold or release seats while the buyer clicks on the map. Seat ids are Seatmap Pro ids."""
        event_sudo = event.sudo()
        if not event_sudo.seatmap_enabled or not event_sudo.event_registrations_open:
            return {'held': [], 'taken': self._seatmap_parse_ids(seat_ids)}
        slot = self._seatmap_slot(event, slot_id)
        seats = self._seatmap_seats_by_seatmap_id(event_sudo, self._seatmap_parse_ids(seat_ids))
        owner = self._seatmap_owner()
        Lock = request.env['seatmap.seat.lock'].sudo()
        if release:
            Lock._release_owned(event_sudo, slot, seats, owner)
            return {'held': [], 'taken': []}
        open_holds = Lock.search_count([
            ('event_id', '=', event.id), ('owner', '=', owner), ('sale_order_line_id', '=', False),
            ('seat_id', 'not in', seats.ids),
        ])
        if open_holds + len(seats) > event_sudo.EVENT_MAX_TICKETS:
            return {'held': [], 'taken': seats.mapped('seat_id'), 'error': 'too_many'}
        available = event_sudo._seatmap_available_seats(slot, owner)
        not_for_sale = seats - available
        held, taken = Lock._acquire(event_sudo, slot, seats & available, owner)
        return {
            'held': held.seat_id.mapped('seat_id'),
            'taken': (taken | not_for_sale).mapped('seat_id'),
        }

    # ------------------------------------------------------------------
    # Registration flow of website_event / website_event_sale
    # ------------------------------------------------------------------

    @http.route()
    def registration_new(self, event, **post):
        event_sudo = event.sudo()
        if not event_sudo.seatmap_enabled:
            return super().registration_new(event, **post)
        slot = self._seatmap_slot(event, post.get('event_slot_id'))
        seats = self._seatmap_seats_by_seatmap_id(event_sudo, self._seatmap_parse_ids(post.get('seatmap_seat_ids')))
        if not seats:
            return False
        owner = self._seatmap_owner()
        available = event_sudo._seatmap_available_seats(slot, owner)
        _held, taken = request.env['seatmap.seat.lock'].sudo()._acquire(event_sudo, slot, seats & available, owner)
        taken |= seats - available
        if taken:
            return {'error': 'seat_taken', 'taken': taken.mapped('seat_id')}
        # The quantities come from the seats, never from the browser.
        post = {key: value for key, value in post.items() if not key.startswith('nb_register-')}
        for ticket, ticket_seats in seats.grouped('ticket_id').items():
            post[f'nb_register-{ticket.id}'] = len(ticket_seats)
        post['seatmap_seat_ids'] = ','.join(str(seat_id) for seat_id in seats.mapped('seat_id'))
        return super().registration_new(event, **post)

    def _prepare_registration_new_values(self, event, **post):
        values = super()._prepare_registration_new_values(event, **post)
        if values and event.sudo().seatmap_enabled and post.get('seatmap_seat_ids'):
            seats = self._seatmap_seats_by_seatmap_id(event, self._seatmap_parse_ids(post['seatmap_seat_ids']))
            values['seatmap_seats_by_ticket'] = {
                ticket.id: ticket_seats.sorted(lambda seat: (seat.sector or '', seat.row or '', seat.id))
                for ticket, ticket_seats in seats.grouped('ticket_id').items()
            }
        return values

    def _seatmap_check_registrations(self, event, registrations, slot):
        """Return an error code, or False when every registration has its own seat held by this buyer."""
        seat_ids = [registration.get('seatmap_seat_id') for registration in registrations]
        if not seat_ids or not all(seat_ids) or len(set(seat_ids)) != len(seat_ids):
            return 'seat_required'
        seats = request.env['seatmap.seat'].sudo().browse(seat_ids).exists()
        if len(seats) != len(seat_ids) or seats.event_id != event:
            return 'seat_required'
        seat_by_id = {seat.id: seat for seat in seats}
        for registration in registrations:
            seat = seat_by_id[registration['seatmap_seat_id']]
            if seat.ticket_id.id != registration.get('event_ticket_id'):
                return 'seat_required'
            if (registration.get('event_slot_id') or False) != (slot.id or False):
                return 'seat_required'
        _held, taken = request.env['seatmap.seat.lock'].sudo()._acquire(event, slot, seats, self._seatmap_owner())
        return 'seat_taken' if taken else False

    @http.route()
    def registration_confirm(self, event, **post):
        event_sudo = event.sudo()
        if event_sudo.seatmap_enabled:
            registrations = self._process_attendees_form(event, post)
            slot_ids = {registration.get('event_slot_id') for registration in registrations}
            if len(slot_ids) > 1:
                return request.redirect(f'/event/{event.id}/seats?registration_error_code=seat_required')
            slot = self._seatmap_slot(event, next(iter(slot_ids), False))
            error = self._seatmap_check_registrations(event_sudo, registrations, slot)
            if error:
                query = f'registration_error_code={error}' + (f'&slot_id={slot.id}' if slot else '')
                return request.redirect(f'/event/{event.id}/seats?{query}')
        return super().registration_confirm(event, **post)

    def _create_attendees_from_registration_post(self, event, registration_data):
        if not event.sudo().seatmap_enabled or not any(data.get('seatmap_seat_id') for data in registration_data):
            return super()._create_attendees_from_registration_post(event, registration_data)

        Lock = request.env['seatmap.seat.lock'].sudo()
        owner = self._seatmap_owner()
        tickets = request.env['event.event.ticket'].sudo().browse(
            {data['event_ticket_id'] for data in registration_data if data.get('event_ticket_id')}
        )
        if all(ticket.price == 0 for ticket in tickets) and not request.cart.id:
            # Free seats skip the cart: the registrations are confirmed at once and the unique index
            # protects the seats, so the holds are released.
            registrations = super()._create_attendees_from_registration_post(event, registration_data)
            Lock.search([('event_id', '=', event.id), ('owner', '=', owner),
                         ('seat_id', 'in', registrations.seatmap_seat_id.ids)]).unlink()
            return registrations

        order_sudo = request.cart or request.website._create_cart()
        for data in registration_data:
            ticket = tickets.filtered(lambda t: t.id == data.get('event_ticket_id'))
            seat = request.env['seatmap.seat'].sudo().browse(data['seatmap_seat_id'])
            slot_id = data.get('event_slot_id', False)
            cart_values = order_sudo._cart_add(
                product_id=ticket.product_id.id,
                quantity=1,
                event_ticket_id=ticket.id,
                event_slot_id=slot_id,
                seatmap_seat_id=seat.id,
            )
            if not cart_values.get('line_id'):
                raise UserError(cart_values.get('warning') or _('This ticket is sold out.'))
            line = request.env['sale.order.line'].sudo().browse(cart_values['line_id'])
            data['sale_order_id'] = order_sudo.id
            data['sale_order_line_id'] = line.id
            Lock.search([
                ('event_id', '=', event.id), ('event_slot_id', '=', slot_id or False),
                ('seat_id', '=', seat.id), ('owner', '=', owner),
            ]).write({
                'sale_order_line_id': line.id,
                'sale_order_id': order_sudo.id,
                'expires_at': Lock._expiry(event.sudo()),
            })
        # The cart lines exist already, one per seat. Skip the website_event_sale step that would add
        # one line per ticket type and go straight to the registration creation of website_event.
        return super(WebsiteEventSaleController, self)._create_attendees_from_registration_post(event, registration_data)
