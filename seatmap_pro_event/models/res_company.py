from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..lib.booking_api import BookingApi, api_origin, checked_api_url


class ResCompany(models.Model):
    _inherit = 'res.company'

    seatmap_api_url = fields.Char(
        string='Seatmap Pro Booking API',
        groups='base.group_system',
        help='Leave empty to use https://booking.seatmap.pro. Other hosts must be listed by the server '
             'administrator in the SEATMAP_PRO_ALLOWED_API_HOSTS environment variable.',
    )
    seatmap_organization_token = fields.Char(
        string='Seatmap Pro organization token',
        groups='base.group_system',
        copy=False,
    )
    seatmap_public_key = fields.Char(
        string='Seatmap Pro public key',
        groups='base.group_system',
    )

    @api.constrains('seatmap_api_url')
    def _check_seatmap_api_url(self):
        for company in self.sudo():
            if company.seatmap_api_url:
                try:
                    checked_api_url(company.seatmap_api_url)
                except ValueError as error:
                    raise ValidationError(str(error)) from error

    def _seatmap_api(self, session=None):
        """Return a Booking API client. Only server-side code calls this; the token never leaves the server."""
        self.ensure_one()
        company = self.sudo()
        if not company.seatmap_organization_token or not company.seatmap_public_key:
            raise UserError(_('Fill in the Seatmap Pro organization token and public key in the Events settings.'))
        try:
            return BookingApi(
                company.seatmap_api_url, company.seatmap_organization_token, company.seatmap_public_key, session=session
            )
        except ValueError as error:
            raise UserError(str(error)) from error

    def _seatmap_public_config(self):
        """Values the buyer's browser may see: the public key and the public API address."""
        self.ensure_one()
        company = self.sudo()
        return {
            'apiUrl': f'{api_origin(company.seatmap_api_url)}/api/public/v1.0/',
            'publicKey': company.seatmap_public_key or '',
        }
