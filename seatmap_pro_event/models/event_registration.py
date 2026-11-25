from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    # copy=False: a copied registration must not claim the same seat (Odoo 20.0 copies registrations
    # for multi-use tickets).
    seatmap_seat_id = fields.Many2one(
        'seatmap.seat', string='Seat', copy=False, ondelete='restrict', index='btree_not_null',
        domain="[('event_id', '=', event_id)]",
    )
    seatmap_seat_label = fields.Char(
        string='Seat label', compute='_compute_seatmap_seat_label', store=True, copy=False,
    )

    # One registration per seat and slot, unless it is cancelled. Cart registrations are drafts and count.
    _seatmap_seat_uniq = models.UniqueIndex(
        "(event_id, COALESCE(event_slot_id, 0), seatmap_seat_id) "
        "WHERE seatmap_seat_id IS NOT NULL AND state != 'cancel'",
        'This seat is already booked.',
    )

    @api.depends('seatmap_seat_id.sector', 'seatmap_seat_id.row', 'seatmap_seat_id.number')
    def _compute_seatmap_seat_label(self):
        for registration in self:
            registration.seatmap_seat_label = registration.seatmap_seat_id.display_name or False

    @api.constrains('seatmap_seat_id', 'event_id')
    def _check_seatmap_seat_event(self):
        for registration in self.filtered('seatmap_seat_id'):
            if registration.seatmap_seat_id.event_id != registration.event_id:
                raise ValidationError(_('The seat %s belongs to another event.', registration.seatmap_seat_id.display_name))

    def _get_website_registration_allowed_fields(self):
        return super()._get_website_registration_allowed_fields() | {'seatmap_seat_id'}

    def _synchronize_so_line_values(self, so_line):
        values = super()._synchronize_so_line_values(so_line)
        if so_line and so_line.seatmap_seat_id:
            values['seatmap_seat_id'] = so_line.seatmap_seat_id.id
        return values
