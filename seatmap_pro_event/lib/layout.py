"""Read seats from a Seatmap Pro public event layout."""
from itertools import accumulate

NO_ZONE = 0
NO_ZONE_NAME = 'Seatmap Pro: no pricing zone'


def decode(values):
    """The public layout stores ids and coordinates as differences. A running sum restores them."""
    return list(accumulate(values or []))


def zone_labels(zone_names):
    """Give every pricing zone a unique, non-empty name."""
    names = {}
    used = set()
    for zone_id, name in sorted(zone_names.items()):
        label = name or f'Zone {zone_id}'
        if label in used:
            label = f'{label} ({zone_id})'
        used.add(label)
        names[zone_id] = label
    return names


def seats_from_layout(public_layout, zone_by_seat):
    """Return one dict per numbered seat: Seatmap seat id, pricing zone id, sector, row, and seat number.

    Only seats listed in ``zone_by_seat`` are returned. The private API lists them and leaves out
    hidden seats and standing areas.
    """
    plain = public_layout['plainSeats']
    seat_ids = decode(plain['ids'])
    row_ids = decode(plain['rowIds'])
    names = plain['names']

    layout_rows = public_layout.get('rows', [])
    row_id_list = decode([row['id'] for row in layout_rows])
    rows = dict(zip(row_id_list, layout_rows))
    sectors = {sector['id']: sector for sector in public_layout.get('sectors', [])}

    seats = []
    for seat_id, row_id, label in zip(seat_ids, row_ids, names):
        if seat_id not in zone_by_seat:
            continue
        row = rows.get(row_id, {})
        sector = sectors.get(row.get('sectorId'), {})
        zone_id = zone_by_seat[seat_id]
        seats.append({
            'seat_id': seat_id,
            'zone_id': NO_ZONE if zone_id is None else zone_id,
            'sector': sector.get('name') or '',
            'row': str(row.get('rowNumber') or ''),
            'number': str(label),
        })
    if not seats:
        raise ValueError('The Seatmap Pro event has no seats with numbers')
    return seats
