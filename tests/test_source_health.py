"""Testy wykrywania „martwego źródła" (alert per portal)."""

from source_health import compute_source_alerts


def _scan(olx, otodom):
    return {'scraped_olx': olx, 'scraped_otodom': otodom}


def test_no_alert_when_all_sources_active():
    scans = [_scan(900, 1800), _scan(910, 1790), _scan(905, 1805)]
    assert compute_source_alerts(scans, {'olx': 900, 'otodom': 1800}) == []


def test_alert_when_source_drops_to_zero():
    # OLX było aktywne, potem 0 w ostatnich skanach
    scans = [_scan(900, 1800), _scan(910, 1790), _scan(0, 1805), _scan(0, 1810)]
    alerts = compute_source_alerts(scans, {'olx': 900, 'otodom': 1800})
    assert len(alerts) == 1
    a = alerts[0]
    assert a['source'] == 'olx'
    assert a['consecutive_zero_scans'] == 2
    assert a['active_in_db'] == 900


def test_alert_persists_after_drop_leaves_window():
    # spadek sprzed dawna: całe okno to zera, ale w bazie wciąż są aktywne
    # oferty (karencja) — alert musi się utrzymać dzięki active_in_db
    scans = [_scan(0, 1800)] * 12
    alerts = compute_source_alerts(scans, {'olx': 500, 'otodom': 1800}, window=5)
    assert [a['source'] for a in alerts] == ['olx']
    assert alerts[0]['consecutive_zero_scans'] == 12


def test_no_alert_for_source_never_present():
    # źródło bez historii (brak pola) nie generuje fałszywego alertu
    scans = [{'scraped_otodom': 1800}, {'scraped_otodom': 1810}]
    assert compute_source_alerts(scans, {'otodom': 1800}) == []


def test_no_alert_on_empty_history():
    assert compute_source_alerts([], {'olx': 100}) == []
