"""Testy logiki głównej: deduplikacja OLX↔Otodom, usuwanie centroidów,
flagowanie generycznych pinezek Otodom."""

from main import SonarSprzedazy


def _offer(id_, source, price, area, coords=None, precision=None, active=True):
    return {
        'id': id_, 'source': source, 'active': active, 'area_m2': area,
        'market': 'wtorny',
        'price': {'current': price},
        'url': f'https://example.com/{id_}',
        'location': {'coords': coords, 'coords_precision': precision},
        'first_seen': '2026-06-01T10:00:00+02:00',
        'last_seen': '2026-06-10T10:00:00+02:00',
    }


def _sonar(tmp_path):
    return SonarSprzedazy(data_file=str(tmp_path / 'offers.json'),
                          removed_file=str(tmp_path / 'removed.json'))


def test_cross_portal_dedup_tagging(tmp_path):
    sonar = _sonar(tmp_path)
    near = {'lat': 51.25, 'lon': 22.56}
    near2 = {'lat': 51.251, 'lon': 22.561}     # ~0.13 km
    far = {'lat': 51.35, 'lon': 22.78}         # ~17 km
    sonar.database['offers'] = [
        _offer('olx:CID3-ID1', 'olx', 480000, 50, near, 'street'),
        _offer('otodom:1', 'otodom', 480000, 50.3, near2, 'exact'),  # duplikat
        _offer('olx:CID3-ID2', 'olx', 480000, 50, near, 'street'),
        _offer('otodom:2', 'otodom', 480000, 50, far, 'exact'),      # za daleko
    ]
    sonar._tag_cross_portal_duplicates()
    offers = {o['id']: o for o in sonar.database['offers']}
    # otodom:1 (exact, lepsza precyzja) jest kanoniczna i wchłania OLX-y
    assert offers['olx:CID3-ID1']['duplicate_of'] == 'otodom:1'
    assert offers['olx:CID3-ID2']['duplicate_of'] == 'otodom:1'
    assert 'duplicate_of' not in offers['otodom:2']


def test_strip_approx_coords(tmp_path):
    sonar = _sonar(tmp_path)
    sonar.database['offers'] = [
        _offer('otodom:1', 'otodom', 400000, 40, {'lat': 51.24, 'lon': 22.56}, 'approx'),
        _offer('otodom:2', 'otodom', 400000, 40, {'lat': 51.25, 'lon': 22.57}, 'exact'),
        _offer('olx:CID3-ID3', 'olx', 400000, 40, {'lat': 51.26, 'lon': 22.58}, 'street'),
    ]
    stripped = sonar._strip_approx_coords()
    offers = {o['id']: o for o in sonar.database['offers']}
    assert stripped == 1
    assert offers['otodom:1']['location']['coords'] is None        # centroid usunięty
    assert offers['otodom:2']['location']['coords'] is not None    # exact zostaje
    assert offers['olx:CID3-ID3']['location']['coords'] is not None  # street zostaje


def test_flag_generic_otodom_cluster(tmp_path):
    sonar = _sonar(tmp_path)
    # 3 oferty Otodom w tym samym punkcie (centroid dzielnicy) — exact → approx
    p = {'lat': 51.2465, 'lon': 22.5684}
    sonar.database['offers'] = [
        _offer('otodom:1', 'otodom', 1, 30, dict(p), 'exact'),
        _offer('otodom:2', 'otodom', 2, 31, dict(p), 'exact'),
        _offer('otodom:3', 'otodom', 3, 32, dict(p), 'exact'),
        # samotna pinezka gdzie indziej — zostaje exact
        _offer('otodom:9', 'otodom', 9, 33, {'lat': 51.30, 'lon': 22.60}, 'exact'),
    ]
    sonar._flag_generic_otodom_coords(min_cluster=3, radius_km=0.25)
    offers = {o['id']: o for o in sonar.database['offers']}
    assert offers['otodom:1']['location']['coords_precision'] == 'approx'
    assert offers['otodom:3']['location']['coords_precision'] == 'approx'
    assert offers['otodom:9']['location']['coords_precision'] == 'exact'


def test_mass_deactivation_protection(tmp_path):
    sonar = _sonar(tmp_path)
    sonar.database['offers'] = [
        _offer(f'otodom:{i}', 'otodom', 100000 + i, 40) for i in range(20)
    ]
    # scraper zwrócił 0 ofert (blokada portalu) — nic nie dezaktywujemy
    deactivated = sonar._mark_inactive({'otodom': []})
    assert deactivated == 0
    assert all(o['active'] for o in sonar.database['offers'])
