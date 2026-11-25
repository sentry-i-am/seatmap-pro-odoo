import copy
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import urlsplit

from odoo.addons.website_event_sale.tests.common import TestWebsiteEventSaleCommon

TOKEN = 'secret-organization-token-123'
PUBLIC_KEY = 'public-key-456'
SEATMAP_EVENT_ID = '5b1e7c2a-0000-4000-8000-000000000001'
SCHEMA_ID = 77

# Ids and coordinates are deltas, as in the Seatmap Pro public API.
PUBLIC_LAYOUT = {
    'rows': [
        {'id': 500, 'rowNumber': 'A', 'sectorId': 10},
        {'id': 1, 'rowNumber': 'B', 'sectorId': 10},
        {'id': 1, 'rowNumber': '1', 'sectorId': 20},
    ],
    'sectors': [
        {'id': 10, 'name': 'Stalls', 'isGa': False},
        {'id': 20, 'name': 'Balcony', 'isGa': False},
    ],
    'plainSeats': {
        'names': ['1', '2', '1', '7', '8'],
        'ids': [1000, 1, 1, 1, 1],
        'x': [100, 30, -30, 200, 30],
        'y': [100, 0, 30, -60, 0],
        'rowIds': [500, 0, 1, 1, 0],
        'sectorIds': [10, 0, 0, 10, 0],
    },
}
ZONE_BY_SEAT = {1000: 1, 1001: 1, 1002: 2, 1003: 3, 1004: None}
ZONE_NAMES = {1: 'Standard', 2: 'Premium', 3: 'Standard'}


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class FakeSession:
    """Answers the Booking API calls of a venue import and records every request."""

    def __init__(self, public_layout=None, zone_by_seat=None, zone_names=None):
        self.public_layout = public_layout or PUBLIC_LAYOUT
        self.zone_by_seat = ZONE_BY_SEAT if zone_by_seat is None else zone_by_seat
        self.zone_names = zone_names or ZONE_NAMES
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({'url': url, 'params': params, 'headers': headers, 'allow_redirects': allow_redirects})
        path = urlsplit(url).path
        if path == f'/api/private/v2.0/events/{SEATMAP_EVENT_ID}':
            return FakeResponse({'schemaId': SCHEMA_ID, 'schemaName': 'Test Hall'})
        if path == '/api/public/v1.0/event/':
            return FakeResponse(self.public_layout)
        if path == f'/api/private/v2.0/schemas/{SCHEMA_ID}/pricing_zones/':
            content = [{'id': zone_id, 'name': name} for zone_id, name in self.zone_names.items()]
            return FakeResponse({'content': content, 'last': True})
        if path == f'/api/private/v2.0/schemas/{SCHEMA_ID}/seatmaps/':
            return FakeResponse([{'id': 1, 'ga': False}, {'id': 2, 'ga': True}])
        if path == f'/api/private/v2.0/schemas/{SCHEMA_ID}/seatmaps/seats/':
            seats = [{'id': seat_id, 'pricingZoneId': zone} for seat_id, zone in self.zone_by_seat.items()]
            return FakeResponse({'rows': [{'seats': seats + [{'id': 9999, 'hidden': True}]}]})
        return FakeResponse({}, status_code=404)


@contextmanager
def fake_booking_api(session):
    with patch('odoo.addons.seatmap_pro_event.lib.booking_api.requests.Session', return_value=session):
        yield session


def layout_without(seat_id):
    """The test layout without one seat, as after an edit of the venue in Seatmap Pro."""
    layout = copy.deepcopy(PUBLIC_LAYOUT)
    plain = layout['plainSeats']
    ids = [1000, 1001, 1002, 1003, 1004]
    rows = [500, 500, 501, 502, 502]
    keep = [index for index, value in enumerate(ids) if value != seat_id]

    def encode(values):
        return [value - (values[index - 1] if index else 0) for index, value in enumerate(values)]

    plain['ids'] = encode([ids[index] for index in keep])
    plain['rowIds'] = encode([rows[index] for index in keep])
    plain['names'] = [plain['names'][index] for index in keep]
    plain['x'] = [0] * len(keep)
    plain['y'] = [0] * len(keep)
    zone_by_seat = {key: value for key, value in ZONE_BY_SEAT.items() if key != seat_id}
    return layout, zone_by_seat


class SeatmapEventCommon(TestWebsiteEventSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({
            'seatmap_organization_token': TOKEN,
            'seatmap_public_key': PUBLIC_KEY,
        })
        cls.ticket_premium = cls.env['event.event.ticket'].create({
            'event_id': cls.event.id,
            'name': 'Premium',
            'product_id': cls.product_event.id,
            'price': 150,
        })
        cls.event.write({'seatmap_event_id': SEATMAP_EVENT_ID, 'company_id': cls.env.company.id})
        with fake_booking_api(FakeSession()):
            cls.event.action_seatmap_import()
        zones = {zone.zone_id: zone for zone in cls.event.seatmap_zone_ids}
        zones[1].ticket_id = cls.ticket
        zones[2].ticket_id = cls.ticket_premium
        zones[3].ticket_id = cls.ticket
        cls.seats = {seat.seat_id: seat for seat in cls.event.seatmap_seat_ids}
        cls.Lock = cls.env['seatmap.seat.lock']

    def make_cart(self, *seat_ids, partner=None):
        """A website cart with one line and one draft registration per seat, held by the cart's order."""
        order = self.env['sale.order'].create({
            'partner_id': (partner or self.partner).id,
            'website_id': self.website.id,
        })
        for seat_id in seat_ids:
            seat = self.seats[seat_id]
            values = order._cart_add(
                product_id=seat.ticket_id.product_id.id,
                quantity=1,
                event_ticket_id=seat.ticket_id.id,
                event_slot_id=False,
                seatmap_seat_id=seat.id,
            )
            line = self.env['sale.order.line'].browse(values['line_id'])
            self.env['event.registration'].create({
                'name': f'Buyer {seat_id}',
                'email': f'buyer{seat_id}@example.com',
                'event_id': self.event.id,
                'sale_order_line_id': line.id,
            })
            held, taken = self.Lock._acquire(self.event, False, seat, f'order-{order.id}', line=line)
            self.assertTrue(held and not taken)
        return order
