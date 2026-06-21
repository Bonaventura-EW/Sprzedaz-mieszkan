"""Otodom Scraper — mieszkania na sprzedaż w Lublinie.

Otodom (Next.js) osadza w HTML pełny stan JSON (`__NEXT_DATA__`):
- listing: tytuł, cena, powierzchnia, cena/m², liczba pokoi, piętro, ulica,
  dzielnica (reverseGeocoding), zdjęcia, paginacja, typ (`estate`) — ale BEZ
  współrzędnych i BEZ jednoznacznego rynku pierwotny/wtórny dla zwykłych ofert,
- strona szczegółów: dokładne współrzędne GPS (`ad.location.coordinates`),
  rynek (`ad.market` → PRIMARY/SECONDARY), pełny opis i charakterystykę.

Strategia (mieszkań w Lublinie są tysiące):
- listing pobieramy w CAŁOŚCI (potrzebny do poprawnej dezaktywacji),
- stronę szczegółów pobieramy TYLKO dla NOWYCH ofert i z LIMITEM na skan
  (`detail_limit`) — reszta dobierze się w kolejnych skanach. Dzięki temu
  pierwszy skan nie robi tysięcy zapytań i nie ściąga na siebie blokady.

Rynek pierwotny/wtórny:
- `estate == 'INVESTMENT'` (oferta deweloperska/inwestycja) → pierwotny już
  z listingu,
- dla `estate == 'FLAT'` rynek znamy dopiero ze strony szczegółów (`ad.market`);
  do tego czasu oferta ma rynek 'nieokreslony'.
"""

import json
import re
import time
import random
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from cid import otodom_offer_id
from olx_scraper import strip_html  # ten sam helper czyszczenia HTML


LISTING_URL = (
    "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/lubelskie/lublin/lublin/lublin"
    "?ownerTypeSingleSelect=ALL&limit=72"
)
OFFER_BASE_URL = "https://www.otodom.pl/pl/oferta/"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pl,en-US;q=0.7,en;q=0.3',
}

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)

MARKET_MAP = {'primary': 'pierwotny', 'secondary': 'wtorny',
              'PRIMARY': 'pierwotny', 'SECONDARY': 'wtorny'}

ROOMS_MAP = {
    'ONE': 1, 'TWO': 2, 'THREE': 3, 'FOUR': 4, 'FIVE': 5,
    'SIX': 6, 'SEVEN': 7, 'EIGHT': 8, 'NINE': 9, 'TEN': 10,
}

FLOOR_MAP = {
    'GROUND': 'parter', 'CELLAR': 'suterena', 'GARRET': 'poddasze',
    'FIRST': '1', 'SECOND': '2', 'THIRD': '3', 'FOURTH': '4', 'FIFTH': '5',
    'SIXTH': '6', 'SEVENTH': '7', 'EIGHTH': '8', 'NINTH': '9', 'TENTH': '10',
    'ABOVE_TENTH': '>10',
}


def extract_next_data(html: str) -> Optional[dict]:
    """Wyciąga i parsuje JSON `__NEXT_DATA__` ze strony Otodom."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"⚠️ Otodom: błąd parsowania __NEXT_DATA__: {e}")
        return None


def _district_from_geocoding(location: dict) -> Optional[str]:
    """Wyciąga nazwę dzielnicy z reverseGeocoding listingu Otodom."""
    locations = ((location or {}).get('reverseGeocoding') or {}).get('locations') or []
    for loc in locations:
        if loc.get('locationLevel') == 'district':
            return loc.get('name')
    return None


def _parse_floor(raw: Optional[str]) -> Optional[str]:
    """floor_no z charakterystyki ('floor_2') / floorNumber ('SECOND') → etykieta."""
    if not raw:
        return None
    if raw in FLOOR_MAP:
        return FLOOR_MAP[raw]
    m = re.match(r'floor_(\d+)', raw)
    if m:
        return m.group(1) if m.group(1) != '0' else 'parter'
    return raw


def normalize_item(item: dict) -> Optional[Dict]:
    """Normalizuje pozycję listingu Otodom do wspólnego schematu."""
    numeric_id = item.get('id')
    slug = item.get('slug')
    if not numeric_id or not slug:
        return None

    total_price = (item.get('totalPrice') or {}).get('value')
    if not isinstance(total_price, (int, float)):
        return None  # oferty z ukrytą ceną / agregaty inwestycji pomijamy
    price = int(total_price)

    area = item.get('areaInSquareMeters')
    per_m2 = (item.get('pricePerSquareMeter') or {}).get('value')
    if per_m2 is None and area:
        per_m2 = round(price / area, 2)

    rooms = ROOMS_MAP.get(item.get('roomsNumber'))
    floor = _parse_floor(item.get('floorNumber'))

    # rynek: oferta inwestycyjna/deweloperska = pierwotny; reszta dopiero
    # ze strony szczegółów (ad.market)
    market = 'pierwotny' if item.get('estate') == 'INVESTMENT' else 'nieokreslony'

    location = item.get('location') or {}
    address = location.get('address') or {}
    street = ((address.get('street') or {}).get('name') or '').strip() or None
    city = ((address.get('city') or {}).get('name') or '').strip() or None

    images = item.get('images') or []
    image = images[0].get('medium') if images else None

    return {
        'id': otodom_offer_id(numeric_id),
        'source': 'otodom',
        'url': OFFER_BASE_URL + slug,
        'title': (item.get('title') or '').strip(),
        'price': price,
        'area_m2': float(area) if area else None,
        'price_per_m2': float(per_m2) if per_m2 else None,
        'market': market,
        'rooms': rooms,
        'floor': floor,
        'location': {
            'city': city,
            'district': _district_from_geocoding(location),
            'street': street,
            'coords': None,  # coords są dopiero na stronie szczegółów
            'coords_precision': None,
        },
        'description': (item.get('shortDescription') or '').strip(),
        'is_private_owner': bool(item.get('isPrivateOwner')),
        'image': image,
        'created_at': item.get('createdAtFirst') or item.get('dateCreated'),
    }


class OtodomMieszkaniaScraper:
    def __init__(self, delay_range=(0.5, 1.2), max_workers: int = 4):
        self.delay_min, self.delay_max = delay_range
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _fetch(self, url: str) -> Optional[str]:
        try:
            r = self.session.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            print(f"❌ Otodom: błąd pobierania {url}: {e}")
            return None

    def _scrape_listing(self, max_pages: int) -> List[Dict]:
        offers: List[Dict] = []
        seen_ids = set()
        total_pages = 1

        for page in range(1, max_pages + 1):
            if page > total_pages:
                break
            html = self._fetch(f"{LISTING_URL}&page={page}")
            if not html:
                break
            data = extract_next_data(html)
            if not data:
                print(f"⚠️ Otodom: brak __NEXT_DATA__ na stronie {page}")
                break

            search_ads = (((data.get('props') or {}).get('pageProps') or {})
                          .get('data') or {}).get('searchAds') or {}
            items = search_ads.get('items') or []
            pagination = search_ads.get('pagination') or {}
            total_pages = pagination.get('totalPages') or total_pages

            print(f"📄 Otodom strona {page}/{total_pages}: {len(items)} ogłoszeń "
                  f"(łącznie w serwisie: {pagination.get('totalItems')})")

            for item in items:
                offer = normalize_item(item)
                if not offer or offer['id'] in seen_ids:
                    continue
                seen_ids.add(offer['id'])
                offers.append(offer)

            if not items:
                break
            time.sleep(random.uniform(self.delay_min, self.delay_max))

        return offers

    def fetch_details(self, offer: Dict) -> Dict:
        """Dociąga ze strony szczegółów: dokładne coords, rynek, opis, piętro/pokoje."""
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        html = self._fetch(offer['url'])
        if not html:
            return offer
        data = extract_next_data(html)
        if not data:
            return offer

        ad = ((data.get('props') or {}).get('pageProps') or {}).get('ad') or {}
        location = ad.get('location') or {}

        coords = location.get('coordinates') or {}
        if coords.get('latitude') and coords.get('longitude'):
            offer['location']['coords'] = {
                'lat': coords['latitude'], 'lon': coords['longitude']
            }
            # radius > 0 = ogłoszeniodawca NIE wskazał dokładnego punktu (Otodom
            # pokazuje okrąg). Takie coords to często centroid dzielnicy — nie
            # udawajmy, że są dokładne (precyzja 'approx' zostanie potem albo
            # podniesiona do 'street', albo usunięta jako dezinformacja).
            radius = (location.get('mapDetails') or {}).get('radius') or 0
            offer['location']['coords_precision'] = 'exact' if radius == 0 else 'approx'

        market = ad.get('market')
        if market in MARKET_MAP:
            offer['market'] = MARKET_MAP[market]

        description = strip_html(ad.get('description') or '')
        if len(description) > len(offer.get('description') or ''):
            offer['description'] = description

        for char in ad.get('characteristics') or []:
            key, val = char.get('key'), char.get('value')
            if key == 'rooms_num' and not offer.get('rooms'):
                try:
                    offer['rooms'] = int(re.sub(r'\D', '', val or ''))
                except ValueError:
                    pass
            elif key == 'floor_no' and not offer.get('floor'):
                offer['floor'] = _parse_floor(val)
            elif key == 'market' and offer.get('market') == 'nieokreslony' \
                    and val in MARKET_MAP:
                offer['market'] = MARKET_MAP[val]

        offer['_details_fetched'] = True
        return offer

    def scrape(self, max_pages: int = 50, known_offers: Dict = None,
               detail_limit: int = 120) -> List[Dict]:
        """Pobiera listing + szczegóły (tylko dla nowych ofert, z limitem na skan).

        Args:
            known_offers: {offer_id: {'coords', 'coords_precision', 'market',
                           'rooms', 'floor', 'description', '_details_fetched'}}
                           — dane z poprzednich skanów, pozwalają pominąć detale.
            detail_limit: maks. liczba stron szczegółów pobieranych w tym skanie
                          (reszta nowych ofert dobierze się następnym razem).
        """
        known_offers = known_offers or {}
        print("🔍 Otodom: scraping mieszkań na sprzedaż (Lublin)...")
        offers = self._scrape_listing(max_pages)
        print(f"✅ Otodom: listing dał {len(offers)} ofert")

        to_fetch = []
        for offer in offers:
            known = known_offers.get(offer['id'])
            if known and known.get('_details_fetched'):
                # przenosimy dane z poprzedniego skanu — bez ponownego pobierania
                if known.get('coords'):
                    offer['location']['coords'] = known['coords']
                    offer['location']['coords_precision'] = known.get('coords_precision', 'exact')
                if known.get('market') and known['market'] != 'nieokreslony':
                    offer['market'] = known['market']
                offer['rooms'] = offer.get('rooms') or known.get('rooms')
                offer['floor'] = offer.get('floor') or known.get('floor')
                if known.get('description') and \
                        len(known['description']) > len(offer.get('description') or ''):
                    offer['description'] = known['description']
                offer['_details_fetched'] = True
            else:
                to_fetch.append(offer)

        # limit pobrań szczegółów na pojedynczy skan
        capped = to_fetch[:detail_limit]
        if len(to_fetch) > detail_limit:
            print(f"⏳ Otodom: {len(to_fetch)} nowych ofert, pobieram szczegóły "
                  f"{detail_limit} (reszta w kolejnych skanach)")

        if capped:
            print(f"⚡ Otodom: pobieram szczegóły {len(capped)} ofert "
                  f"({self.max_workers} wątków)...")
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self.fetch_details, o): o for o in capped}
                done = 0
                for future in as_completed(futures):
                    done += 1
                    try:
                        future.result()
                    except Exception as e:  # pojedyncza oferta nie wali skanu
                        print(f"\n⚠️ Otodom: błąd szczegółów: {e}")
                    print(f"\r   Postęp: [{done}/{len(capped)}]", end='', flush=True)
            print()
        else:
            print("✅ Otodom: brak nowych ofert do pobrania szczegółów")

        print(f"✅ Otodom: zebrano {len(offers)} ofert\n")
        return offers


if __name__ == "__main__":
    scraper = OtodomMieszkaniaScraper(delay_range=(0.3, 0.8))
    result = scraper.scrape(max_pages=1, detail_limit=3)
    print(f"Łącznie: {len(result)}")
    if result:
        for k, v in result[0].items():
            print(f"  {k}: {str(v)[:100]}")
