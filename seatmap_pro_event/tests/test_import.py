from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import (
    PUBLIC_KEY, SCHEMA_ID, SEATMAP_EVENT_ID, TOKEN, FakeSession, SeatmapEventCommon, fake_booking_api,
    layout_without,
)


@tagged('post_install', '-at_install')
class TestVenueImport(SeatmapEventCommon):

    def test_import_creates_zones_and_seats(self):
        event = self.event
        self.assertTrue(event.seatmap_enabled)
        self.assertEqual(event.seatmap_schema_id, SCHEMA_ID)
        self.assertEqual(event.seatmap_venue_name, 'Test Hall')
        self.assertEqual(event.seatmap_seat_count, 5)
        self.assertEqual(sorted(self.seats), [1000, 1001, 1002, 1003, 1004])
        zones = {zone.zone_id: zone.name for zone in event.seatmap_zone_ids}
        self.assertEqual(zones, {
            0: 'Seatmap Pro: no pricing zone', 1: 'Standard', 2: 'Premium', 3: 'Standard (3)',
        })
        seat = self.seats[1002]
        self.assertEqual((seat.sector, seat.row, seat.number), ('Stalls', 'B', '1'))
        self.assertEqual(seat.display_name, 'Stalls, Row B, Seat 1')
        self.assertEqual(seat.ticket_id, self.ticket_premium)
        self.assertEqual((self.seats[1003].sector, self.seats[1003].row), ('Balcony', '1'))
        self.assertFalse(self.seats[1004].ticket_id, 'A seat without pricing zone is not for sale')

    def test_token_goes_only_to_the_booking_api(self):
        session = FakeSession()
        with fake_booking_api(session):
            self.event.action_seatmap_import()
        self.assertTrue(session.calls)
        for call in session.calls:
            self.assertTrue(call['url'].startswith('https://booking.seatmap.pro/'))
            self.assertIs(call['allow_redirects'], False)
            if call['url'].endswith('/api/public/v1.0/event/'):
                self.assertNotIn('X-API-Key', call['headers'])
                self.assertEqual(call['params'], {'id': SEATMAP_EVENT_ID, 'publicKey': PUBLIC_KEY})
            else:
                self.assertEqual(call['headers']['X-API-Key'], TOKEN)

    def test_reimport_keeps_seat_records_and_mapping(self):
        before = {seat_id: seat.id for seat_id, seat in self.seats.items()}
        with fake_booking_api(FakeSession()):
            self.event.action_seatmap_import()
        after = {seat.seat_id: seat.id for seat in self.event.seatmap_seat_ids}
        self.assertEqual(before, after)
        self.assertEqual(self.seats[1002].ticket_id, self.ticket_premium)

    def test_reimport_removes_a_free_seat(self):
        layout, zone_by_seat = layout_without(1001)
        with fake_booking_api(FakeSession(layout, zone_by_seat)):
            self.event.action_seatmap_import()
        self.assertEqual(sorted(self.event.seatmap_seat_ids.mapped('seat_id')), [1000, 1002, 1003, 1004])

    def test_reimport_refuses_to_remove_a_booked_seat(self):
        self.env['event.registration'].create({
            'name': 'Booked', 'event_id': self.event.id, 'event_ticket_id': self.ticket.id,
            'seatmap_seat_id': self.seats[1001].id,
        })
        layout, zone_by_seat = layout_without(1001)
        with fake_booking_api(FakeSession(layout, zone_by_seat)), self.assertRaises(UserError):
            self.event.action_seatmap_import()
        self.assertIn(1001, self.event.seatmap_seat_ids.mapped('seat_id'))

    def test_import_needs_credentials(self):
        self.env.company.seatmap_organization_token = False
        with fake_booking_api(FakeSession()), self.assertRaises(UserError):
            self.event.action_seatmap_import()
