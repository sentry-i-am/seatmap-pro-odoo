from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib.booking_api import SeatmapApiError
from ..lib.layout import NO_ZONE, NO_ZONE_NAME, seats_from_layout, zone_labels
from .seatmap_seat_lock import DEFAULT_HOLD_MINUTES

RENDERER_VERSION = '1.75.0'
RENDERER_URL = f'https://cdn.jsdelivr.net/npm/@seatmap.pro/renderer@{RENDERER_VERSION}/+esm'
SEAT_FIELDS = ('zone_id', 'sector', 'row', 'number')


class EventEvent(models.Model):
    _inherit = 'event.event'

    seatmap_event_id = fields.Char(
        string='Seatmap Pro event ID', copy=False,
        help='ID of the published Seatmap Pro event whose venue map buyers see.',
    )
    seatmap_hold_minutes = fields.Integer(
        string='Seat hold (minutes)', default=DEFAULT_HOLD_MINUTES,
        help='How long a seat stays reserved for a buyer between the click on the map and payment.',
    )
    seatmap_schema_id = fields.Integer(string='Seatmap Pro schema ID', readonly=True, copy=False)
    seatmap_venue_name = fields.Char(string='Seatmap Pro venue', readonly=True, copy=False)
    seatmap_imported_at = fields.Datetime(string='Venue loaded on', readonly=True, copy=False)
    seatmap_zone_ids = fields.One2many('seatmap.zone', 'event_id', string='Pricing zones', copy=False)
    seatmap_seat_ids = fields.One2many('seatmap.seat', 'event_id', string='Seats', copy=False)
    seatmap_seat_count = fields.Integer(compute='_compute_seatmap_seat_count', string='Seats on the map')
    seatmap_enabled = fields.Boolean(
        compute='_compute_seatmap_enabled', store=True,
        help='Buyers choose seats on the Seatmap Pro map instead of entering ticket quantities.',
    )

    @api.depends('seatmap_seat_ids')
    def _compute_seatmap_seat_count(self):
        counts = dict(self.env['seatmap.seat']._read_group(
            [('event_id', 'in', self.ids)], ['event_id'], ['__count'],
        ))
        for event in self:
            event.seatmap_seat_count = counts.get(event, 0)

    @api.depends('seatmap_event_id', 'seatmap_seat_ids')
    def _compute_seatmap_enabled(self):
        for event in self:
            event.seatmap_enabled = bool(event.seatmap_event_id and event.seatmap_seat_ids)

    # ------------------------------------------------------------------
    # Venue import
    # ------------------------------------------------------------------

    def action_seatmap_import(self):
        self.ensure_one()
        if not self.seatmap_event_id:
            raise UserError(_('Fill in the Seatmap Pro event ID first.'))
        company = self.company_id or self.env.company
        try:
            venue = company._seatmap_api().venue(self.seatmap_event_id.strip())
        except SeatmapApiError as error:
            raise UserError(str(error)) from error
        self._seatmap_apply_venue(venue)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('%(count)s seats loaded from Seatmap Pro.', count=self.seatmap_seat_count),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _seatmap_apply_venue(self, venue):
        """Write zones and seats from a venue. A seat keeps its record when the venue is loaded again."""
        self.ensure_one()
        try:
            layout_seats = seats_from_layout(venue.public_layout, venue.zone_by_seat)
        except ValueError as error:
            raise UserError(str(error)) from error

        Zone = self.env['seatmap.zone'].sudo()
        Seat = self.env['seatmap.seat'].sudo()
        labels = zone_labels(venue.zone_names)
        used_zone_ids = {seat['zone_id'] for seat in layout_seats}
        if NO_ZONE in used_zone_ids:
            labels[NO_ZONE] = NO_ZONE_NAME

        zones = {zone.zone_id: zone for zone in self.sudo().seatmap_zone_ids}
        for zone_id in sorted(used_zone_ids):
            if zone_id in zones:
                if zones[zone_id].name != labels.get(zone_id):
                    zones[zone_id].name = labels.get(zone_id) or f'Zone {zone_id}'
            else:
                zones[zone_id] = Zone.create({
                    'event_id': self.id,
                    'zone_id': zone_id,
                    'name': labels.get(zone_id) or f'Zone {zone_id}',
                })

        existing = {seat.seat_id: seat for seat in self.sudo().seatmap_seat_ids}
        new_ids = {seat['seat_id'] for seat in layout_seats}
        removed = Seat.browse([seat.id for seat_id, seat in existing.items() if seat_id not in new_ids])
        if removed:
            in_use = self.env['event.registration'].sudo().with_context(active_test=False).search_count([
                ('seatmap_seat_id', 'in', removed.ids), ('state', '!=', 'cancel'),
            ])
            if in_use:
                raise UserError(_(
                    'The new venue removes %(count)s seats that are already booked. '
                    'Restore them in Seatmap Pro or cancel those registrations first.',
                    count=in_use,
                ))
            # Registrations that were cancelled keep their record but lose the link to a deleted seat.
            self.env['event.registration'].sudo().with_context(active_test=False).search([
                ('seatmap_seat_id', 'in', removed.ids),
            ]).write({'seatmap_seat_id': False})
            self.env['sale.order.line'].sudo().search([('seatmap_seat_id', 'in', removed.ids)]).write(
                {'seatmap_seat_id': False})
            removed.unlink()

        to_create = []
        for data in layout_seats:
            values = {
                'zone_id': zones[data['zone_id']].id,
                'sector': data['sector'],
                'row': data['row'],
                'number': data['number'],
            }
            seat = existing.get(data['seat_id'])
            if seat is None:
                to_create.append({'event_id': self.id, 'seat_id': data['seat_id'], **values})
            elif any((seat.zone_id.id if name == 'zone_id' else seat[name]) != values[name] for name in SEAT_FIELDS):
                seat.write(values)
        if to_create:
            Seat.create(to_create)

        unused_zones = Zone.browse([zone.id for zone_id, zone in zones.items() if zone_id not in used_zone_ids])
        unused_zones.unlink()

        self.sudo().write({
            'seatmap_schema_id': venue.schema_id,
            'seatmap_venue_name': venue.name,
            'seatmap_imported_at': fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Website
    # ------------------------------------------------------------------

    def _seatmap_available_seats(self, slot, owner):
        """Seats a buyer can select: mapped to a ticket on sale, not booked, and not held by someone else."""
        self.ensure_one()
        event = self.sudo()
        slot = slot or self.env['event.slot']
        tickets = event.event_ticket_ids.filtered(lambda ticket: ticket.sale_available and not ticket.is_expired)
        seats = self.env['seatmap.seat'].sudo().search([
            ('event_id', '=', event.id),
            ('zone_id.ticket_id', 'in', tickets.ids),
        ])
        Lock = self.env['seatmap.seat.lock'].sudo()
        sold = Lock._sold_seat_ids(event, slot, seats)
        held = set(Lock.search([
            ('event_id', '=', event.id),
            ('event_slot_id', '=', slot.id or False),
            ('expires_at', '>=', fields.Datetime.now()),
            ('owner', '!=', owner),
        ]).seat_id.ids)
        return seats.filtered(lambda seat: seat.id not in sold and seat.id not in held)

    def _seatmap_frontend_config(self, slot, owner):
        """Configuration for the seat picker. It holds only public values: never the organization token."""
        self.ensure_one()
        event = self.sudo()
        company = event.company_id or self.env.company
        seats = event._seatmap_available_seats(slot, owner)
        return {
            'rendererUrl': RENDERER_URL,
            **company._seatmap_public_config(),
            'eventId': event.seatmap_event_id,
            'slotId': slot.id if slot else False,
            'currency': (event.company_id or self.env.company).currency_id.name,
            'lockUrl': f'/event/{event.id}/seatmap/lock',
            'registrationUrl': f'/event/{event.id}/registration/new',
            'seats': {
                str(seat.seat_id): {
                    'ticketId': seat.ticket_id.id,
                    'price': seat.ticket_id.price,
                    'label': seat.display_name,
                }
                for seat in seats
            },
            'maxSeats': self.EVENT_MAX_TICKETS,
            'labels': {
                'selected': _('Selected seats: {count}, total {total}'),
                'taken': _('Someone else has just taken these seats: {seats}. Choose other seats.'),
                'tooMany': _('You can choose up to {max} seats at once.'),
            },
        }
