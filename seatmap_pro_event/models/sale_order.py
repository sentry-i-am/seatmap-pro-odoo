from odoo import _, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _cart_find_product_line(self, *args, seatmap_seat_id=False, **kwargs):
        lines = super()._cart_find_product_line(*args, seatmap_seat_id=seatmap_seat_id, **kwargs)
        # A seat line only matches its own seat, and a plain ticket line never matches a seat line.
        return lines.filtered(lambda line: line.seatmap_seat_id.id == (seatmap_seat_id or False))

    def _prepare_order_line_values(self, product_id, *args, seatmap_seat_id=False, **kwargs):
        values = super()._prepare_order_line_values(product_id, *args, seatmap_seat_id=seatmap_seat_id, **kwargs)
        if seatmap_seat_id:
            values['seatmap_seat_id'] = seatmap_seat_id
        return values

    def _verify_updated_quantity(self, order_line, product_id, new_qty, uom_id, *, seatmap_seat_id=False, **kwargs):
        new_qty, warning = super()._verify_updated_quantity(
            order_line, product_id, new_qty, uom_id, seatmap_seat_id=seatmap_seat_id, **kwargs,
        )
        if (seatmap_seat_id or order_line.seatmap_seat_id) and new_qty > 1:
            return 1, _('A seat is sold once. Choose more seats on the map.')
        return new_qty, warning

    def _seatmap_hold_cart_seats(self):
        """Hold every seat of the cart again before payment. Return the seats that are no longer available."""
        self.ensure_one()
        Lock = self.env['seatmap.seat.lock'].sudo()
        taken = self.env['seatmap.seat']
        for line in self.order_line.filtered('seatmap_seat_id'):
            _held, line_taken = Lock._acquire(
                line.event_id, line.event_slot_id, line.seatmap_seat_id, f'order-{self.id}', line=line,
            )
            taken |= line_taken
        return taken

    def _is_cart_ready_for_payment(self):
        ready = super()._is_cart_ready_for_payment()
        taken = self._seatmap_hold_cart_seats()
        if taken:
            self._add_blocking_alert(self.env._(
                'These seats are no longer available: %(seats)s. Remove them from your cart and choose '
                'other seats.',
                seats=', '.join(taken.mapped('display_name')),
            ))
            return False
        return ready

    def _seatmap_release_locks(self):
        self.env['seatmap.seat.lock'].sudo().search([('sale_order_id', 'in', self.ids)]).unlink()

    def action_confirm(self):
        res = super().action_confirm()
        # Confirmed registrations are protected by the unique index; the holds are no longer needed.
        self._seatmap_release_locks()
        return res

    def _action_cancel(self):
        res = super()._action_cancel()
        self._seatmap_release_locks()
        return res
