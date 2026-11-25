from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    seatmap_api_url = fields.Char(
        related='company_id.seatmap_api_url', readonly=False, groups='base.group_system',
    )
    seatmap_public_key = fields.Char(
        related='company_id.seatmap_public_key', readonly=False, groups='base.group_system',
    )
    # The token is write-only: the form never loads the stored value into the browser.
    seatmap_token_input = fields.Char(string='New organization token', groups='base.group_system')
    seatmap_token_is_set = fields.Boolean(compute='_compute_seatmap_token_is_set', groups='base.group_system')

    @api.depends('company_id')
    def _compute_seatmap_token_is_set(self):
        for settings in self:
            settings.seatmap_token_is_set = bool(settings.company_id.sudo().seatmap_organization_token)

    def set_values(self):
        super().set_values()
        for settings in self:
            if settings.seatmap_token_input:
                settings.company_id.sudo().seatmap_organization_token = settings.seatmap_token_input.strip()
                settings.seatmap_token_input = False
