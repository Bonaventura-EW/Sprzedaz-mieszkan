"""OLX Scraper — mieszkania na sprzedaż w Lublinie.

Tak jak w SONARZE DZIAŁKOWYM nie parsujemy HTML kart ogłoszeń: OLX osadza
w listingu pełny stan JSON (`window.__PRERENDERED_STATE__`), który zawiera dla
każdego ogłoszenia m.in.:
- rynek (`params.market` → primary / secondary),
- cenę (`price.regularPrice.value`),
- powierzchnię, cenę za m², liczbę pokoi, piętro (`params`),
- typ zabudowy, pełny opis (HTML).

⚠️ WAŻNE: dla mieszkań OLX podaje w listingu **centroid miasta** (te same
współrzędne dla wszystkich ofert, radius 3–6 km), a nie przybliżony punkt
oferty jak przy działkach. Taka pinezka to dezinformacja, więc OLX-owi NIE
ustawiamy współrzędnych — lokalizację bierzemy wyłącznie z ulicy wykrytej
w tytule/opisie (`location_refiner.py`). To realizuje zasadę projektu:
„pinezka tylko gdy szczegółowy adres jest w tytule lub treści ogłoszenia".
"""

import json
import re
import time
import random
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import requests

# FIX 2026-08-22: OLX zaczął zwracać 0 ofert (blokada WAF po TLS fingerprincie —
# `requests` ma charakterystyczny „pythonowy" JA3). curl_cffi z impersonate
# podszywa się pod prawdziwy TLS Chrome'a i przechodzi przez WAF. Gdy biblioteki
# nie ma (środowisko bez curl_cffi), spadamy z powrotem do requests, żeby nic
# nie wywalić — patrz OLXMieszkaniaScraper.__init__.
try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    _HAS_CFFI = True
except ImportError:  # pragma: no cover - zależne od środowiska
    cffi_requests = None
    _HAS_CFFI = False

from cid import olx_offer_id


# FIX 2026-08-27: obszar zbierania to Lublin + Świdnik — osobny listing na miasto
# (rynek pierwotny + wtórny razem). OLX dokleja do listingu wyniki „z okolicy",
# więc Świdnik częściowo wpadał już z listingu lubelskiego, ale niekompletnie —
# dlatego pobieramy go własnym listingiem, a `ALLOWED_CITIES` pilnuje, żeby nie
# wpuścić przy okazji Mełgwi czy Piask.
LISTING_URLS = {
    'lublin': "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/lublin/",
    'swidnik': "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/swidnik/",
}
ALLOWED_CITIES = set(LISTING_URLS)  # wg `cityNormalizedName` z listingu

# zgodność wsteczna dla importów spoza modułu
LISTING_URL = LISTING_URLS['lublin']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pl,en-US;q=0.7,en;q=0.3',
}

_STATE_RE = re.compile(r'window\.__PRERENDERED_STATE__\s*=\s*"(.*)";')
_TAG_RE = re.compile(r'<[^>]+>')

# FIX 2026-09-06: pojedynczy timeout strony potrafił skasować resztę listingu.
# `_fetch` nie miał retry, a `_scrape_city` na `None` robiło `break` — czyli
# jeden `curl: (28)` na stronie 9 ucinał strony 9–24. W logach: 2026-09-02
# (407 ofert zamiast ~1000) i 2026-09-04 (486). Teraz: 3 próby na stronę
# z narastającą przerwą, a nieudana strona jest POMIJANA, nie kończy paginacji;
# dopiero 3 nieudane strony z rzędu (= realna blokada, nie chwilowy timeout)
# przerywają listing miasta.
REQUEST_TIMEOUT_S = 20
FETCH_ATTEMPTS = 3
FETCH_BACKOFF_S = (3, 8)          # przerwa po 1. i 2. nieudanej próbie
MAX_CONSECUTIVE_PAGE_FAILURES = 3
# Bezpiecznik czasu: nieudana strona kosztuje ~70 s (3 próby × timeout + przerwy),
# więc rwący się listing bez tego limitu rozciągnąłby skan z ~2 na ~20 minut.
MAX_PAGE_FAILURES_PER_CITY = 6

# Mapowanie rynku OLX (param `market`) na wspólne nazwy
MARKET_MAP = {
    'primary': 'pierwotny',
    'secondary': 'wtorny',
}

# Liczba pokoi: OLX podaje słownie (param `rooms`)
ROOMS_MAP = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
}

# Piętro: OLX param `floor_select` (floor_0 = parter, floor_10 = 10, itd.)
FLOOR_MAP = {
    'floor_0': 'parter',
    'ground_floor': 'parter',
    'cellar': 'suterena',
    'basement': 'suterena',
    'garret': 'poddasze',
    'floor_higher_10': '>10',
}


def strip_html(text: str) -> str:
    """Usuwa tagi HTML z opisu (OLX trzyma opis jako HTML)."""
    if not text:
        return ''
    text = text.replace('</p>', '\n').replace('<br>', '\n').replace('<br/>', '\n')
    return _TAG_RE.sub('', text).strip()


def decode_prerendered_state(html: str) -> Optional[dict]:
    """Wyciąga i dekoduje `window.__PRERENDERED_STATE__` z HTML listingu.

    Stan jest zapisany jako escapowany string JS. Po unicode_escape polskie
    znaki są zepsute (bajty UTF-8 zinterpretowane jako latin-1) — naprawiamy
    re-enkodowaniem latin-1 → utf-8.
    """
    m = _STATE_RE.search(html)
    if not m:
        return None
    raw = m.group(1).encode('utf-8').decode('unicode_escape')
    try:
        raw = raw.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass  # stan był już poprawnym tekstem
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ OLX: nie udało się sparsować __PRERENDERED_STATE__: {e}")
        return None


def _param(ad: dict, key: str) -> Optional[str]:
    """Zwraca normalizedValue parametru ogłoszenia OLX o danym kluczu."""
    for p in ad.get('params') or []:
        if p.get('key') == key:
            return p.get('normalizedValue') or p.get('value')
    return None


def _parse_floor(raw: Optional[str]) -> Optional[str]:
    """floor_select OLX → czytelna etykieta piętra ('parter', '3', '>10')."""
    if not raw:
        return None
    if raw in FLOOR_MAP:
        return FLOOR_MAP[raw]
    m = re.match(r'floor_(\d+)', raw)
    if m:
        return m.group(1)
    return raw


# FIX 2026-09-01: detekcja płatnych wyróżnień na listingu OLX (propagacja
# z SONAR-POKOJOWY). OLX doszywa do href-a/URL-a oferty parametr atrybucji
# `search_reason=search|promoted` (organiczne: `search|organic`). To pewniejszy
# sygnał niż klasy CSS czy `data-testid`, bo generuje go serwer OLX, nie warstwa
# prezentacji. U nas URL jest dostępny w `__PRERENDERED_STATE__` z pełnym query
# stringiem PRZED przycięciem do zapisu (`url.split('?')[0]`), więc czytamy go
# w `normalize_ad`. Metryka liczy się dopiero od wdrożenia — wyróżnienia to stan
# chwilowy listingu, nie da się go odtworzyć wstecz.
def _is_promoted_href(url: str) -> bool:
    """Czy oferta jest PŁATNIE WYRÓŻNIONA na listingu (parametr `search_reason`)?"""
    if '?' not in (url or ''):
        return False
    try:
        reasons = parse_qs(urlparse(url).query).get('search_reason', [])
    except ValueError:
        return False
    return any('promoted' in r.lower() for r in reasons)


# FIX 2026-09-06: od wdrożenia metryki (2026-09-03) ŻADNA oferta nie miała
# `search_reason` — kanarek `cards>0 && attributed==0` alarmował w każdym skanie,
# a szereg „⭐ wyróżnienia" na trend.html rysował płaskie zero. W listingu OLX
# obok URL-a bywa jednak własny obiekt `promotion` (`top_ad` = wypchnięcie na
# górę, `highlighted` = podświetlenie karty — oba płatne). Czytamy go jako
# ZAPASOWE źródło flagi: gdy OLX przestał doszywać atrybucję do URL-a, metryka
# wraca; gdy pola nie ma, `_promotion_flags` zwraca pustkę i nic się nie zmienia.
# Diagnostyka w `scrape()` dopisuje do logu, co OLX faktycznie zwraca, więc
# następny skan rozstrzyga jednoznacznie.
PROMOTION_PAID_KEYS = ('top_ad', 'highlighted', 'urgent', 'premium_ad_page')


def _promotion_flags(ad: dict) -> Optional[bool]:
    """Płatne wyróżnienie z obiektu `promotion` listingu OLX.

    Zwraca None, gdy ogłoszenie w ogóle nie niesie takiego obiektu (nie wiemy
    nic — decyduje `search_reason`), True/False gdy niesie.
    """
    promotion = ad.get('promotion')
    if not isinstance(promotion, dict):
        return None
    flags = [bool(promotion.get(k)) for k in PROMOTION_PAID_KEYS if k in promotion]
    if not flags:
        return None
    return any(flags)


def is_promoted_ad(ad: dict) -> bool:
    """Flaga płatnego wyróżnienia: parametr atrybucji LUB obiekt `promotion`."""
    if _is_promoted_href(ad.get('url') or ''):
        return True
    return _promotion_flags(ad) is True


def normalize_ad(ad: dict) -> Optional[Dict]:
    """Normalizuje ogłoszenie OLX do wspólnego schematu SONARA SPRZEDAŻY MIESZKAŃ."""
    url = ad.get('url') or ''
    if not url:
        return None

    price = None
    price_info = ad.get('price') or {}
    regular = price_info.get('regularPrice') or {}
    if isinstance(regular.get('value'), (int, float)):
        price = int(regular['value'])
    if not price:
        return None  # bez ceny oferta jest bezużyteczna

    area = None
    raw_area = _param(ad, 'm')
    try:
        area = float(raw_area) if raw_area else None
    except ValueError:
        area = None

    per_m2 = None
    raw_per_m2 = _param(ad, 'price_per_m')
    try:
        per_m2 = float(raw_per_m2) if raw_per_m2 else None
    except ValueError:
        pass
    if per_m2 is None and area:
        per_m2 = round(price / area, 2)

    market = MARKET_MAP.get(_param(ad, 'market') or '', 'nieokreslony')

    rooms = None
    raw_rooms = _param(ad, 'rooms')
    if raw_rooms:
        rooms = ROOMS_MAP.get(raw_rooms)
        if rooms is None:
            try:
                rooms = int(re.sub(r'\D', '', raw_rooms))
            except ValueError:
                rooms = None

    floor = _parse_floor(_param(ad, 'floor_select'))

    location = ad.get('location') or {}
    photos = ad.get('photos') or []

    return {
        'id': olx_offer_id(url),
        'source': 'olx',
        'url': url.split('?')[0],
        # płatne wyróżnienie: parametr atrybucji (czytany z PEŁNEGO url powyżej,
        # zanim przytniemy query string do zapisu) LUB obiekt `promotion`
        # z listingu — patrz _is_promoted_href / _promotion_flags
        'promoted': is_promoted_ad(ad),
        'title': ad.get('title', '').strip(),
        'price': price,
        'area_m2': area,
        'price_per_m2': per_m2,
        'market': market,
        'rooms': rooms,
        'floor': floor,
        'location': {
            'city': location.get('cityName'),
            'district': location.get('districtName'),
            'street': None,  # OLX nie podaje ulicy w listingu
            # OLX dla mieszkań podaje centroid miasta — celowo BEZ coords,
            # pinezkę uzupełnia location_refiner z ulicy w tytule/opisie
            'coords': None,
            'coords_precision': None,
        },
        'description': strip_html(ad.get('description', '')),
        'is_private_owner': not ad.get('isBusiness', False),
        'image': photos[0] if photos else None,
        'created_at': ad.get('createdTime'),
    }


class OLXMieszkaniaScraper:
    # marka impersonacji dla curl_cffi (aktualna wersja Chrome — bije JA3 WAF-a)
    IMPERSONATE = "chrome"

    def __init__(self, delay_range=(1.0, 2.0)):
        self.delay_min, self.delay_max = delay_range
        # Statystyki wyróżnień (płatne promowanie): `attributed` = ile ofert
        # niosło w ogóle parametr `search_reason`. attributed == 0 przy niepustym
        # listingu znaczy, że OLX zmienił format atrybucji i metryka promowanych
        # po cichu spadłaby do zera — o tym alarmuje `scrape()`.
        self.promoted_stats = {'cards': 0, 'attributed': 0, 'promoted': 0,
                               'promotion_field': 0}
        # próbka pierwszego ogłoszenia — zasila diagnostykę wyróżnień w logu
        self._promotion_sample: Optional[dict] = None
        # FIX 2026-09-06: strony listingu, których nie udało się pobrać mimo
        # ponowień. Niepusta lista = skan OLX jest NIEKOMPLETNY; main.py
        # pomija wtedy dezaktywację tego źródła (brak oferty w skanie może
        # znaczyć „nie doczytaliśmy strony", a nie „oferta zniknęła").
        self.failed_pages: List[str] = []
        # FIX 2026-08-22: preferuj curl_cffi (impersonacja TLS Chrome) — OLX
        # blokuje „pythonowy" fingerprint requests. Fallback do requests, gdy
        # curl_cffi niedostępne.
        if _HAS_CFFI:
            self.session = cffi_requests.Session(impersonate=self.IMPERSONATE)
            # impersonate ustawia komplet nagłówków przeglądarki; dokładamy tylko
            # preferencję języka (polski listing)
            self.session.headers.update({'Accept-Language': HEADERS['Accept-Language']})
            self.engine = 'curl_cffi'
        else:
            self.session = requests.Session()
            self.session.headers.update(HEADERS)
            self.engine = 'requests'
        print(f"🌐 OLX: silnik HTTP = {self.engine}"
              + ("" if _HAS_CFFI else " (curl_cffi niedostępne — możliwa blokada WAF)"))

    def _fetch(self, url: str) -> Optional[str]:
        """Pobiera stronę z ponowieniami — patrz FIX 2026-09-06 na górze pliku.

        Timeout OLX-a bywa chwilowy (jedna strona listingu na kilkaset), więc
        ponawiamy zamiast od razu odpuszczać. Zwraca None dopiero po wyczerpaniu
        wszystkich prób.
        """
        last_error = None
        for attempt in range(1, FETCH_ATTEMPTS + 1):
            try:
                r = self.session.get(url, timeout=REQUEST_TIMEOUT_S)
                r.raise_for_status()
                return r.text
            except Exception as e:  # curl_cffi rzuca własne wyjątki; łapiemy szeroko
                last_error = e
                if attempt < FETCH_ATTEMPTS:
                    wait = FETCH_BACKOFF_S[min(attempt - 1, len(FETCH_BACKOFF_S) - 1)]
                    print(f"   ⚠️ OLX: próba {attempt}/{FETCH_ATTEMPTS} nieudana "
                          f"({type(e).__name__}) — ponawiam za {wait}s: {url}")
                    time.sleep(wait)
        print(f"❌ OLX: błąd pobierania {url} po {FETCH_ATTEMPTS} próbach: {last_error}")
        return None

    def scrape(self, max_pages: int = 25) -> List[Dict]:
        """Pobiera listingi wszystkich obsługiwanych miast i zwraca oferty.

        `seen_ids` jest wspólne dla miast: ta sama oferta bywa w obu listingach
        (OLX dokleja wyniki „z okolicy"), a chcemy ją policzyć raz.
        """
        offers: List[Dict] = []
        seen_ids = set()
        for city, listing_url in LISTING_URLS.items():
            self._scrape_city(city, listing_url, max_pages, offers, seen_ids)
        ps = self.promoted_stats
        print(f"✅ OLX: zebrano {len(offers)} ofert "
              f"(⭐ wyróżnionych: {ps['promoted']})\n")
        # FIX 2026-09-06: skan z pominiętymi stronami jest NIEKOMPLETNY —
        # trzeba to widzieć w logu i przekazać dalej (main pomija dezaktywację).
        if self.failed_pages:
            print(f"⚠️ OLX: skan NIEKOMPLETNY — nie pobrano stron: "
                  f"{', '.join(self.failed_pages)}\n")
        self._report_promotion_health()
        return offers

    def _report_promotion_health(self) -> None:
        """Alarm + diagnostyka detekcji płatnych wyróżnień (FIX 2026-09-06).

        Kanarek z propagacji (SONAR-POKOJOWY) alarmował „brak search_reason", ale
        nie mówił, CO OLX zwraca zamiast tego — przez co przez kilka dni nie dało
        się rozstrzygnąć, czy to zmiana po stronie portalu, czy nasz błąd odczytu.
        Teraz log niesie próbkę: klucze ogłoszenia i kształt pola `promotion`.
        """
        ps = self.promoted_stats
        if not ps['cards']:
            return
        if ps['attributed']:
            return  # atrybucja w URL-u działa — nic do zgłaszania

        if ps['promotion_field'] and ps['promoted']:
            print(f"ℹ️ OLX: brak parametru search_reason, ale {ps['promotion_field']} "
                  f"ofert niesie pole `promotion` — wyróżnienia liczone z niego\n")
            return

        if ps['promotion_field']:
            # pole jest, ale ZERO wyróżnionych w całym listingu — na tysiącu
            # ogłoszeń to nieprawdopodobne, więc traktujemy jak zepsuty odczyt,
            # a nie „nikt nie płaci za wyróżnienie"
            print(f"🚨 OLX: pole `promotion` niesie {ps['promotion_field']} ofert, "
                  f"ale ŻADNA nie jest wyróżniona — podejrzany odczyt "
                  f"(sprawdź klucze {PROMOTION_PAID_KEYS})\n")
            return

        print("🚨 OLX: żadna oferta nie miała ani parametru search_reason, ani pola "
              "`promotion` — detekcja wyróżnień NIE DZIAŁA!")
        sample = self._promotion_sample or {}
        if sample:
            print(f"   🔬 diagnostyka: url z query stringiem = {sample.get('has_query')}, "
                  f"url = {sample.get('url')}")
            print(f"   🔬 klucze ogłoszenia: {sample.get('keys')}")
        print()

    def _scrape_city(self, city: str, listing_url: str, max_pages: int,
                     offers: List[Dict], seen_ids: set) -> None:
        """Paginuje listing jednego miasta, dopisując oferty do `offers`."""
        print(f"🔍 OLX: scraping mieszkań na sprzedaż ({city.capitalize()})...")
        before = len(offers)

        consecutive_failures = city_failures = 0

        for page in range(1, max_pages + 1):
            url = listing_url if page == 1 else f"{listing_url}?page={page}"
            html = self._fetch(url)
            state = decode_prerendered_state(html) if html else None

            # FIX 2026-09-06: nieudana strona NIE kończy listingu miasta —
            # pomijamy ją i lecimy dalej. Paginację przerywa dopiero seria
            # MAX_CONSECUTIVE_PAGE_FAILURES błędów (wtedy to nie chwilowy
            # timeout, tylko blokada i dalsze dobijanie się nie ma sensu).
            if not state:
                if html:
                    print(f"⚠️ OLX: brak stanu JSON na stronie {page}")
                consecutive_failures += 1
                city_failures += 1
                self.failed_pages.append(f"{city}/{page}")
                if consecutive_failures >= MAX_CONSECUTIVE_PAGE_FAILURES:
                    print(f"⛔ OLX {city}: {consecutive_failures} nieudanych stron "
                          f"z rzędu — przerywam paginację (możliwa blokada portalu)")
                    break
                if city_failures >= MAX_PAGE_FAILURES_PER_CITY:
                    print(f"⛔ OLX {city}: {city_failures} nieudanych stron w tym "
                          f"listingu — przerywam paginację (bezpiecznik czasu)")
                    break
                print(f"   ⏭️ OLX {city}: pomijam stronę {page}, przechodzę do kolejnej")
                time.sleep(random.uniform(self.delay_min, self.delay_max))
                continue
            consecutive_failures = 0

            listing = (state.get('listing') or {}).get('listing') or {}
            ads = listing.get('ads') or []
            total = listing.get('totalElements')
            print(f"📄 OLX {city} strona {page}: {len(ads)} ogłoszeń "
                  f"(łącznie w serwisie: {total})")

            new_on_page = 0
            for ad in ads:
                # OLX dokleja na końcu wyniki "z okolicy" — pilnujemy miasta.
                # Oferta z sąsiedniego miasta Z NASZEJ listy jest OK (dublet
                # odsieje `seen_ids`); spoza listy — odrzucamy.
                ad_city = ((ad.get('location') or {}).get('cityNormalizedName') or '').lower()
                if ad_city and ad_city not in ALLOWED_CITIES:
                    continue
                offer = normalize_ad(ad)
                if not offer or offer['id'] in seen_ids:
                    continue
                seen_ids.add(offer['id'])
                self.promoted_stats['cards'] += 1
                if 'search_reason=' in (ad.get('url') or ''):
                    self.promoted_stats['attributed'] += 1
                if _promotion_flags(ad) is not None:
                    self.promoted_stats['promotion_field'] += 1
                if offer.get('promoted'):
                    self.promoted_stats['promoted'] += 1
                if self._promotion_sample is None:
                    # próbka dla diagnostyki — patrz _report_promotion_health
                    raw_url = ad.get('url') or ''
                    self._promotion_sample = {
                        'has_query': '?' in raw_url,
                        'url': raw_url[:160],
                        'keys': sorted(ad.keys()),
                    }
                offers.append(offer)
                new_on_page += 1

            # koniec paginacji TYLKO gdy strona jest pusta — strona z samymi
            # powtórkami / wynikami "z okolicy" nie może ucinać kolejnych stron
            if not ads:
                break
            if total and len(offers) - before >= total:
                break
            if new_on_page == 0 and page > 1:
                # strona 2+ bez żadnej nowej oferty = koniec (OLX powtarza
                # ostatnią stronę dla page > max)
                break

            time.sleep(random.uniform(self.delay_min, self.delay_max))

        print(f"   → {city}: {len(offers) - before} ofert")


if __name__ == "__main__":
    scraper = OLXMieszkaniaScraper(delay_range=(0.5, 1.0))
    result = scraper.scrape(max_pages=3)
    print(f"Łącznie: {len(result)}")
    if result:
        for k, v in result[0].items():
            print(f"  {k}: {str(v)[:100]}")
