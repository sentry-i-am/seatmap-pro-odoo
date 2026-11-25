from odoo import _, api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # One order line per seat, so the buyer removes a specific seat from the cart.
    seatmap_seat_id = fields.Many2one(
        'seatmap.seat', string='Seat', copy=False, ondelete='restrict', index='btree_not_null',
    )

    @api.depends('seatmap_seat_id')
    def _compute_name(self):
        super()._compute_name()

    @api.depends('seatmap_seat_id')
    def _compute_name_short(self):
        super()._compute_name_short()
        for line in self.filtered('seatmap_seat_id'):
            line.name_short = f'{line.name_short}, {line.seatmap_seat_id.display_name}'

    def _get_sale_order_line_multiline_description_sale(self):
        description = super()._get_sale_order_line_multiline_description_sale()
        if self.seatmap_seat_id:
            description += '\n' + _('Seat: %s', self.seatmap_seat_id.display_name)
        return description
