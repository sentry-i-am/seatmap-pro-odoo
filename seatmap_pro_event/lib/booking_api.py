"""Client for the Seatmap Pro Booking API.

The organization token is sent only to hosts that the server administrator allows, only over HTTPS,
and the client never follows redirects.
"""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

DEFAULT_API_URL = 'https://booking.seatmap.pro'
# A server administrator lists extra Booking API hosts here, for example an on-premise installation.
# Event managers cannot add hosts, so the module never sends the organization token to an address they choose.
ALLOWED_HOSTS_VARIABLE = 'SEATMAP_PRO_ALLOWED_API_HOSTS'
TIMEOUT = 20
PAGE_SIZE = 200


class SeatmapApiError(Exception):
    pass


def allowed_api_hosts():
    extra = os.environ.get(ALLOWED_HOSTS_VARIABLE, '')
    return {urlsplit(DEFAULT_API_URL).netloc, *(host.strip().lower() for host in extra.split(',') if host.strip())}


def checked_api_url(api_url):
    """Return the API address without a trailing slash, or raise ValueError if the server does not allow it."""
    url = (api_url or DEFAULT_API_URL).strip().rstrip('/')
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('The Booking API address must be a plain https:// address.')
    if parts.netloc.lower() not in allowed_api_hosts():
        raise ValueError(
            f'The server administrator has not allowed {parts.netloc}. Add it to {ALLOWED_HOSTS_VARIABLE}.'
        )
    return f'https://{parts.netloc.lower()}{parts.path}'


def api_origin(api_url):
    """Return scheme and host of an allowed API address, or of the default address."""
    try:
        parts = urlsplit(checked_api_url(api_url))
    except ValueError:
        parts = urlsplit(DEFAULT_API_URL)
    return f'{parts.scheme}://{parts.netloc}'


@dataclass(frozen=True)
class Venue:
    name: str
    schema_id: int
    public_layout: dict
    zone_by_seat: dict
    zone_names: dict


class BookingApi:
    def __init__(self, api_url, organization_token, public_key, session=None):
        self.api_url = checked_api_url(api_url)
        self.organization_token = organization_token
        self.public_key = public_key
        self.session = session or requests.Session()

    def _get(self, path, params=None, private=True):
        headers = {'Accept': 'application/json'}
        if private:
            headers['X-API-Key'] = self.organization_token
        try:
            response = self.session.get(
                f'{self.api_url}{path}', params=params, headers=headers, timeout=TIMEOUT, allow_redirects=False
            )
        except requests.RequestException as error:
            raise SeatmapApiError(f'Seatmap Pro is not reachable: {error}') from error
        if response.status_code != 200:
            raise SeatmapApiError(f'Seatmap Pro returned HTTP {response.status_code} for {path}')
        return response.json()

    def _pages(self, path):
        page = 0
        while True:
            data = self._get(path, {'page': page, 'size': PAGE_SIZE})
            yield from data['content']
            if data.get('last', True):
                return
            page += 1

    def event(self, event_id):
        return self._get(f'/api/private/v2.0/events/{event_id}')

    def public_event(self, event_id):
        return self._get('/api/public/v1.0/event/', {'id': event_id, 'publicKey': self.public_key}, private=False)

    def pricing_zones(self, schema_id):
        zones = self._pages(f'/api/private/v2.0/schemas/{schema_id}/pricing_zones/')
        return {zone['id']: zone['name'] for zone in zones}

    def sections(self, schema_id):
        return self._get(f'/api/private/v2.0/schemas/{schema_id}/seatmaps/', {'type': 'SECTION'})

    def section_seats(self, schema_id, section_id):
        return self._get(f'/api/private/v2.0/schemas/{schema_id}/seatmaps/seats/', {'sectionId': section_id})

    def venue(self, event_id):
        event = self.event(event_id)
        schema_id = event['schemaId']
        zone_by_seat = {}
        for section in self.sections(schema_id):
            if section.get('ga'):
                continue
            for row in self.section_seats(schema_id, section['id'])['rows']:
                for seat in row['seats']:
                    if not seat.get('hidden'):
                        zone_by_seat[seat['id']] = seat.get('pricingZoneId')
        return Venue(
            name=event.get('schemaName') or event.get('name') or '',
            schema_id=schema_id,
            public_layout=self.public_event(event_id),
            zone_by_seat=zone_by_seat,
            zone_names=self.pricing_zones(schema_id),
        )
