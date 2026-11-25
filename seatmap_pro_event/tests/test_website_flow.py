import json
import re
from html import unescape

from odoo.tests import HttpCase, tagged

from .common import PUBLIC_KEY, SEATMAP_EVENT_ID, TOKEN, SeatmapEventCommon


@tagged('post_install', '-at_install')
class TestWebsiteSeatFlow(HttpCase, SeatmapEventCommon):

    def setUp(self):
        super().setUp()
        self.authenticate(None, None)

    def seat_page(self):
        response = self.url_open(f'/event/{self.event.id}/seats')
        self.assertEqual(response.status_code, 200)
        return response.text

    def page_config(self, html):
        match = re.search(r'data-seatmap-config="([^"]*)"', html)
        self.assertTrue(match, 'The seat picker is on the page')
        return json.loads(unescape(match.group(1)))

    def lock(self, *seat_ids, release=False):
        return self.make_jsonrpc_request(f'/event/{self.event.id}/seatmap/lock', {
            'seat_ids': list(seat_ids), 'release': release,
        })

    def attendee_form(self, *seat_ids):
        return self.make_jsonrpc_request(f'/event/{self.event.id}/registration/new', {
            'seatmap_seat_ids': ','.join(str(seat_id) for seat_id in seat_ids),
            # A forged quantity is ignored: the seats decide.
            f'nb_register-{self.ticket.id}': 9,
        })

    def confirm(self, seat_fields):
        questions = self.event.question_ids
        name = questions.filtered(lambda q: q.question_type == 'name')
        email = questions.filtered(lambda q: q.question_type == 'email')
        data = {'csrf_token': self.csrf_token()}
        for index, (ticket_id, seat_record_id) in enumerate(seat_fields, start=1):
            data.update({
                f'{index}-name-{name.id}': f'Buyer {index}',
                f'{index}-email-{email.id}': f'buyer{index}@example.com',
                f'{index}-event_ticket_id': ticket_id,
            })
            if seat_record_id:
                data[f'{index}-seatmap_seat_id'] = seat_record_id
        return self.url_open(f'/event/{self.event.id}/registration/confirm', data=data, allow_redirects=False)

    def test_page_has_public_values_and_no_token(self):
        register = self.url_open(f'/event/{self.event.id}/register').text
        self.assertIn(f'/seats', register)
        self.assertNotIn(TOKEN, register)
        html = self.seat_page()
        self.assertNotIn(TOKEN, html)
        config = self.page_config(html)
        self.assertNotIn(TOKEN, json.dumps(config))
        self.assertEqual(config['publicKey'], PUBLIC_KEY)
        self.assertEqual(config['eventId'], SEATMAP_EVENT_ID)
        self.assertEqual(config['apiUrl'], 'https://booking.seatmap.pro/api/public/v1.0/')
        self.assertEqual(config['rendererUrl'], 'https://cdn.jsdelivr.net/npm/@seatmap.pro/renderer@1.75.0/+esm')
        self.assertEqual(sorted(config['seats']), ['1000', '1001', '1002', '1003'])
        self.assertEqual(config['seats']['1002'], {
            'ticketId': self.ticket_premium.id, 'price': 150.0, 'label': 'Stalls, Row B, Seat 1',
        })

    def test_buyer_books_seats(self):
        result = self.lock(1000, 1002)
        self.assertEqual(sorted(result['held']), [1000, 1002])
        form = self.attendee_form(1000, 1002)
        self.assertIsInstance(form, str)
        seat_inputs = dict(re.findall(r'name="(\d+)-seatmap_seat_id" value="(\d+)"', form))
        ticket_inputs = dict(re.findall(r'name="(\d+)-event_ticket_id" value="(\d+)"', form))
        self.assertEqual(len(seat_inputs), 2, 'One seat field per attendee, not the forged quantity')
        self.assertIn('Stalls, Row B, Seat 1', form)

        response = self.confirm([(ticket_inputs[index], seat_inputs[index]) for index in sorted(seat_inputs)])
        self.assertEqual(response.status_code, 303)
        self.assertIn('/shop/checkout', response.headers['Location'])

        registrations = self.env['event.registration'].search([('event_id', '=', self.event.id)])
        self.assertEqual(registrations.seatmap_seat_id, self.seats[1000] | self.seats[1002])
        self.assertEqual(registrations.filtered(lambda r: r.seatmap_seat_id == self.seats[1002]).event_ticket_id,
                         self.ticket_premium)
        order = registrations.sale_order_id
        self.assertEqual(len(order), 1)
        lines = order.order_line.filtered('seatmap_seat_id')
        self.assertEqual(len(lines), 2, 'One order line per seat')
        self.assertEqual(lines.registration_ids, registrations)
        locks = self.Lock.search([('event_id', '=', self.event.id)])
        self.assertEqual(locks.sale_order_line_id, lines)

    def test_second_buyer_cannot_take_a_held_or_sold_seat(self):
        self.lock(1000)
        form = self.attendee_form(1000)
        seat_record_id = re.search(r'name="1-seatmap_seat_id" value="(\d+)"', form).group(1)
        self.confirm([(self.ticket.id, seat_record_id)])

        self.authenticate(None, None)  # a new visitor with a new session
        self.assertNotIn('1000', self.page_config(self.seat_page())['seats'])
        result = self.lock(1000)
        self.assertEqual(result['held'], [])
        self.assertEqual(result['taken'], [1000])
        self.assertEqual(self.attendee_form(1000), {'error': 'seat_taken', 'taken': [1000]})

        # A forged attendee form with the same seat is refused before any registration is created.
        count = self.env['event.registration'].search_count([('event_id', '=', self.event.id)])
        response = self.confirm([(self.ticket.id, seat_record_id)])
        self.assertEqual(response.status_code, 303)
        self.assertIn('registration_error_code=seat_taken', response.headers['Location'])
        self.assertEqual(self.env['event.registration'].search_count([('event_id', '=', self.event.id)]), count)

        # After payment the seat is sold and stays unavailable.
        order = self.env['event.registration'].search([('seatmap_seat_id', '=', self.seats[1000].id)]).sale_order_id
        order.action_confirm()
        self.assertEqual(self.lock(1000)['taken'], [1000])
        self.assertNotIn('1000', self.page_config(self.seat_page())['seats'])

    def test_free_seat_is_confirmed_without_a_cart(self):
        free_ticket = self.env['event.event.ticket'].create({
            'event_id': self.event.id, 'name': 'Free', 'product_id': self.product_event.id, 'price': 0,
        })
        self.event.seatmap_zone_ids.filtered(lambda zone: zone.zone_id == 3).ticket_id = free_ticket
        self.lock(1003)
        form = self.attendee_form(1003)
        seat_record_id = re.search(r'name="1-seatmap_seat_id" value="(\d+)"', form).group(1)
        response = self.confirm([(free_ticket.id, seat_record_id)])
        self.assertIn('/registration/success', response.headers['Location'])
        registration = self.env['event.registration'].search([('seatmap_seat_id', '=', self.seats[1003].id)])
        self.assertEqual(registration.state, 'open')
        self.assertFalse(registration.sale_order_id)
        self.assertFalse(self.Lock.search([('seat_id', '=', self.seats[1003].id)]))

    def test_ticket_additional_products_follow_each_seat(self):
        extra = self.env['product.product'].create({'name': 'Programme', 'list_price': 3, 'type': 'consu'})
        self.ticket.additional_product_ids = extra
        self.lock(1000, 1001)
        form = self.attendee_form(1000, 1001)
        seat_inputs = dict(re.findall(r'name="(\d+)-seatmap_seat_id" value="(\d+)"', form))
        self.confirm([(self.ticket.id, seat_inputs[index]) for index in sorted(seat_inputs)])
        order = self.env['event.registration'].search([('event_id', '=', self.event.id)]).sale_order_id
        seat_lines = order.order_line.filtered('seatmap_seat_id')
        self.assertEqual(len(seat_lines), 2)
        for line in seat_lines:
            self.assertEqual(line.linked_line_ids.product_id, extra)
            self.assertEqual(line.linked_line_ids.product_uom_qty, 1)

    def test_released_seat_is_free_again(self):
        self.lock(1001)
        self.lock(1001, release=True)
        self.authenticate(None, None)
        self.assertEqual(self.lock(1001)['held'], [1001])

    def test_registration_without_seat_is_refused(self):
        response = self.confirm([(self.ticket.id, False)])
        self.assertIn('registration_error_code=seat_required', response.headers['Location'])
        self.assertFalse(self.env['event.registration'].search([('event_id', '=', self.event.id)]))

    def test_seat_must_match_its_ticket(self):
        self.lock(1002)
        response = self.confirm([(self.ticket.id, self.seats[1002].id)])  # 1002 is a Premium seat
        self.assertIn('registration_error_code=seat_required', response.headers['Location'])

    def test_frontend_bundle_contains_the_seat_picker(self):
        bundle = self.env['ir.qweb']._get_asset_bundle('web.assets_frontend', debug_assets=True)
        js = ''.join(asset.content for asset in bundle.javascripts)
        self.assertIn('seatmap_pro_event.seat_picker', js)
