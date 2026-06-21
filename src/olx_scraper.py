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

import requests

from cid import olx_offer_id


# Listing mieszkań na sprzedaż w Lublinie (rynek pierwotny + wtórny razem)
LISTING_URL = "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/lublin/"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pl,en-US;q=0.7,en;q=0.3',
}

_STATE_RE = re.compile(r'window\.__PRERENDERED_STATE__\s*=\s*"(.*)";')
_TAG_RE = re.compile(r'<[^>]+>')

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
    def __init__(self, delay_range=(1.0, 2.0)):
        self.delay_min, self.delay_max = delay_range
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _fetch(self, url: str) -> Optional[str]:
        try:
            r = self.session.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            print(f"❌ OLX: błąd pobierania {url}: {e}")
            return None

    def scrape(self, max_pages: int = 25) -> List[Dict]:
        """Pobiera wszystkie strony listingu i zwraca znormalizowane oferty."""
        print("🔍 OLX: scraping mieszkań na sprzedaż (Lublin)...")
        offers: List[Dict] = []
        seen_ids = set()

        for page in range(1, max_pages + 1):
            url = LISTING_URL if page == 1 else f"{LISTING_URL}?page={page}"
            html = self._fetch(url)
            if not html:
                break

            state = decode_prerendered_state(html)
            if not state:
                print(f"⚠️ OLX: brak stanu JSON na stronie {page}")
                break

            listing = (state.get('listing') or {}).get('listing') or {}
            ads = listing.get('ads') or []
            total = listing.get('totalElements')
            print(f"📄 OLX strona {page}: {len(ads)} ogłoszeń (łącznie w serwisie: {total})")

            new_on_page = 0
            for ad in ads:
                # OLX dokleja na końcu wyniki "z okolicy" — pilnujemy miasta
                city = ((ad.get('location') or {}).get('cityNormalizedName') or '').lower()
                if city and city != 'lublin':
                    continue
                offer = normalize_ad(ad)
                if not offer or offer['id'] in seen_ids:
                    continue
                seen_ids.add(offer['id'])
                offers.append(offer)
                new_on_page += 1

            # koniec paginacji TYLKO gdy strona jest pusta — strona z samymi
            # powtórkami / wynikami "z okolicy" nie może ucinać kolejnych stron
            if not ads:
                break
            if total and len(seen_ids) >= total:
                break
            if new_on_page == 0 and page > 1:
                # strona 2+ bez żadnej nowej oferty = koniec (OLX powtarza
                # ostatnią stronę dla page > max)
                break

            time.sleep(random.uniform(self.delay_min, self.delay_max))

        print(f"✅ OLX: zebrano {len(offers)} ofert\n")
        return offers


if __name__ == "__main__":
    scraper = OLXMieszkaniaScraper(delay_range=(0.5, 1.0))
    result = scraper.scrape(max_pages=3)
    print(f"Łącznie: {len(result)}")
    if result:
        for k, v in result[0].items():
            print(f"  {k}: {str(v)[:100]}")
