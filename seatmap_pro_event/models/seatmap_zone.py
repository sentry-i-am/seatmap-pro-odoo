from odoo import api, fields, models


class SeatmapZone(models.Model):
    _name = 'seatmap.zone'
    _description = 'Seatmap Pro pricing zone'
    _order = 'event_id, name, id'

    event_id = fields.Many2one('event.event', required=True, ondelete='cascade', index=True)
    zone_id = fields.Integer(string='Seatmap Pro zone ID', required=True, readonly=True)
    name = fields.Char(required=True, readonly=True)
    ticket_id = fields.Many2one(
        'event.event.ticket', string='Ticket',
        domain="[('event_id', '=', event_id)]", ondelete='set null',
        help='Ticket sold for the seats of this pricing zone. Seats of a zone without a ticket are not for sale.',
    )
    seat_ids = fields.One2many('seatmap.seat', 'zone_id', string='Seats')
    seat_count = fields.Integer(compute='_compute_seat_count')

    _zone_uniq = models.Constraint('unique(event_id, zone_id)', 'A pricing zone is imported once per event.')

    @api.depends('seat_ids')
    def _compute_seat_count(self):
        counts = dict(self.env['seatmap.seat']._read_group(
            [('zone_id', 'in', self.ids)], ['zone_id'], ['__count'],
        ))
        for zone in self:
            zone.seat_count = counts.get(zone, 0)
