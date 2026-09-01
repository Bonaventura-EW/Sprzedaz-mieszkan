"""Testy detekcji płatnych wyróżnień OLX (`search_reason`) i ich szeregu czasowego.

Propagacja z SONAR-POKOJOWY (manifest 2026-08-26-promoted-listings-metric).
Sprawdzają: odczyt flagi z URL-a listingu (`_is_promoted_href`, `normalize_ad`),
trackowanie dni w bazie (`main._track_promoted`, `_add_new`, `_mark_inactive`)
i dzienny szereg w trend.json (`trend_generator.build_trend['promoted']`).
"""

from datetime import date, datetime

import pytz

from olx_scraper import _is_promoted_href, normalize_ad
from main import SonarSprzedazy
from trend_generator import build_trend


BASE_AD = {
    'url': 'https://www.olx.pl/d/oferta/mieszkanie-testowe-CID3-ID1abcDE.html',
    'title': 'Mieszkanie 2 pokoje',
    'isBusiness': False,
    'price': {'regularPrice': {'value': 480000, 'currencyCode': 'PLN'}},
    'location': {'cityName': 'Lublin', 'cityNormalizedName': 'lublin', 'districtName': None},
    'params': [{'key': 'm', 'normalizedValue': '50'}],
}


# ── _is_promoted_href ────────────────────────────────────────────────
def test_is_promoted_href_detects_promoted():
    assert _is_promoted_href('https://www.olx.pl/d/oferta/x-CID3-ID1.html?search_reason=search%7Cpromoted') is True
    assert _is_promoted_href('https://www.olx.pl/d/oferta/x-CID3-ID1.html?search_reason=search|promoted') is True


def test_is_promoted_href_organic_and_missing():
    assert _is_promoted_href('https://www.olx.pl/d/oferta/x.html?search_reason=search|organic') is False
    assert _is_promoted_href('https://www.olx.pl/d/oferta/x.html') is False
    assert _is_promoted_href('') is False
    assert _is_promoted_href(None) is False


# ── normalize_ad ─────────────────────────────────────────────────────
def test_normalize_ad_sets_promoted_from_url():
    ad = dict(BASE_AD, url=BASE_AD['url'] + '?search_reason=search%7Cpromoted')
    o = normalize_ad(ad)
    assert o['promoted'] is True
    # URL zapisany BEZ query stringa (jak dotąd), flaga i tak odczytana
    assert o['url'].endswith('.html')


def test_normalize_ad_not_promoted_by_default():
    assert normalize_ad(dict(BASE_AD))['promoted'] is False


# ── main._track_promoted / _add_new / _mark_inactive ─────────────────
def _sonar(tmp_path):
    return SonarSprzedazy(data_file=str(tmp_path / 'offers.json'),
                          removed_file=str(tmp_path / 'removed.json'))


def _today():
    return datetime.now(pytz.timezone('Europe/Warsaw')).strftime('%Y-%m-%d')


def test_track_promoted_adds_today_once(tmp_path):
    sonar = _sonar(tmp_path)
    offer = {'id': 'olx:1', 'promoted_dates': []}
    assert sonar._track_promoted(offer, True) is True
    assert offer['promoted'] is True
    assert offer['promoted_dates'] == [_today()]
    # drugi skan tego samego dnia nie dubluje wpisu
    assert sonar._track_promoted(offer, True) is False
    assert offer['promoted_dates'] == [_today()]


def test_track_promoted_false_clears_current_keeps_history(tmp_path):
    sonar = _sonar(tmp_path)
    offer = {'id': 'olx:1', 'promoted': True, 'promoted_dates': ['2026-08-30']}
    assert sonar._track_promoted(offer, False) is False
    assert offer['promoted'] is False
    assert offer['promoted_dates'] == ['2026-08-30']  # historia nietknięta


def test_add_new_seeds_promoted_history(tmp_path):
    sonar = _sonar(tmp_path)
    sonar._add_new({'id': 'olx:1', 'source': 'olx', 'promoted': True,
                    'price': 480000, 'location': {}})
    off = sonar.database['offers'][0]
    assert off['promoted'] is True
    assert off['promoted_dates'] == [_today()]


def test_mark_inactive_clears_promoted_for_offers_off_listing(tmp_path):
    sonar = _sonar(tmp_path)
    # oferta wyróżniona wcześniej, ale w tym skanie brak jej na listingu
    stale = {'id': 'olx:1', 'source': 'olx', 'active': True, 'promoted': True,
             'promoted_dates': ['2026-08-30'],
             'last_seen': '2020-01-01T00:00:00+01:00'}  # dawno = poza karencją
    others = [{'id': f'olx:{i}', 'source': 'olx', 'active': True,
               'promoted': False, 'last_seen': '2020-01-01T00:00:00+01:00'}
              for i in range(2, 15)]
    sonar.database['offers'] = [stale] + others
    # scan zwraca wszystkie POZA `stale` → ochrona z >30% nie odpala
    scraped = [{'id': o['id']} for o in others]
    sonar._mark_inactive({'olx': scraped})
    assert stale['promoted'] is False           # stan bieżący zdjęty
    assert stale['promoted_dates'] == ['2026-08-30']  # historia zostaje


# ── trend_generator.build_trend ──────────────────────────────────────
def _promoted_map(payload, key):
    return {p['date']: p['count'] for p in payload['promoted'][key]}


def test_build_trend_promoted_series_daily_count():
    db = {'offers': [
        {'id': 'olx:1', 'source': 'olx', 'market': 'wtorny', 'rooms': 2,
         'active': True, 'first_seen': '2026-08-30T10:00:00+02:00',
         'last_seen': '2026-09-01T10:00:00+02:00',
         'promoted_dates': ['2026-08-31', '2026-09-01']},
        {'id': 'olx:2', 'source': 'olx', 'market': 'wtorny', 'rooms': 3,
         'active': True, 'first_seen': '2026-08-30T10:00:00+02:00',
         'last_seen': '2026-09-01T10:00:00+02:00',
         'promoted_dates': ['2026-09-01']},
    ]}
    payload = build_trend(db, today=date(2026, 9, 1))
    assert _promoted_map(payload, 'wszystkie') == {'2026-08-31': 1, '2026-09-01': 2}
    # Otodom nie ma atrybucji → pusta seria dla tej kategorii
    assert payload['promoted']['zrodlo_otodom'] == []


def test_build_trend_promoted_empty_when_no_dates():
    db = {'offers': [
        {'id': 'olx:1', 'source': 'olx', 'market': 'wtorny', 'rooms': 2,
         'active': True, 'first_seen': '2026-08-30T10:00:00+02:00',
         'last_seen': '2026-09-01T10:00:00+02:00'},
    ]}
    payload = build_trend(db, today=date(2026, 9, 1))
    assert payload['promoted']['wszystkie'] == []
