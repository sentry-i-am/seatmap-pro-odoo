from odoo import _, api, fields, models


class SeatmapSeat(models.Model):
    _name = 'seatmap.seat'
    _description = 'Seatmap Pro seat'
    _order = 'event_id, sector, row, id'

    event_id = fields.Many2one('event.event', required=True, ondelete='cascade', index=True)
    seat_id = fields.Integer(string='Seatmap Pro seat ID', required=True, readonly=True)
    zone_id = fields.Many2one('seatmap.zone', string='Pricing zone', ondelete='set null', index=True)
    ticket_id = fields.Many2one(related='zone_id.ticket_id')
    sector = fields.Char(readonly=True)
    row = fields.Char(readonly=True)
    number = fields.Char(readonly=True)

    _seat_uniq = models.Constraint('unique(event_id, seat_id)', 'A seat is imported once per event.')

    @api.depends('sector', 'row', 'number')
    def _compute_display_name(self):
        for seat in self:
            parts = [seat.sector] if seat.sector else []
            if seat.row:
                parts.append(_('Row %s', seat.row))
            parts.append(_('Seat %s', seat.number or seat.seat_id))
            seat.display_name = ', '.join(parts)
