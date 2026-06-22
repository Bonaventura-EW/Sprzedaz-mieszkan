"""Doprecyzowanie lokalizacji ofert: ulica z tytułu/opisu → współrzędne.

Główna zasada projektu: **pinezka pojawia się tylko wtedy, gdy znamy szczegółowy
adres** — czyli ulicę z tytułu lub treści ogłoszenia (albo dokładny punkt
wskazany przez ogłoszeniodawcę na Otodom). OLX dla mieszkań nie podaje sensownej
lokalizacji (centroid miasta), więc dla niego ulica z tekstu to jedyne źródło.

Ten moduł:
1. wyciąga kandydatów na ulicę z tekstu (regex po prefiksach ul./ulica/al.),
2. normalizuje polską odmianę (dopełniacz → mianownik: „Wyżynnej" → „Wyżynna"),
3. geokoduje przez Nominatim (zapytanie strukturalne street+city, cache na
   dysku, limit 1 req/s) i zwraca punkt TYLKO gdy leży w Lublinie.

Oferty z dokładnymi coords (Otodom, precyzja 'exact') nie są ruszane.
Po udanym geokodowaniu oferta dostaje precyzję 'street' (lepsze niż 'approx',
gorsze niż 'exact'). Celowo NIE robimy fallbacku do centroidu dzielnicy —
pinezka ma oznaczać konkretny adres, a nie „gdzieś w dzielnicy".
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

import paths

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {'User-Agent': 'SONAR-SPRZEDAZY/1.0 (github.com/Bonaventura-EW/Sprzedaz-mieszkan)'}
CACHE_FILE = Path(paths.DATA_DIR) / "geocoding_cache.json"
NEGATIVE_TTL_S = 7 * 24 * 3600  # nieudane zapytania ponawiamy po tygodniu

# Granice Lublina z marginesem — wynik spoza nich odrzucamy
LUBLIN_BBOX = {'lat_min': 51.10, 'lat_max': 51.36, 'lon_min': 22.40, 'lon_max': 22.78}

# ulica musi zaczynać się wielką literą; łapiemy do 3 słów (np. "Gen. Urbanowicza").
# Kropka po „ul"/„al" jest OPCJONALNA — sprzedający często piszą „ul Lipińskiego"
# bez kropki (\bul\b zapobiega łapaniu „ul" wewnątrz słów typu „ulica").
_STREET_RE = re.compile(
    r'(?:\b(?:ul|al)\b\.?\s*|\b(?:ulic[ayę]|ulicą|alei|alej[aę])\s+|\bprzy\s+ul\b\.?\s*)'
    r'([A-ZŚĆŁŻŹÓĄĘŃ][\wąęółśżźćń]+\.?(?:[ \-][A-ZŚĆŁŻŹÓĄĘŃ][\wąęółśżźćń\.]*){0,2})',
    re.UNICODE)

# słowa, które NIE są nazwą ulicy (ucinamy je z końca dopasowania)
_STOP_WORDS = {
    'dzielnica', 'oferta', 'lublin', 'lublinie', 'lublina', 'mieszkanie',
    'mieszkania', 'cena', 'nr', 'obok', 'blisko', 'oraz', 'czyli', 'gmina',
    'okolice', 'najważniejsze', 'sprzedam', 'sprzedaż', 'pokoje', 'pokoi',
    'parter', 'piętro', 'osiedle',
}


def extract_street_candidates(text: str) -> List[str]:
    """Zwraca kandydatów na nazwę ulicy z tekstu (bez duplikatów, w kolejności)."""
    candidates = []
    for m in _STREET_RE.finditer(text or ''):
        name = m.group(1)
        # utnij na granicy zdania/linii i odetnij stop-słowa z końca
        name = re.split(r'[\n,;:|!?()"]', name)[0].strip().rstrip('.')
        words = name.split()
        while words and words[-1].lower().strip('.') in _STOP_WORDS:
            words.pop()
        name = ' '.join(words).rstrip('.')
        if len(name) >= 4 and name not in candidates:
            candidates.append(name)
    return candidates


def nominative_variants(street: str) -> List[str]:
    """Warianty mianownika dla nazwy w dopełniaczu: Wyżynnej→Wyżynna,
    Krężnickiej→Krężnicka, Zorzy→Zorza."""
    variants = [street]
    last = street.split()[-1]
    prefix = street[: len(street) - len(last)]
    if last.endswith('iej') and len(last) > 4:
        variants.append(prefix + last[:-3] + 'a')
    elif last.endswith('ej') and len(last) > 3:
        variants.append(prefix + last[:-2] + 'a')
    elif last.endswith('y') and len(last) > 3:
        variants.append(prefix + last[:-1] + 'a')
    return variants


class StreetGeocoder:
    def __init__(self, cache_file: str = str(CACHE_FILE), delay_s: float = 1.1,
                 max_live: Optional[int] = None, max_reverse: Optional[int] = None):
        self.cache_file = Path(cache_file)
        self.delay_s = delay_s
        self._last_request = 0.0
        self.cache = self._load_cache()
        self.live_requests = 0
        self.reverse_requests = 0
        # budżet zapytań NA ŻYWO do Nominatim (None = bez limitu); wyniki z cache
        # są stosowane zawsze, niezależnie od budżetu — patrz geocode_street
        self.max_live = max_live
        # osobny budżet na reverse geocoding (weryfikacja pinezek Otodom)
        self.max_reverse = max_reverse

    def _load_cache(self) -> Dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {}

    def save_cache(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=1)

    def _query(self, street: str) -> Optional[Dict]:
        """Jedno zapytanie strukturalne do Nominatim (z rate limitem)."""
        wait = self.delay_s - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(NOMINATIM_URL, params={
                'street': street, 'city': 'Lublin', 'country': 'Poland',
                'format': 'json', 'limit': 3,
            }, headers=HEADERS, timeout=15)
            self._last_request = time.time()
            self.live_requests += 1
            r.raise_for_status()
            results = r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"      ⚠️ Nominatim błąd dla '{street}': {e}")
            return None

        for res in results:
            lat, lon = float(res['lat']), float(res['lon'])
            # tylko realne ulice (class=highway) — bez tego śmieciowa nazwa
            # (np. 'Lublinie') dopasowuje samo miasto i pinezka ląduje w centrum
            if res.get('class') != 'highway':
                continue
            if 'Lublin' not in res.get('display_name', ''):
                continue
            if not (LUBLIN_BBOX['lat_min'] <= lat <= LUBLIN_BBOX['lat_max']
                    and LUBLIN_BBOX['lon_min'] <= lon <= LUBLIN_BBOX['lon_max']):
                continue
            return {'lat': lat, 'lon': lon, 'name': res.get('name') or street}
        return None

    def geocode_street(self, street: str) -> Optional[Dict]:
        """Geokoduje ulicę (z wariantami odmiany). Zwraca {'lat','lon','name'} lub None."""
        key = street.lower()
        if key in self.cache:
            entry = self.cache[key]
            if entry.get('result'):
                return entry['result']
            if time.time() - entry.get('ts', 0) < NEGATIVE_TTL_S:
                return None  # świeży negatywny wpis

        # miss w cache → potrzebne zapytanie na żywo; respektuj budżet, ale gdy
        # jest wyczerpany NIE zapisuj negatywu (ponów w kolejnym skanie)
        result = None
        budget_exhausted = False
        for variant in nominative_variants(street):
            if self.max_live is not None and self.live_requests >= self.max_live:
                budget_exhausted = True
                break
            result = self._query(variant)
            if result:
                break
        if result is not None or not budget_exhausted:
            self.cache[key] = {'result': result, 'ts': time.time()}
        return result

    def reverse_address(self, lat: float, lon: float) -> Optional[Dict]:
        """Reverse geocoding: zwraca {'road','district','city'} w danym punkcie.

        Używane do weryfikacji pinezek Otodom — sprawdzamy, na jakiej ulicy i w
        jakiej dzielnicy NAPRAWDĘ stoi pinezka. Wynik (cały adres) cache'owany po
        zaokrąglonych współrzędnych; respektuje osobny budżet `max_reverse`.
        """
        key = f"rva:{lat:.4f},{lon:.4f}"
        if key in self.cache:
            entry = self.cache[key]
            if entry.get('result') is not None:
                return entry['result'] or None
            if time.time() - entry.get('ts', 0) < NEGATIVE_TTL_S:
                return None
        if self.max_reverse is not None and self.reverse_requests >= self.max_reverse:
            return None  # budżet wyczerpany — bez zapisu (ponów w kolejnym skanie)

        wait = self.delay_s - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        result = None
        try:
            r = requests.get(NOMINATIM_REVERSE_URL, params={
                'lat': lat, 'lon': lon, 'format': 'json', 'zoom': 16,
                'addressdetails': 1,
            }, headers=HEADERS, timeout=15)
            self._last_request = time.time()
            self.reverse_requests += 1
            r.raise_for_status()
            addr = (r.json() or {}).get('address') or {}
            result = {
                'road': (addr.get('road') or addr.get('pedestrian')
                         or addr.get('residential') or addr.get('footway')),
                'district': (addr.get('suburb') or addr.get('city_district')
                             or addr.get('quarter') or addr.get('neighbourhood')
                             or addr.get('borough')),
                'city': addr.get('city') or addr.get('town') or addr.get('municipality'),
            }
        except (requests.RequestException, ValueError) as e:
            print(f"      ⚠️ Nominatim reverse błąd ({lat:.4f},{lon:.4f}): {e}")
            return None
        self.cache[key] = {'result': result, 'ts': time.time()}
        return result

    def reverse_road(self, lat: float, lon: float) -> Optional[str]:
        """Sama nazwa ulicy w punkcie (z reverse_address) — do weryfikacji ulicy."""
        addr = self.reverse_address(lat, lon)
        return (addr or {}).get('road')


# ── pomocnicze: porównywanie nazw ulic i dystans ─────────────────────────────

_PREFIX_RE = re.compile(r'^(ul|al|aleja|ulica|os|osiedle|pl|plac)\.?\s+', re.I)


def _norm_street(name: str) -> str:
    """Normalizuje nazwę ulicy do rdzenia: bez prefiksu, bez numerów, małe litery."""
    if not name:
        return ''
    s = _PREFIX_RE.sub('', name.strip().lower())
    s = re.split(r'[\d,/]', s)[0].strip()           # utnij numer budynku itp.
    return s


def street_name_matches(stated: str, road: str) -> bool:
    """Czy nazwa ulicy z ogłoszenia (`stated`) i z reverse geocodingu (`road`)
    oznaczają tę samą ulicę (z tolerancją na polską odmianę i wieloczłonowość)."""
    a, b = _norm_street(stated), _norm_street(road)
    if not a or not b:
        return False
    if a == b:
        return True
    va = {v.lower() for v in nominative_variants(a)}
    vb = {v.lower() for v in nominative_variants(b)}
    if va & vb:
        return True
    # porównaj rdzenie ostatnich słów (np. „Kunickiego" vs „Kunicki")
    def stem(w: str) -> str:
        return re.sub(r'(iego|ego|iej|ej|ą|a|ie|y)$', '', w)
    la, lb = stem(a.split()[-1]), stem(b.split()[-1])
    return len(la) >= 4 and la == lb


def haversine_km(a: Dict, b: Dict) -> float:
    """Odległość w km między dwoma punktami {'lat','lon'}."""
    import math
    lat1, lon1 = math.radians(a['lat']), math.radians(a['lon'])
    lat2, lon2 = math.radians(b['lat']), math.radians(b['lon'])
    x = (lon2 - lon1) * math.cos((lat1 + lat2) / 2)
    return math.hypot(x, lat2 - lat1) * 6371


def street_candidates(offer: Dict) -> List[str]:
    """Kandydaci na ulicę oferty: jawne pole `street` + ekstrakcja z tytułu/opisu."""
    loc = offer.get('location') or {}
    cands = []
    if loc.get('street'):
        cands.append(re.sub(r'^(ul|al)\.\s*', '', loc['street']))
    text = (offer.get('title') or '') + '\n' + (offer.get('description') or '')
    cands.extend(c for c in extract_street_candidates(text) if c not in cands)
    return cands


def _in_lublin(coords: Dict) -> bool:
    return (LUBLIN_BBOX['lat_min'] <= coords['lat'] <= LUBLIN_BBOX['lat_max']
            and LUBLIN_BBOX['lon_min'] <= coords['lon'] <= LUBLIN_BBOX['lon_max'])


def district_matches(stated: str, found: str) -> bool:
    """Czy dzielnica podana w ogłoszeniu i wykryta z reverse geocodingu to ta sama.
    Leniwie (gdy brak którejś danej — nie blokujemy)."""
    a = (stated or '').strip().lower().replace('-', ' ')
    b = (found or '').strip().lower().replace('-', ' ')
    if not a or not b:
        return True
    if a in b or b in a:
        return True
    return bool(set(a.split()) & set(b.split()))


def otodom_coords_plausible(offer: Dict, geocoder: StreetGeocoder) -> bool:
    """Czy współrzędne Otodom są na tyle wiarygodne, by użyć ich na mapie.

    Mechanizm: pinezka musi być w granicach Lublina, a dzielnica wykryta z reverse
    geocodingu pinezki musi zgadzać się z dzielnicą podaną w ogłoszeniu. Dzięki
    temu używamy lokalizacji z Otodom (zamiast ją wyrzucać), ale odrzucamy pinezki
    stojące w złym miejscu. Leniwie: gdy reverse niedostępny (budżet), zostawiamy
    coords (korzystamy z lokalizacji Otodom; weryfikacja dobierze się w kolejnym skanie).
    """
    loc = offer.get('location') or {}
    coords = loc.get('coords')
    if not coords:
        return False
    if not _in_lublin(coords):
        return False  # poza Lublinem — pinezka na pewno błędna
    addr = geocoder.reverse_address(coords['lat'], coords['lon'])
    if addr is None:
        return True  # nie zweryfikowano (budżet/błąd) — używamy lokalizacji Otodom
    city = addr.get('city')
    if city and 'lublin' not in city.lower():
        return False
    if not district_matches(loc.get('district'), addr.get('district')):
        loc['district_mismatch'] = True
        return False  # pinezka w innej dzielnicy niż podana → nie używamy
    loc.pop('district_mismatch', None)
    return True


def verify_otodom_coords(offer: Dict, geocoder: StreetGeocoder,
                         min_dist_km: float = 0.7) -> bool:
    """Weryfikuje „dokładną" pinezkę Otodom względem ulicy z tytułu/treści.

    Jeśli pinezka leży na INNEJ ulicy niż podana w ogłoszeniu (reverse geocoding)
    i jednocześnie jest oddalona o > min_dist_km od zgeokodowanej podanej ulicy,
    przenosimy ją na ulicę z ogłoszenia (precyzja 'street'). Poprawne pinezki na
    długich ulicach zostają nietknięte (reverse zwraca tę samą ulicę).

    Returns: True jeśli współrzędne zostały skorygowane.
    """
    loc = offer.get('location') or {}
    coords = loc.get('coords')
    if not coords or loc.get('coords_precision') != 'exact':
        return False
    cands = street_candidates(offer)
    if not cands:
        return False  # brak adresu w tekście — nie ma czym weryfikować

    road = geocoder.reverse_road(coords['lat'], coords['lon'])
    if road is None:
        return False  # nie udało się ustalić ulicy pinezki — zostaw bez zmian
    if any(street_name_matches(c, road) for c in cands):
        return False  # pinezka stoi na podanej ulicy — OK, nie ruszamy

    # pinezka jest na innej ulicy niż podana → przenieś na podaną (jeśli geokodowalna)
    for c in cands:
        geo = geocoder.geocode_street(c)
        if geo and haversine_km(coords, geo) > min_dist_km:
            loc['coords'] = {'lat': geo['lat'], 'lon': geo['lon']}
            loc['coords_precision'] = 'street'
            loc['street'] = f"ul. {geo['name']}"
            loc['otodom_coord_corrected'] = True
            return True
    return False


def refine_offer_location(offer: Dict, geocoder: StreetGeocoder) -> bool:
    """Próbuje doprecyzować lokalizację oferty (brak/approx → street).

    Returns: True jeśli coords zostały ustawione/poprawione z ulicy.
    """
    loc = offer.setdefault('location', {})
    if loc.get('coords_precision') in ('exact', 'street'):
        return False  # już dobre — nie ruszamy

    # kandydaci: jawne pole street (Otodom) + ekstrakcja z tytułu i opisu
    candidates = []
    if loc.get('street'):
        candidates.append(re.sub(r'^(ul|al)\.\s*', '', loc['street']))
    text = (offer.get('title') or '') + '\n' + (offer.get('description') or '')
    candidates.extend(c for c in extract_street_candidates(text) if c not in candidates)

    for candidate in candidates:
        result = geocoder.geocode_street(candidate)
        if result:
            loc['coords'] = {'lat': result['lat'], 'lon': result['lon']}
            loc['coords_precision'] = 'street'
            loc['street'] = loc.get('street') or f"ul. {result['name']}"
            return True
    return False


if __name__ == "__main__":
    tests = [
        ("Mieszkanie 2 pok. Lublin, ul. Krężnicka", ['Krężnicka']),
        ("Kawalerka przy ul. Wyżynnej w Lublinie", ['Wyżynnej']),
        ("Mieszkanie 37 m² • Lublin, ul. Niepodległości.", ['Niepodległości']),
        ("Mieszkanie przy alei Kraśnickiej, blisko centrum", ['Kraśnickiej']),
        ("Mieszkanie bez ulicy w tekście", []),
    ]
    ok = 0
    for text, expected in tests:
        got = extract_street_candidates(text)
        status = "OK " if got == expected else "FAIL"
        ok += got == expected
        print(f"{status} {text[:50]!r} → {got}")
    print(f"\n{ok}/{len(tests)} OK")
    print("warianty 'Krężnickiej':", nominative_variants('Krężnickiej'))
