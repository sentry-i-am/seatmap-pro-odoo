from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain

DEFAULT_HOLD_MINUTES = 15
# An order with a transaction in one of these states is being paid: its seats stay held.
PAYMENT_IN_PROGRESS = ('pending', 'authorized', 'done')


class SeatmapSeatLock(models.Model):
    """Holds a seat for one buyer from the click on the map until the order is confirmed.

    Odoo keeps cart registrations in ``draft`` and does not count them as taken, so without a hold two
    buyers could put the same seat in their carts. The unique index makes the hold atomic.
    """
    _name = 'seatmap.seat.lock'
    _description = 'Seatmap Pro seat hold'
    _order = 'expires_at, id'

    event_id = fields.Many2one('event.event', required=True, ondelete='cascade', index=True)
    event_slot_id = fields.Many2one('event.slot', ondelete='cascade')
    seat_id = fields.Many2one('seatmap.seat', required=True, ondelete='cascade')
    owner = fields.Char(required=True, index=True, help='Session key of the buyer who holds the seat.')
    sale_order_line_id = fields.Many2one('sale.order.line', ondelete='cascade', index='btree_not_null')
    sale_order_id = fields.Many2one('sale.order', ondelete='cascade', index='btree_not_null')
    expires_at = fields.Datetime(required=True, index=True)

    _seat_lock_uniq = models.UniqueIndex(
        '(event_id, COALESCE(event_slot_id, 0), seat_id)',
        'This seat is held by another buyer.',
    )

    @api.model
    def _expiry(self, event):
        return fields.Datetime.now() + timedelta(minutes=event.seatmap_hold_minutes or DEFAULT_HOLD_MINUTES)

    @api.model
    def _sold_seat_ids(self, event, slot, seats, exclude_line=None):
        """Seats with a registration that is not cancelled, including drafts in other carts."""
        domain = [
            ('event_id', '=', event.id),
            ('event_slot_id', '=', slot.id or False),
            ('seatmap_seat_id', 'in', seats.ids),
            ('state', '!=', 'cancel'),
        ]
        if exclude_line:
            domain.append(('sale_order_line_id', '!=', exclude_line.id))
        registrations = self.env['event.registration'].sudo().with_context(active_test=False).search(domain)
        return set(registrations.seatmap_seat_id.ids)

    @api.model
    def _insert(self, event, slot, seat, owner, expires_at, line=None):
        """Insert a hold, or return an empty recordset if another transaction holds the seat."""
        self.env['seatmap.seat.lock'].flush_model()
        self.env.cr.execute(
            """
            INSERT INTO seatmap_seat_lock
                (event_id, event_slot_id, seat_id, owner, sale_order_line_id, sale_order_id, expires_at,
                 create_uid, create_date, write_uid, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() at time zone 'UTC', %s, now() at time zone 'UTC')
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                event.id, slot.id or None, seat.id, owner,
                line.id if line else None, line.order_id.id if line else None,
                expires_at, self.env.uid, self.env.uid,
            ),
        )
        row = self.env.cr.fetchone()
        return self.browse(row[0]) if row else self.browse()

    @api.model
    def _acquire(self, event, slot, seats, owner, line=None):
        """Hold ``seats`` for ``owner``. Return ``(held locks, taken seats)``.

        A seat is taken when a registration that is not cancelled uses it, or when another buyer holds
        it and the hold has not expired. Holds of the same owner, or of the same order line, are extended.
        """
        self = self.sudo()
        slot = slot or self.env['event.slot']
        seats = seats.sudo()
        release_domain = [('event_id', '=', event.id), ('seat_id', 'in', seats.ids)]
        if line:
            # Before payment an expired hold of this very line is renewed, not released.
            release_domain.append(('sale_order_line_id', '!=', line.id))
        self._release_expired(release_domain)
        sold = self._sold_seat_ids(event, slot, seats, exclude_line=line)
        existing = {
            lock.seat_id.id: lock
            for lock in self.search([
                ('event_id', '=', event.id),
                ('event_slot_id', '=', slot.id or False),
                ('seat_id', 'in', seats.ids),
            ])
        }
        expires_at = self._expiry(event)
        held = self.browse()
        taken = self.env['seatmap.seat']
        for seat in seats:
            if seat.id in sold:
                taken |= seat
                continue
            lock = existing.get(seat.id)
            if lock:
                if lock.owner == owner or (line and lock.sale_order_line_id == line):
                    lock.write({'expires_at': expires_at, 'owner': owner})
                    held |= lock
                else:
                    taken |= seat
                continue
            lock = self._insert(event, slot, seat, owner, expires_at, line=line)
            if lock:
                held |= lock
            else:
                taken |= seat
        return held, taken

    @api.model
    def _release_owned(self, event, slot, seats, owner):
        """Release holds that the buyer set on the map but has not put in a cart."""
        self.sudo().search([
            ('event_id', '=', event.id),
            ('event_slot_id', '=', (slot.id if slot else False)),
            ('seat_id', 'in', seats.ids),
            ('owner', '=', owner),
            ('sale_order_line_id', '=', False),
        ]).unlink()

    @api.model
    def _release_expired(self, domain=None):
        """Remove expired holds. A seat in a cart that is not being paid leaves the cart with its registration."""
        self = self.sudo()
        locks = self.search(Domain.AND([[('expires_at', '<', fields.Datetime.now())], domain or []]))
        kept = self.browse()
        for lock in locks:
            line = lock.sale_order_line_id
            if not line:
                continue
            order = line.order_id
            if order.state != 'draft':
                continue
            if order.transaction_ids.filtered(lambda tx: tx.state in PAYMENT_IN_PROGRESS):
                kept |= lock
                continue
            # Unlinking the line deletes its registration and this hold through ``ondelete='cascade'``.
            order._cart_update_order_line(line, 0)
        (locks.exists() - kept).unlink()

    @api.model
    def _cron_release_expired(self):
        self._release_expired()
