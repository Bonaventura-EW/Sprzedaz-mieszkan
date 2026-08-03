"""Testy generatora szeregów czasowych trendu (trend_generator.build_trend).

Sprawdzają rekonstrukcję dziennej liczby aktywnych ofert, odpływ (archiwizacje
danego dnia), pomijanie duplikatów OLX↔Otodom oraz predykaty kategorii.
"""

from datetime import date

from trend_generator import build_trend


def _offer(id_, source, market, rooms, first_seen, active=True,
           deactivated_at=None, last_seen=None, duplicate_of=None):
    return {
        'id': id_, 'source': source, 'market': market, 'rooms': rooms,
        'active': active,
        'first_seen': first_seen,
        'last_seen': last_seen or first_seen,
        'deactivated_at': deactivated_at,
        'duplicate_of': duplicate_of,
    }


def _profile_map(payload, key):
    """{'YYYY-MM-DD': count} dla danej kategorii."""
    return {p['date']: p['count'] for p in payload['profiles'][key]}


def test_active_offer_counted_every_day_until_today():
    db = {'offers': [
        _offer('olx:1', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00', active=True),
    ]}
    payload = build_trend(db, today=date(2026, 6, 3))
    m = _profile_map(payload, 'wszystkie')
    assert m == {'2026-06-01': 1, '2026-06-02': 1, '2026-06-03': 1}


def test_deactivated_offer_stops_being_counted_and_shows_in_outflow():
    db = {'offers': [
        _offer('otodom:1', 'otodom', 'pierwotny', 3, '2026-06-01T10:00:00+02:00',
               active=False, deactivated_at='2026-06-02T12:00:00+02:00'),
    ]}
    payload = build_trend(db, today=date(2026, 6, 4))
    m = _profile_map(payload, 'wszystkie')
    # obecna 01 i 02 (dzień dezaktywacji włącznie), zniknęła 03–04
    assert m == {'2026-06-01': 1, '2026-06-02': 1, '2026-06-03': 0, '2026-06-04': 0}
    # odpływ zliczony w dniu dezaktywacji
    outflow = {o['date']: o['count'] for o in payload['outflow']['wszystkie']}
    assert outflow == {'2026-06-02': 1}


def test_duplicates_are_excluded():
    db = {'offers': [
        _offer('otodom:1', 'otodom', 'wtorny', 2, '2026-06-01T10:00:00+02:00'),
        _offer('olx:1', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00',
               duplicate_of='otodom:1'),
    ]}
    payload = build_trend(db, today=date(2026, 6, 1))
    # duplikat pominięty → tylko 1 oferta
    assert payload['profiles']['wszystkie'][0]['count'] == 1
    assert payload['profiles']['zrodlo_olx'][0]['count'] == 0
    assert payload['profiles']['zrodlo_otodom'][0]['count'] == 1


def test_category_predicates_split_correctly():
    db = {'offers': [
        _offer('a', 'olx', 'pierwotny', 1, '2026-06-01T10:00:00+02:00'),
        _offer('b', 'otodom', 'wtorny', 2, '2026-06-01T10:00:00+02:00'),
        _offer('c', 'otodom', 'wtorny', 5, '2026-06-01T10:00:00+02:00'),
    ]}
    payload = build_trend(db, today=date(2026, 6, 1))
    first = lambda k: payload['profiles'][k][0]['count']
    assert first('wszystkie') == 3
    assert first('rynek_pierwotny') == 1
    assert first('rynek_wtorny') == 2
    assert first('zrodlo_olx') == 1
    assert first('zrodlo_otodom') == 2
    assert first('pokoje_1') == 1
    assert first('pokoje_2') == 1
    assert first('pokoje_4plus') == 1   # 5 pokoi → 4+


def test_labels_present_and_flagged():
    db = {'offers': [
        _offer('a', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00'),
    ]}
    payload = build_trend(db, today=date(2026, 6, 1))
    assert payload['labels']['wszystkie'] == {'label': 'Wszystkie oferty', 'is_category': True}
    assert payload['labels']['rynek_pierwotny']['is_category'] is False


def test_empty_db_returns_empty_structures():
    payload = build_trend({'offers': []}, today=date(2026, 6, 1))
    assert payload['profiles'] == {}
    assert payload['outflow'] == {}
