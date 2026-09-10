"""Testy generatora szeregów czasowych trendu (trend_generator.build_trend).

Sprawdzają rekonstrukcję dziennej liczby aktywnych ofert, odpływ (archiwizacje
danego dnia), pomijanie duplikatów OLX↔Otodom oraz predykaty kategorii.
"""

from datetime import date

import trend_generator as tg
from trend_generator import SCANS_PER_DAY, _scan_coverage, build_trend


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
    assert payload['inflow'] == {}
    assert payload['reactivations'] == {}


def _sparse_map(payload, kind, key):
    return {p['date']: p['count'] for p in payload[kind][key]}


def test_new_offers_and_first_day_seed_excluded():
    # A = najstarsza (dzień 0 osi = zasianie bazy → NIE liczymy jako napływ);
    # B pojawia się dzień później → realnie nowa
    db = {'offers': [
        _offer('a', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00'),
        _offer('b', 'otodom', 'wtorny', 2, '2026-06-02T10:00:00+02:00'),
    ]}
    payload = build_trend(db, today=date(2026, 6, 3))
    inflow = _sparse_map(payload, 'inflow', 'wszystkie')
    # 01.06 (seed) pominięty, 02.06 = 1 nowa
    assert inflow == {'2026-06-02': 1}


def test_reactivations_counted_and_folded_into_inflow():
    offer = _offer('otodom:1', 'otodom', 'wtorny', 2, '2026-06-01T10:00:00+02:00')
    offer['reactivation_dates'] = ['2026-06-03T08:00:00+02:00', '2026-06-04T08:00:00+02:00']
    # druga oferta jako „dzień 0", żeby 01.06 nie był jedyną datą osi
    db = {'offers': [offer, _offer('x', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00')]}
    payload = build_trend(db, today=date(2026, 6, 5))
    react = _sparse_map(payload, 'reactivations', 'wszystkie')
    assert react == {'2026-06-03': 1, '2026-06-04': 1}
    # reaktywacje wchodzą też do napływu
    inflow = _sparse_map(payload, 'inflow', 'wszystkie')
    assert inflow.get('2026-06-03') == 1
    assert inflow.get('2026-06-04') == 1


def test_reactivated_at_scalar_fallback():
    # brak listy reactivation_dates → używamy skalarnego reactivated_at
    offer = _offer('otodom:2', 'otodom', 'wtorny', 2, '2026-06-01T10:00:00+02:00')
    offer['reactivated_at'] = '2026-06-03T08:00:00+02:00'
    db = {'offers': [offer, _offer('x', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00')]}
    payload = build_trend(db, today=date(2026, 6, 4))
    react = _sparse_map(payload, 'reactivations', 'wszystkie')
    assert react == {'2026-06-03': 1}


# ── Maska pokrycia skanami (FIX 2026-09-10, propagacja issue #14) ──────────

def _counts(*days_and_n):
    """{date: liczba skanów} z par (date, n) — wejście dla `_scan_coverage`."""
    return {d: n for d, n in days_and_n}


def _history(*days_and_n):
    """Dziennik skanów: n ZAKOŃCZONYCH przebiegów w każdym z podanych dni."""
    return [{'timestamp': f'{d.isoformat()}T{8 + 4 * i:02d}:00:00+02:00',
             'status': 'completed', 'active': 100}
            for d, n in days_and_n for i in range(n)]


def test_scan_coverage_marks_incomplete_and_last_complete():
    # pierwszy dzień dziennika pomijamy (bywa ucięty), dni sprzed niego = pełne
    counts = _counts((date(2026, 6, 1), 2), (date(2026, 6, 2), 2),
                     (date(2026, 6, 3), 1), (date(2026, 6, 4), 2))
    incomplete, last_complete = _scan_coverage(counts, today=date(2026, 6, 5))
    # 03 miał 1 skan z 2 → niepełny; 05 nie ma w dzienniku (0 skanów) → niepełny
    assert incomplete == {date(2026, 6, 3), date(2026, 6, 5)}
    # ostatni pełny dzień to 04 (05 niepełny)
    assert last_complete == date(2026, 6, 4)


def test_scan_coverage_empty_log_assumes_full():
    # brak dziennika → nie maskujemy, seria idzie do „dziś"
    assert _scan_coverage({}, today=date(2026, 6, 5)) == (set(), date(2026, 6, 5))


def test_incomplete_day_omitted_and_series_ends_on_last_complete():
    # oferta żyje przez cały czerwiec; 05 ma 1 skan (niepełny), 06 = dziś bez skanu
    db = {'offers': [
        _offer('olx:1', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00', active=True),
    ]}
    scan_history = _history((date(2026, 6, 1), SCANS_PER_DAY),
                          (date(2026, 6, 2), SCANS_PER_DAY),
                          (date(2026, 6, 3), SCANS_PER_DAY),
                          (date(2026, 6, 4), SCANS_PER_DAY),
                          (date(2026, 6, 5), 1))   # niepełny
    payload = build_trend(db, today=date(2026, 6, 6), scan_history=scan_history)
    m = _profile_map(payload, 'wszystkie')
    # 05 (niepełny) i 06 (dziś, brak skanu) wypadają; seria kończy się na 04
    assert '2026-06-05' not in m
    assert '2026-06-06' not in m
    assert max(m) == '2026-06-04'
    assert m['2026-06-04'] == 1


def test_days_before_scan_log_assumed_complete():
    # oferta z maja, dziennik skanów rusza dopiero w czerwcu — stara historia
    # nie może zniknąć jako „niepełna"
    db = {'offers': [
        _offer('olx:1', 'olx', 'wtorny', 2, '2026-05-20T10:00:00+02:00', active=True),
    ]}
    scan_history = _history((date(2026, 6, 1), SCANS_PER_DAY),
                          (date(2026, 6, 2), SCANS_PER_DAY))
    payload = build_trend(db, today=date(2026, 6, 3), scan_history=scan_history)
    m = _profile_map(payload, 'wszystkie')
    # 20.05 (sprzed dziennika) obecny; 03.06 (dziś, brak skanu) ucięty
    assert '2026-05-20' in m
    assert '2026-06-03' not in m
    assert max(m) == '2026-06-02'

# ── Seria „measured" (propagacja z SONAR-POKOJOWY, issue #11) ──────────────
# Zmierzony (nie rekonstruowany) dzienny stan bazy po dedup, z data/scan_history.json.

def _measured_map(payload):
    return {p['date']: p['count'] for p in payload['measured'].get('wszystkie', [])}


def test_measured_series_max_per_day_and_gaps():
    db = {'offers': [_offer('a', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00')]}
    scan_history = [
        {'timestamp': '2026-06-01T08:00:00+02:00', 'active_dedup': 100},
        {'timestamp': '2026-06-01T18:00:00+02:00', 'active_dedup': 130},  # ten sam dzień → max
        # 2026-06-02: brak skanu → LUKA (nie zero)
        {'timestamp': '2026-06-03T08:00:00+02:00', 'active_dedup': 120},
        {'timestamp': '2026-06-04T08:00:00+02:00', 'status': 'failed'},   # bez active_dedup → pominięty
        {'timestamp': '2026-06-05T08:00:00+02:00', 'active': 200},        # stary skan bez pola → pominięty
    ]
    payload = build_trend(db, today=date(2026, 6, 5), scan_history=scan_history)
    assert _measured_map(payload) == {'2026-06-01': 130, '2026-06-03': 120}


def test_measured_absent_without_scan_history():
    db = {'offers': [_offer('a', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00')]}
    assert build_trend(db, today=date(2026, 6, 1)).get('measured') == {}
    assert build_trend(db, today=date(2026, 6, 1), scan_history=[]).get('measured') == {}
    # skany sprzed wdrożenia (bez active_dedup) nie tworzą serii
    old = [{'timestamp': '2026-06-01T08:00:00+02:00', 'active': 100}]
    assert build_trend(db, today=date(2026, 6, 1), scan_history=old).get('measured') == {}


def test_empty_db_has_measured_key():
    payload = build_trend({'offers': []}, today=date(2026, 6, 1))
    assert payload['measured'] == {}


def _monotonic_drift_ratio(recon_map, measured_map):
    """Detektor błędu z manifestu brata (issue #11): porównaj rekonstrukcję z
    niezależnym pomiarem tego samego dnia. Jeśli |różnica| maleje monotonicznie
    w stronę dziś — to ten sam błąd (prawy koniec odwraca kierunek trendu).
    Zwraca udział par dzień-po-dniu, w których |dryf| maleje: ~1.0 =
    monotoniczny dryf (podejrzany), ~0.5 = zdrowy szum wokół zera."""
    days = sorted(set(recon_map) & set(measured_map))
    diffs = [recon_map[d] - measured_map[d] for d in days]
    if len(diffs) < 2:
        return 0.0
    decreasing = sum(1 for a, b in zip(diffs, diffs[1:]) if abs(b) < abs(a))
    return decreasing / (len(diffs) - 1)


def test_reconstruction_drift_detector():
    # rekonstrukcja systematycznie zawyża przeszłość, błąd maleje do dziś → ten sam błąd
    recon = {'2026-06-01': 130, '2026-06-02': 124, '2026-06-03': 118,
             '2026-06-04': 112, '2026-06-05': 106}
    measured = {d: 100 for d in recon}
    assert _monotonic_drift_ratio(recon, measured) == 1.0
    # zdrowa rekonstrukcja: szum wokół zera, brak monotonicznego dryfu
    healthy = {'2026-06-01': 101, '2026-06-02': 99, '2026-06-03': 102,
               '2026-06-04': 98, '2026-06-05': 100}
    assert _monotonic_drift_ratio(healthy, measured) < 1.0


def test_scan_counts_only_completed_runs():
    # nieudany skan nie zalicza się do pokrycia doby (dzień zostaje niepełny)
    history = [{'timestamp': '2026-06-01T08:00:00+02:00', 'status': 'completed'},
               {'timestamp': '2026-06-01T18:00:00+02:00', 'status': 'failed'},
               {'timestamp': '2026-06-02T08:00:00+02:00', 'status': 'completed'},
               {'timestamp': '2026-06-02T18:00:00+02:00', 'status': 'warning'}]
    assert tg._scan_counts(history) == {date(2026, 6, 1): 1, date(2026, 6, 2): 2}
    assert tg._scan_counts(None) == {}


def test_measured_survives_incomplete_day():
    # Styk dwóch zmian (#14 + #11): dzień niepełny wypada z REKONSTRUKCJI, ale
    # pomiar jest migawką stanu bazy, więc jego punkt zostaje.
    db = {'offers': [_offer('olx:1', 'olx', 'wtorny', 2, '2026-06-01T10:00:00+02:00')]}
    history = _history((date(2026, 6, 1), SCANS_PER_DAY), (date(2026, 6, 2), SCANS_PER_DAY),
                       (date(2026, 6, 3), SCANS_PER_DAY), (date(2026, 6, 4), 1))
    for scan in history:
        scan['active_dedup'] = 42
    payload = build_trend(db, today=date(2026, 6, 4), scan_history=history)
    assert '2026-06-04' not in _profile_map(payload, 'wszystkie')   # niepełny → bez rekonstrukcji
    assert _measured_map(payload)['2026-06-04'] == 42               # ale pomiar zostaje
