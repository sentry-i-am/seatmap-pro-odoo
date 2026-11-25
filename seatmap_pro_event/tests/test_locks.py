from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import SeatmapEventCommon


@tagged('post_install', '-at_install')
class TestSeatLocks(SeatmapEventCommon):

    def acquire(self, seat_id, owner, slot=False):
        return self.Lock._acquire(self.event, slot, self.seats[seat_id], owner)

    def expire(self, locks):
        locks.expires_at = fields.Datetime.now() - timedelta(minutes=1)

    def test_hold_lasts_the_event_hold_time(self):
        self.event.seatmap_hold_minutes = 15
        held, taken = self.acquire(1000, 'buyer-a')
        self.assertFalse(taken)
        remaining = held.expires_at - fields.Datetime.now()
        self.assertTrue(timedelta(minutes=14) < remaining <= timedelta(minutes=15))

    def test_second_buyer_cannot_take_a_held_seat(self):
        held, _taken = self.acquire(1000, 'buyer-a')
        self.assertEqual(held.seat_id, self.seats[1000])
        held_b, taken_b = self.acquire(1000, 'buyer-b')
        self.assertFalse(held_b)
        self.assertEqual(taken_b, self.seats[1000])
        self.assertNotIn(self.seats[1000], self.event._seatmap_available_seats(False, 'buyer-b'))
        self.assertIn(self.seats[1000], self.event._seatmap_available_seats(False, 'buyer-a'))

    def test_same_buyer_extends_the_hold(self):
        held, _taken = self.acquire(1000, 'buyer-a')
        self.expire(held)
        held_again, taken = self.acquire(1000, 'buyer-a')
        self.assertFalse(taken)
        self.assertEqual(held_again.seat_id, self.seats[1000])
        self.assertGreater(held_again.expires_at, fields.Datetime.now())

    def test_sold_seat_cannot_be_held(self):
        self.env['event.registration'].create({
            'name': 'Sold', 'event_id': self.event.id, 'event_ticket_id': self.ticket.id,
            'seatmap_seat_id': self.seats[1000].id, 'state': 'open',
        })
        held, taken = self.acquire(1000, 'buyer-b')
        self.assertFalse(held)
        self.assertEqual(taken, self.seats[1000])
        self.assertNotIn(self.seats[1000], self.event._seatmap_available_seats(False, 'buyer-b'))

    def test_cancelled_registration_frees_the_seat(self):
        registration = self.env['event.registration'].create({
            'name': 'Sold', 'event_id': self.event.id, 'event_ticket_id': self.ticket.id,
            'seatmap_seat_id': self.seats[1000].id, 'state': 'open',
        })
        registration.action_cancel()
        held, taken = self.acquire(1000, 'buyer-b')
        self.assertTrue(held)
        self.assertFalse(taken)

    def test_database_refuses_two_registrations_for_one_seat(self):
        values = {
            'name': 'One', 'event_id': self.event.id, 'event_ticket_id': self.ticket.id,
            'seatmap_seat_id': self.seats[1000].id,
        }
        self.env['event.registration'].create(values)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.env['event.registration'].create(dict(values, name='Two'))

    def test_copied_registration_does_not_keep_the_seat(self):
        registration = self.env['event.registration'].create({
            'name': 'One', 'event_id': self.event.id, 'event_ticket_id': self.ticket.id,
            'seatmap_seat_id': self.seats[1000].id,
        })
        self.assertFalse(registration.copy().seatmap_seat_id)

    def test_seats_outside_mapped_zones_are_not_offered(self):
        available = self.event._seatmap_available_seats(False, 'buyer-a')
        self.assertEqual(sorted(available.mapped('seat_id')), [1000, 1001, 1002, 1003])

    def test_one_seat_per_slot(self):
        self.event.is_multi_slots = True
        slot_1, slot_2 = self.env['event.slot'].create([
            {'event_id': self.event.id, 'date': fields.Date.today() + timedelta(days=5),
             'start_hour': 10, 'end_hour': 12},
            {'event_id': self.event.id, 'date': fields.Date.today() + timedelta(days=5),
             'start_hour': 14, 'end_hour': 16},
        ])
        held_1, _taken = self.acquire(1000, 'buyer-a', slot_1)
        held_2, taken_2 = self.acquire(1000, 'buyer-b', slot_2)
        self.assertTrue(held_1 and held_2)
        self.assertFalse(taken_2)
        _held, taken = self.acquire(1000, 'buyer-c', slot_1)
        self.assertEqual(taken, self.seats[1000])

    def test_cart_has_one_line_per_seat(self):
        order = self.make_cart(1000, 1001)
        lines = order.order_line.filtered('seatmap_seat_id')
        self.assertEqual(len(lines), 2)
        self.assertEqual(set(lines.mapped('product_uom_qty')), {1})
        self.assertEqual(lines.registration_ids.seatmap_seat_id, self.seats[1000] | self.seats[1001])
        self.assertIn('Stalls, Row A, Seat 1', lines.filtered(lambda line: line.seatmap_seat_id == self.seats[1000]).name)
        line = lines[0]
        order._cart_update_line_quantity(line.id, 3)
        self.assertEqual(line.product_uom_qty, 1)

    def test_expired_hold_leaves_the_cart(self):
        order = self.make_cart(1000, 1001)
        lock = self.Lock.search([('sale_order_id', '=', order.id), ('seat_id', '=', self.seats[1000].id)])
        self.expire(lock)
        self.Lock._cron_release_expired()
        self.assertEqual(order.order_line.seatmap_seat_id, self.seats[1001])
        self.assertFalse(self.env['event.registration'].search([('seatmap_seat_id', '=', self.seats[1000].id)]))
        self.assertFalse(lock.exists())
        held, taken = self.acquire(1000, 'buyer-b')
        self.assertTrue(held)
        self.assertFalse(taken)

    def test_expired_hold_without_cart_is_removed(self):
        held, _taken = self.acquire(1000, 'buyer-a')
        self.expire(held)
        self.Lock._cron_release_expired()
        self.assertFalse(held.exists())

    def test_expired_hold_is_released_when_another_buyer_clicks(self):
        order = self.make_cart(1000)
        self.expire(self.Lock.search([('sale_order_id', '=', order.id)]))
        held, taken = self.acquire(1000, 'buyer-b')
        self.assertTrue(held)
        self.assertFalse(taken)
        self.assertFalse(order.order_line.filtered('seatmap_seat_id'))

    def test_payment_check_renews_an_expired_hold(self):
        order = self.make_cart(1000)
        lock = self.Lock.search([('sale_order_id', '=', order.id)])
        self.expire(lock)
        order._check_cart_is_ready_to_be_paid()
        self.assertGreater(lock.expires_at, fields.Datetime.now())
        self.assertEqual(order.order_line.seatmap_seat_id, self.seats[1000])

    def test_payment_check_refuses_a_seat_taken_meanwhile(self):
        order = self.make_cart(1000)
        # The cart registration keeps other website buyers away. Another channel, such as a point of sale,
        # may still hold the seat directly.
        self.Lock.search([('sale_order_id', '=', order.id)]).unlink()
        _held, taken = self.acquire(1000, 'buyer-b')
        self.assertEqual(taken, self.seats[1000])
        self.Lock.create({
            'event_id': self.event.id, 'seat_id': self.seats[1000].id, 'owner': 'pos-order',
            'expires_at': fields.Datetime.now() + timedelta(minutes=10),
        })
        with self.assertRaises(ValidationError):
            order._check_cart_is_ready_to_be_paid()

    def test_confirmed_order_keeps_the_seat_without_a_hold(self):
        order = self.make_cart(1000)
        order.action_confirm()
        self.assertFalse(self.Lock.search([('sale_order_id', '=', order.id)]))
        registration = order.order_line.registration_ids
        self.assertEqual(registration.state, 'open')
        self.assertEqual(registration.seatmap_seat_label, 'Stalls, Row A, Seat 1')
        _held, taken = self.acquire(1000, 'buyer-b')
        self.assertEqual(taken, self.seats[1000])

    def test_removing_the_line_frees_the_seat(self):
        order = self.make_cart(1000)
        line = order.order_line.filtered('seatmap_seat_id')
        order._cart_update_line_quantity(line.id, 0)
        self.assertFalse(self.Lock.search([('seat_id', '=', self.seats[1000].id)]))
        held, _taken = self.acquire(1000, 'buyer-b')
        self.assertTrue(held)
