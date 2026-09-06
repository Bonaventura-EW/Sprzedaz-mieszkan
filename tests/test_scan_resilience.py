"""Testy odporności skanu (FIX 2026-09-06 — po audycie logów przebiegów).

Trzy awarie widoczne wyłącznie w logu skanu, przy zielonym workflow:
1. jeden timeout strony OLX ucinał resztę listingu miasta (407/486 ofert
   zamiast ~1000 — skany 2026-09-02 i 2026-09-04),
2. skokowa zmiana ceny była ignorowana BEZ KOŃCA, więc oferta zostawała
   w bazie ze starą ceną na zawsze,
3. częściowe załamanie źródła nie zapalało alertu (alert znał tylko „0 ofert").
"""

import olx_scraper
from olx_scraper import (OLXMieszkaniaScraper, _promotion_flags, is_promoted_ad,
                         MAX_CONSECUTIVE_PAGE_FAILURES, MAX_PAGE_FAILURES_PER_CITY)
from main import SonarSprzedazy, PRICE_JUMP_CONFIRM_SCANS
from source_health import compute_source_alerts


# ── 1. paginacja OLX: nieudana strona nie kończy listingu ─────────────
def _ad(n):
    return {
        'url': f'https://www.olx.pl/d/oferta/mieszkanie-{n}-CID3-ID1abc{n}.html',
        'title': f'Mieszkanie {n}',
        'isBusiness': False,
        'price': {'regularPrice': {'value': 400000 + n, 'currencyCode': 'PLN'}},
        'location': {'cityName': 'Lublin', 'cityNormalizedName': 'lublin'},
        'params': [{'key': 'm', 'normalizedValue': '50'}],
    }


def _page(ads, total=1000):
    return {'listing': {'listing': {'ads': ads, 'totalElements': total}}}


class _FakeScraper(OLXMieszkaniaScraper):
    """Scraper z podmienionym wejściem HTTP — `pages` mapuje nr strony na stan
    JSON (None = strona nie do pobrania)."""

    def __init__(self, pages):
        self.delay_min = self.delay_max = 0
        self.promoted_stats = {'cards': 0, 'attributed': 0, 'promoted': 0,
                               'promotion_field': 0}
        self._promotion_sample = None
        self.failed_pages = []
        self.engine = 'fake'
        self._pages = pages
        self.fetched = []

    def _fetch(self, url):
        page = 1 if '?page=' not in url else int(url.rsplit('=', 1)[1])
        self.fetched.append(page)
        return 'html' if self._pages.get(page) is not None else None


def test_failed_page_does_not_end_pagination(monkeypatch):
    # strona 2 nie do pobrania, strony 1/3/4 mają oferty; ostatnia pusta = koniec
    pages = {1: _page([_ad(1)]), 2: None, 3: _page([_ad(3)]), 4: _page([_ad(4)]),
             5: _page([])}
    scraper = _FakeScraper(pages)
    monkeypatch.setattr(olx_scraper, 'decode_prerendered_state',
                        lambda html: scraper._pages[scraper.fetched[-1]])

    offers = []
    scraper._scrape_city('lublin', olx_scraper.LISTING_URLS['lublin'], 10,
                         offers, set())

    # PRZED fixem: `break` na stronie 2 → tylko 1 oferta
    assert [o['title'] for o in offers] == ['Mieszkanie 1', 'Mieszkanie 3', 'Mieszkanie 4']
    assert scraper.failed_pages == ['lublin/2']


def test_pagination_stops_after_consecutive_failures(monkeypatch):
    # seria nieudanych stron = realna blokada, nie ma sensu dobijać się dalej
    pages = {1: _page([_ad(1)])}
    for p in range(2, 12):
        pages[p] = None
    scraper = _FakeScraper(pages)
    monkeypatch.setattr(olx_scraper, 'decode_prerendered_state',
                        lambda html: scraper._pages[scraper.fetched[-1]])

    offers = []
    scraper._scrape_city('lublin', olx_scraper.LISTING_URLS['lublin'], 20,
                         offers, set())

    assert len(scraper.failed_pages) == MAX_CONSECUTIVE_PAGE_FAILURES
    assert max(scraper.fetched) == 1 + MAX_CONSECUTIVE_PAGE_FAILURES


def test_scattered_failures_stop_at_time_guard(monkeypatch):
    """Rwący się listing (co druga strona pada) nie może rozciągnąć skanu
    w nieskończoność — bezpiecznik liczy WSZYSTKIE nieudane strony miasta."""
    pages = {}
    for p in range(1, 40):
        pages[p] = None if p % 2 == 0 else _page([_ad(p)])
    scraper = _FakeScraper(pages)
    monkeypatch.setattr(olx_scraper, 'decode_prerendered_state',
                        lambda html: scraper._pages[scraper.fetched[-1]])

    offers = []
    scraper._scrape_city('lublin', olx_scraper.LISTING_URLS['lublin'], 39,
                         offers, set())

    # przerwane po MAX_PAGE_FAILURES_PER_CITY, mimo że nigdy nie było
    # MAX_CONSECUTIVE_PAGE_FAILURES błędów z rzędu
    assert len(scraper.failed_pages) == MAX_PAGE_FAILURES_PER_CITY
    assert len(offers) == MAX_PAGE_FAILURES_PER_CITY  # strony nieparzyste do tego miejsca


def test_fetch_retries_before_giving_up(monkeypatch):
    """`_fetch` ponawia — pojedynczy timeout nie może zgubić strony."""
    calls = []

    class _Session:
        def get(self, url, timeout=None):
            calls.append(url)
            if len(calls) < 3:
                raise TimeoutError('curl: (28) Operation timed out')
            return type('R', (), {'text': 'ok', 'raise_for_status': lambda self: None})()

    scraper = _FakeScraper({})
    scraper.session = _Session()
    monkeypatch.setattr(olx_scraper.time, 'sleep', lambda s: None)

    assert OLXMieszkaniaScraper._fetch(scraper, 'https://olx/x') == 'ok'
    assert len(calls) == 3


def test_fetch_returns_none_after_all_attempts(monkeypatch):
    class _Session:
        def get(self, url, timeout=None):
            raise TimeoutError('curl: (28) Operation timed out')

    scraper = _FakeScraper({})
    scraper.session = _Session()
    monkeypatch.setattr(olx_scraper.time, 'sleep', lambda s: None)

    assert OLXMieszkaniaScraper._fetch(scraper, 'https://olx/x') is None


# ── 2. detekcja wyróżnień: zapasowe źródło flagi ──────────────────────
def test_promotion_flags_reads_listing_object():
    assert _promotion_flags({'promotion': {'top_ad': True, 'highlighted': False}}) is True
    assert _promotion_flags({'promotion': {'top_ad': False, 'highlighted': False}}) is False
    # brak pola = brak wiedzy (decyduje search_reason), nie „niewyróżniona"
    assert _promotion_flags({}) is None
    assert _promotion_flags({'promotion': None}) is None
    assert _promotion_flags({'promotion': {}}) is None


def test_is_promoted_ad_prefers_any_signal():
    url = 'https://www.olx.pl/d/oferta/x-CID3-ID1.html'
    assert is_promoted_ad({'url': url + '?search_reason=search%7Cpromoted'}) is True
    assert is_promoted_ad({'url': url, 'promotion': {'top_ad': True}}) is True
    assert is_promoted_ad({'url': url, 'promotion': {'top_ad': False}}) is False
    assert is_promoted_ad({'url': url}) is False


# ── 3. potwierdzanie skokowej zmiany ceny ─────────────────────────────
def _sonar(tmp_path):
    return SonarSprzedazy(data_file=str(tmp_path / 'offers.json'),
                          removed_file=str(tmp_path / 'removed.json'))


def _existing(price):
    return {
        'id': 'otodom:1', 'source': 'otodom', 'active': True,
        'url': 'https://otodom/1', 'title': 'Mieszkanie',
        'price': {'current': price, 'history': [price]},
        'location': {},
    }


def _scraped(price):
    return {'id': 'otodom:1', 'url': 'https://otodom/1', 'title': 'Mieszkanie',
            'price': price, 'location': {}}


def test_price_jump_needs_confirmation_then_applies(tmp_path):
    sonar = _sonar(tmp_path)
    existing = _existing(78900)

    # 1. skan: skok 862% — nie ufamy, ale zapamiętujemy
    sonar._update_existing(existing, _scraped(759000))
    assert existing['price']['current'] == 78900
    assert existing['price']['pending_change']['price'] == 759000
    assert existing['price']['pending_change']['seen'] == 1

    # 2. skan: ta sama cena → potwierdzona, przyjmujemy
    sonar._update_existing(existing, _scraped(759000))
    assert existing['price']['current'] == 759000
    assert existing['price']['history'] == [78900, 759000]
    assert existing['price']['price_changes'][-1]['jump'] is True
    assert 'pending_change' not in existing['price']


def test_price_jump_reset_when_value_changes(tmp_path):
    """Jednorazowy błąd parsowania nie może się „uzbierać" — inna cena
    w kolejnym skanie zeruje licznik."""
    sonar = _sonar(tmp_path)
    existing = _existing(300000)

    sonar._update_existing(existing, _scraped(3050200))
    sonar._update_existing(existing, _scraped(2900000))
    assert existing['price']['current'] == 300000
    assert existing['price']['pending_change']['price'] == 2900000
    assert existing['price']['pending_change']['seen'] == 1


def test_price_back_to_normal_clears_pending(tmp_path):
    sonar = _sonar(tmp_path)
    existing = _existing(300000)

    sonar._update_existing(existing, _scraped(3050200))
    assert 'pending_change' in existing['price']
    sonar._update_existing(existing, _scraped(300000))
    assert 'pending_change' not in existing['price']
    assert existing['price']['current'] == 300000


def test_normal_price_change_still_immediate(tmp_path):
    sonar = _sonar(tmp_path)
    existing = _existing(500000)
    sonar._update_existing(existing, _scraped(470000))
    assert existing['price']['current'] == 470000
    assert 'jump' not in existing['price']['price_changes'][-1]
    assert PRICE_JUMP_CONFIRM_SCANS >= 2  # próg ma sens tylko >1


# ── 4. dezaktywacja przy niekompletnym listingu ───────────────────────
def test_incomplete_listing_skips_deactivation(tmp_path):
    sonar = _sonar(tmp_path)
    sonar.database['offers'] = [
        {'id': f'olx:{i}', 'source': 'olx', 'active': True,
         'last_seen': '2020-01-01T00:00:00+01:00'} for i in range(20)
    ]
    # skan zwrócił większość ofert (ochrona ilościowa NIE zadziała),
    # ale jedna strona listingu się nie pobrała
    scraped = [{'id': f'olx:{i}'} for i in range(15)]
    deactivated = sonar._mark_inactive({'olx': scraped}, incomplete_sources={'olx'})
    assert deactivated == 0
    assert all(o['active'] for o in sonar.database['offers'])


def test_complete_listing_still_deactivates(tmp_path):
    sonar = _sonar(tmp_path)
    sonar.database['offers'] = [
        {'id': f'olx:{i}', 'source': 'olx', 'active': True,
         'last_seen': '2020-01-01T00:00:00+01:00'} for i in range(20)
    ]
    scraped = [{'id': f'olx:{i}'} for i in range(15)]
    deactivated = sonar._mark_inactive({'olx': scraped})
    assert deactivated == 5


# ── 5. alert o częściowym załamaniu źródła ────────────────────────────
def _scan(olx, otodom):
    return {'scraped_olx': olx, 'scraped_otodom': otodom}


def test_partial_collapse_raises_alert():
    # dokładnie przypadek z 2026-09-04: 486 ofert zamiast ~1000
    scans = [_scan(1003, 1909), _scan(999, 1896), _scan(486, 1905)]
    alerts = compute_source_alerts(scans, {'olx': 1100, 'otodom': 1900})
    assert [a['source'] for a in alerts] == ['olx']
    a = alerts[0]
    assert a['kind'] == 'partial'
    assert a['last_scraped'] == 486
    assert a['recent_max_scraped'] == 1003
    assert a['scraped_ratio'] == 0.48


def test_normal_fluctuation_is_not_an_alert():
    scans = [_scan(1003, 1909), _scan(999, 1896), _scan(930, 1905)]
    assert compute_source_alerts(scans, {'olx': 1100, 'otodom': 1900}) == []


def test_dead_source_alert_keeps_its_kind():
    scans = [_scan(900, 1800), _scan(0, 1810)]
    alerts = compute_source_alerts(scans, {'olx': 900, 'otodom': 1800})
    assert alerts[0]['kind'] == 'dead'
