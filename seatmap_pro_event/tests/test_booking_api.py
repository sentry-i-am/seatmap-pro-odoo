import os
from unittest import mock

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..lib.booking_api import ALLOWED_HOSTS_VARIABLE, BookingApi, api_origin, checked_api_url


@tagged('post_install', '-at_install')
class TestBookingApiHosts(TransactionCase):

    def test_default_api_url_is_allowed(self):
        self.assertEqual(checked_api_url(''), 'https://booking.seatmap.pro')
        self.assertEqual(checked_api_url('https://Booking.Seatmap.pro/'), 'https://booking.seatmap.pro')

    def test_other_api_urls_are_refused(self):
        for url in (
            'http://booking.seatmap.pro',
            'https://attacker.example',
            'https://booking.seatmap.pro.attacker.example',
            'https://user:pass@booking.seatmap.pro',
            'https://booking.seatmap.pro?x=1',
            'https://169.254.169.254',
            'file:///etc/passwd',
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                checked_api_url(url)

    def test_administrator_can_allow_an_on_premise_host(self):
        with mock.patch.dict(os.environ, {ALLOWED_HOSTS_VARIABLE: 'seatmap.internal.example:8443, other.example'}):
            self.assertEqual(
                checked_api_url('https://seatmap.internal.example:8443/'), 'https://seatmap.internal.example:8443')
            with self.assertRaises(ValueError):
                checked_api_url('https://seatmap.internal.example')

    def test_browser_falls_back_to_the_default_host(self):
        self.assertEqual(api_origin('https://attacker.example'), 'https://booking.seatmap.pro')

    def test_client_does_not_follow_redirects(self):
        session = mock.Mock()
        session.get.return_value = mock.Mock(status_code=200, json=lambda: {})
        BookingApi('', 'token', 'key', session=session).event('abc')
        self.assertIs(session.get.call_args.kwargs['allow_redirects'], False)
        self.assertEqual(session.get.call_args.kwargs['headers']['X-API-Key'], 'token')

    def test_public_call_carries_no_token(self):
        session = mock.Mock()
        session.get.return_value = mock.Mock(status_code=200, json=lambda: {})
        BookingApi('', 'token', 'key', session=session).public_event('abc')
        self.assertNotIn('X-API-Key', session.get.call_args.kwargs['headers'])

    def test_client_refuses_a_disallowed_host(self):
        with self.assertRaises(ValueError):
            BookingApi('https://attacker.example', 'token', 'key')


@tagged('post_install', '-at_install')
class TestCompanyApiUrl(TransactionCase):

    def test_company_refuses_a_disallowed_host(self):
        with self.assertRaises(ValidationError):
            self.env.company.seatmap_api_url = 'https://attacker.example'

    def test_token_is_restricted_to_administrators(self):
        self.assertEqual(self.env['res.company']._fields['seatmap_organization_token'].groups, 'base.group_system')
