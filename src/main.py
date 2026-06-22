"""SONAR SPRZEDAŻY MIESZKAŃ — główny agent.

Koordynuje: scraping (OLX + Otodom) → normalizacja → aktualizacja bazy →
doprecyzowanie lokalizacji (ulica z tytułu/opisu) → dezaktywacja zniknietych
ofert → zapis. Wzorowany na SONAR-DZIAŁKOWY, dostosowany do mieszkań na
sprzedaż z podziałem na rynek pierwotny/wtórny.

Zasada lokalizacji: pinezka pojawia się TYLKO gdy znamy szczegółowy adres —
dokładny punkt z Otodom (precyzja 'exact') albo ulica wykryta w tytule/opisie
(precyzja 'street'). Przybliżone coords (centroid miasta z OLX, centroid
dzielnicy z Otodom) są usuwane — takie oferty trafiają do sekcji „bez GPS".
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import pytz

import paths
from olx_scraper import OLXMieszkaniaScraper
from otodom_scraper import OtodomMieszkaniaScraper
from location_refiner import (
    StreetGeocoder, refine_offer_location, verify_otodom_coords)

# Ranking precyzji coords — przy deduplikacji zostaje oferta z najlepszą lokalizacją
PRECISION_RANK = {'exact': 3, 'street': 2, 'approx': 1, None: 0}

# Maksymalna wiarygodna zmiana ceny między skanami (ochrona przed błędami parsowania)
MAX_PRICE_CHANGE_PERCENT = 70
# Ochrona przed masową dezaktywacją: scraper źródła musi zwrócić >= 30%
# wcześniejszej liczby aktywnych ofert tego źródła, inaczej pomijamy dezaktywację
MIN_SCRAPE_RATIO = 0.3
# Limit live geokodowań na skan (Nominatim, 1 req/s) — reszta w kolejnych skanach
MAX_LIVE_GEOCODES = 100
# Limit reverse geocodingu na skan (weryfikacja pinezek Otodom) — patrz niżej
MAX_REVERSE_GEOCODES = 100


class SonarSprzedazy:
    def __init__(self, data_file: str = paths.OFFERS_JSON,
                 removed_file: str = paths.REMOVED_JSON):
        self.data_file = Path(data_file)
        self.removed_file = Path(removed_file)
        self.tz = pytz.timezone('Europe/Warsaw')
        self.database = self._load_json(self.data_file) or {
            'last_scan': None, 'next_scan': None, 'offers': []
        }
        removed = self._load_json(self.removed_file) or {}
        self.removed_ids = set(removed.get('removed_ids', []))

    @staticmethod
    def _load_json(path: Path):
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️ Uszkodzony plik {path}, pomijam")
            return None

    def _save_database(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.database, f, ensure_ascii=False, indent=1)
        print(f"💾 Baza zapisana: {self.data_file}")

    def _known_otodom_offers(self) -> Dict:
        """Indeks znanych ofert Otodom — pozwala scraperowi pominąć strony szczegółów."""
        known = {}
        for offer in self.database['offers']:
            if offer.get('source') != 'otodom':
                continue
            loc = offer.get('location') or {}
            known[offer['id']] = {
                'coords': loc.get('coords'),
                'coords_precision': loc.get('coords_precision'),
                'market': offer.get('market'),
                'rooms': offer.get('rooms'),
                'floor': offer.get('floor'),
                'description': offer.get('description'),
                # detale uznajemy za pobrane gdy wcześniej dociągnęliśmy stronę
                # oferty (ślad: znany rynek lub coords)
                '_details_fetched': offer.get('_details_fetched', False),
            }
        return known

    def _find_existing(self, offer_id: str):
        for offer in self.database['offers']:
            if offer['id'] == offer_id:
                return offer
        return None

    def _update_existing(self, existing: Dict, new: Dict):
        now = datetime.now(self.tz).isoformat()
        existing['last_seen'] = now

        # slug/URL mógł się zmienić (sprzedawca edytował tytuł) — odśwież
        existing['url'] = new['url']
        existing['title'] = new['title'] or existing.get('title')

        old_price = existing['price']['current']
        new_price = new['price']
        if new_price and new_price != old_price:
            change_pct = abs(new_price - old_price) / old_price * 100
            if change_pct <= MAX_PRICE_CHANGE_PERCENT:
                trend = 'down' if new_price < old_price else 'up'
                arrow = '📉' if trend == 'down' else '📈'
                print(f"   {arrow} Zmiana ceny {existing['id']}: "
                      f"{old_price} → {new_price} zł")
                existing['price']['previous_price'] = old_price
                existing['price']['current'] = new_price
                existing['price']['price_trend'] = trend
                existing['price']['price_changed_at'] = now
                existing['price']['history'].append(new_price)
                existing['price'].setdefault('price_changes', []).append({
                    'old_price': old_price, 'new_price': new_price,
                    'changed_at': now, 'trend': trend,
                })
            else:
                print(f"   ⚠️ PODEJRZANA zmiana ceny {existing['id']}: "
                      f"{old_price} → {new_price} zł ({change_pct:.0f}%) — ignoruję")

        # uzupełnij/odśwież pola merytoryczne (nowy skan = świeższe dane)
        if new.get('area_m2'):
            existing['area_m2'] = new['area_m2']
        if existing.get('area_m2') and existing['price']['current']:
            existing['price_per_m2'] = round(
                existing['price']['current'] / existing['area_m2'], 2)
        if new.get('market') and new['market'] != 'nieokreslony':
            existing['market'] = new['market']
        if new.get('rooms'):
            existing['rooms'] = new['rooms']
        if new.get('floor'):
            existing['floor'] = new['floor']
        if new.get('description') and len(new['description']) >= len(existing.get('description') or ''):
            existing['description'] = new['description']
        if new.get('image'):
            existing['image'] = new['image']
        if new.get('_details_fetched'):
            existing['_details_fetched'] = True

        # coords: nie nadpisuj dokładnych przybliżonymi
        new_loc = new.get('location') or {}
        old_loc = existing.setdefault('location', {})
        if new_loc.get('coords'):
            if not old_loc.get('coords') or old_loc.get('coords_precision') != 'exact' \
               or new_loc.get('coords_precision') == 'exact':
                old_loc['coords'] = new_loc['coords']
                old_loc['coords_precision'] = new_loc.get('coords_precision')
        for key in ('city', 'district', 'street'):
            if new_loc.get(key):
                old_loc[key] = new_loc[key]

        if not existing.get('active', True):
            existing['active'] = True
            existing['reactivated_at'] = now
            print(f"   🔄 REAKTYWOWANO: {existing['id']}")

    def _add_new(self, new: Dict):
        now = datetime.now(self.tz).isoformat()
        price = new.pop('price')
        new['price'] = {
            'current': price,
            'history': [price],
        }
        new['first_seen'] = now
        new['last_seen'] = now
        new['active'] = True
        new['days_active'] = 0
        self.database['offers'].append(new)

    def _mark_inactive(self, scraped_by_source: Dict[str, List[Dict]]) -> int:
        """Dezaktywuje oferty nieobecne w skanie — per źródło, z ochroną
        przed masową dezaktywacją przy blokadzie portalu.

        Returns: łączna liczba dezaktywowanych ofert (do statystyk API).
        """
        now = datetime.now(self.tz).isoformat()
        total_deactivated = 0
        for source, scraped in scraped_by_source.items():
            scraped_ids = {o['id'] for o in scraped}
            active_in_db = [o for o in self.database['offers']
                            if o.get('source') == source and o.get('active')]

            if not active_in_db:
                continue
            if len(scraped) == 0:
                print(f"   ⚠️ OCHRONA [{source}]: scraper zwrócił 0 ofert, "
                      f"baza ma {len(active_in_db)} aktywnych — pomijam dezaktywację")
                continue
            if len(active_in_db) >= 10 and len(scraped) < len(active_in_db) * MIN_SCRAPE_RATIO:
                print(f"   ⚠️ OCHRONA [{source}]: tylko {len(scraped)} ofert ze skanu "
                      f"vs {len(active_in_db)} aktywnych — pomijam dezaktywację")
                continue

            deactivated = 0
            for offer in active_in_db:
                if offer['id'] not in scraped_ids:
                    offer['active'] = False
                    offer['deactivated_at'] = now
                    deactivated += 1
            total_deactivated += deactivated
            if deactivated:
                print(f"   ⏸️ [{source}] dezaktywowano: {deactivated}")
        return total_deactivated

    def _update_days_active(self):
        for offer in self.database['offers']:
            try:
                first = datetime.fromisoformat(offer['first_seen'])
                last = datetime.fromisoformat(offer['last_seen'])
                offer['days_active'] = (last - first).days
            except (ValueError, KeyError):
                offer['days_active'] = 0

    @staticmethod
    def _distance_km(c1: Dict, c2: Dict) -> float:
        """Przybliżona odległość (równoodległościowa) — wystarcza do dedup."""
        import math
        lat1, lon1 = math.radians(c1['lat']), math.radians(c1['lon'])
        lat2, lon2 = math.radians(c2['lat']), math.radians(c2['lon'])
        x = (lon2 - lon1) * math.cos((lat1 + lat2) / 2)
        return math.hypot(x, lat2 - lat1) * 6371

    def _flag_generic_otodom_coords(self, min_cluster: int = 3, radius_km: float = 0.25):
        """Wykrywa 'fałszywie dokładne' pinezki Otodom stojące w generycznym
        centroidzie (np. plac Zamkowy / centrum dzielnicy).

        Gdy ogłoszeniodawca nie wskaże punktu, Otodom wstawia centroid dzielnicy
        — wiele różnych ofert ląduje w tym samym miejscu. Heurystyka:
        >= min_cluster aktywnych ofert z coords 'exact' w promieniu radius_km →
        wszystkie w klastrze dostają precyzję 'approx' (a refiner spróbuje
        podnieść je do 'street' z ulicy w tytule/opisie; jak nie — coords zostaną
        usunięte). Dzielnica z reverse geokodowania jest czyszczona.
        """
        active = [o for o in self.database['offers']
                  if o.get('active') and o.get('source') == 'otodom'
                  and (o.get('location') or {}).get('coords')]
        flagged = 0
        for offer in active:
            loc = offer['location']
            if loc.get('coords_precision') != 'exact':
                continue
            c = loc['coords']
            neighbours = sum(
                1 for other in active
                if self._distance_km(c, other['location']['coords']) <= radius_km
            )  # liczy też samą ofertę
            if neighbours >= min_cluster:
                loc['coords_precision'] = 'approx'
                loc['generic_centroid'] = True
                loc['district'] = None
                flagged += 1
        if flagged:
            print(f"   🎯 Oznaczono {flagged} pinezek Otodom jako przybliżone "
                  f"(generyczny centroid)")

    def _strip_approx_coords(self) -> int:
        """Usuwa współrzędne 'approx' (centroidy) — pinezka tylko dla znanego adresu.

        Po doprecyzowaniu (refiner) wszystko, co nadal jest 'approx', to centroid
        miasta/dzielnicy — taka pinezka wprowadzałaby w błąd (dziesiątki ofert
        w jednym punkcie). Uczciwiej: bez coords → oferta trafia do sekcji
        „bez lokalizacji GPS" pod mapą.
        """
        stripped = 0
        for offer in self.database['offers']:
            loc = offer.get('location') or {}
            if offer.get('active') and loc.get('coords') \
                    and loc.get('coords_precision') == 'approx':
                loc['coords'] = None
                loc['coords_precision'] = None
                stripped += 1
        if stripped:
            print(f"   📭 {stripped} ofert bez konkretnego adresu → sekcja 'bez GPS'")
        return stripped

    def _tag_cross_portal_duplicates(self):
        """To samo mieszkanie wystawione na OLX i Otodom: identyczna cena,
        powierzchnia ±1% i (gdy oba mają GPS) odległość <2 km.

        Kanoniczna zostaje oferta z najlepszą precyzją coords (exact > street >
        approx), przy remisie Otodom. Duplikaty dostają `duplicate_of`
        (map_generator je chowa), obie strony linkują się przez `also_at`.
        """
        active = [o for o in self.database['offers']
                  if o.get('active') and o.get('area_m2')]

        def rank(o):
            precision = (o.get('location') or {}).get('coords_precision')
            return (PRECISION_RANK.get(precision, 0), o['source'] == 'otodom')

        ordered = sorted(active, key=rank, reverse=True)
        for o in ordered:
            o.pop('duplicate_of', None)  # przelicz od zera przy każdym skanie

        absorbed = set()
        tagged = 0
        for canonical in ordered:
            if canonical['id'] in absorbed:
                continue
            for other in ordered:
                if other['id'] == canonical['id'] or other['id'] in absorbed:
                    continue
                if other['source'] == canonical['source']:
                    continue  # duplikaty w obrębie źródła to inny problem
                if other['price']['current'] != canonical['price']['current']:
                    continue
                if abs(other['area_m2'] - canonical['area_m2']) > \
                   0.01 * max(other['area_m2'], canonical['area_m2']):
                    continue
                ca = (canonical.get('location') or {}).get('coords')
                cb = (other.get('location') or {}).get('coords')
                # gdy oba mają GPS i są >2 km od siebie to inne mieszkanie
                # mimo zgodnej ceny/powierzchni
                if ca and cb and self._distance_km(ca, cb) > 2:
                    continue
                other['duplicate_of'] = canonical['id']
                other['also_at'] = canonical['url']
                canonical['also_at'] = other['url']
                absorbed.add(other['id'])
                tagged += 1
        if tagged:
            print(f"   🔗 Powiązano {tagged} duplikatów OLX↔Otodom "
                  f"— na mapie zostaje oferta z najlepszą lokalizacją")

    def _cleanup_old(self, max_age_days: int = 365):
        cutoff = datetime.now(self.tz) - timedelta(days=max_age_days)
        before = len(self.database['offers'])
        self.database['offers'] = [
            o for o in self.database['offers']
            if datetime.fromisoformat(o['first_seen']) > cutoff
        ]
        removed = before - len(self.database['offers'])
        if removed:
            print(f"🗑️ Usunięto {removed} ofert starszych niż {max_age_days} dni")

    def _next_scan_time(self) -> str:
        now = datetime.now(self.tz)
        for hour in (8, 14, 20):
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > now:
                return candidate.isoformat()
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=8, minute=0, second=0, microsecond=0).isoformat()

    def _log_scan(self, stats: Dict):
        """Dopisuje wpis do data/scan_history.json (ostatnie 200 skanów)."""
        history_path = Path(paths.SCAN_HISTORY_JSON)
        history = self._load_json(history_path) or {'scans': []}
        history['scans'].append(stats)
        history['scans'] = history['scans'][-200:]
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=1)

    def run_scan(self, max_pages: int = 50):
        """Pełny skan z logowaniem statusu — nieudany skan też trafia do
        scan_history (status 'failed'), żeby API pokazywało awarie."""
        start = time.time()
        now = datetime.now(self.tz)
        try:
            self._run_scan(max_pages, start, now)
        except Exception as e:
            print(f"\n❌ Skan nieudany: {e}")
            self._log_scan({
                'timestamp': now.isoformat(),
                'status': 'failed',
                'error': str(e)[:300],
                'duration_s': round(time.time() - start, 1),
            })
            raise

    def _run_scan(self, max_pages: int, start: float, now):
        print("\n" + "=" * 60)
        print("🏠 SONAR SPRZEDAŻY MIESZKAŃ — Scan Started")
        print("=" * 60 + "\n")

        # 1. Scraping obu źródeł RÓWNOLEGLE (różne domeny, własne rate limity).
        # Awaria/blokada jednego źródła nie przerywa drugiego; szczegóły ofert
        # Otodom i tak pobierane są TYLKO dla nowych (known_offers, z limitem).
        scrape_tasks = {
            'olx': lambda: OLXMieszkaniaScraper().scrape(max_pages=max_pages),
            'otodom': lambda: OtodomMieszkaniaScraper().scrape(
                max_pages=max_pages, known_offers=self._known_otodom_offers()),
        }

        scraped_by_source: Dict[str, List[Dict]] = {}
        with ThreadPoolExecutor(max_workers=len(scrape_tasks)) as executor:
            futures = {executor.submit(fn): key for key, fn in scrape_tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    scraped_by_source[key] = future.result()
                except Exception as e:
                    print(f"❌ [{key}]: scraping nieudany: {e}")
                    scraped_by_source[key] = []

        # 2. Aktualizacja bazy
        print("💾 Aktualizacja bazy danych...")
        new_count, updated_count, skipped_removed = 0, 0, 0
        for source, scraped in scraped_by_source.items():
            for offer in scraped:
                if offer['id'] in self.removed_ids:
                    skipped_removed += 1
                    continue
                existing = self._find_existing(offer['id'])
                if existing:
                    self._update_existing(existing, offer)
                    updated_count += 1
                else:
                    price = offer['price']
                    self._add_new(dict(offer))
                    new_count += 1
                    print(f"   🆕 [{source}] {offer['title'][:60]} — {price} zł")

        # 3a. Fałszywie dokładne pinezki Otodom (centroidy dzielnic) → approx
        self._flag_generic_otodom_coords()

        # 3b. Doprecyzowanie lokalizacji: ulica z tytułu/opisu → coords (Nominatim).
        # Cache sprawia, że kolejne skany robią live zapytania tylko dla nowych ulic.
        print("📍 Doprecyzowanie lokalizacji (ulice z tytułów/opisów)...")
        # WAŻNE: limit dotyczy TYLKO nowych zapytań do Nominatim. Wyniki z cache
        # są stosowane do WSZYSTKICH aktywnych ofert (nie przerywamy pętli), więc
        # oferta z ulicą znaną już z cache dostaje pinezkę nawet po wyczerpaniu
        # budżetu live — naprawia przypadek, gdy oferta z ulicą w tytule (np.
        # „ul. Mełgiewska") wypadała za limitem i nigdy nie była zaznaczana.
        geocoder = StreetGeocoder(max_live=MAX_LIVE_GEOCODES,
                                  max_reverse=MAX_REVERSE_GEOCODES)
        refined_count = 0
        for offer in self.database['offers']:
            if not offer.get('active'):
                continue
            if refine_offer_location(offer, geocoder):
                refined_count += 1

        # 3b2. Weryfikacja „dokładnych" pinezek Otodom względem ulicy z ogłoszenia.
        # Otodom bywa nieprecyzyjny — gdy reverse geocoding pokaże, że pinezka stoi
        # na INNEJ ulicy niż podana w tytule/treści (i daleko od niej), przenosimy
        # ją na ulicę z ogłoszenia. Poprawne pinezki (także na długich ulicach)
        # zostają nietknięte. Reverse cache'owany, dobiera się przez kilka skanów.
        corrected_count = 0
        for offer in self.database['offers']:
            if not offer.get('active'):
                continue
            if verify_otodom_coords(offer, geocoder):
                corrected_count += 1

        geocoder.save_cache()
        if geocoder.live_requests >= MAX_LIVE_GEOCODES:
            print(f"   ⚠️ Wyczerpano budżet {MAX_LIVE_GEOCODES} nowych geokodowań — "
                  f"nieznane jeszcze ulice dobiorą się w kolejnych skanach")
        if refined_count:
            print(f"   ✅ Doprecyzowano {refined_count} ofert (ulica → pinezka)")
        if corrected_count:
            print(f"   🛠️ Skorygowano {corrected_count} błędnych pinezek Otodom "
                  f"(przeniesione na ulicę z ogłoszenia)")

        # 3c. Usuń przybliżone coords (centroidy) — pinezka tylko dla znanego adresu
        self._strip_approx_coords()

        # 4. Dezaktywacja + porządki
        deactivated_count = self._mark_inactive(scraped_by_source)
        self._update_days_active()
        self._tag_cross_portal_duplicates()
        self._cleanup_old()

        # 5. Metadane + zapis
        self.database['last_scan'] = now.isoformat()
        self.database['next_scan'] = self._next_scan_time()
        self._save_database()

        # 6. Statystyki
        active = sum(1 for o in self.database['offers'] if o.get('active'))
        with_coords = sum(1 for o in self.database['offers']
                          if o.get('active') and (o.get('location') or {}).get('coords'))
        duration = time.time() - start
        self._log_scan({
            'timestamp': now.isoformat(),
            'status': 'completed',
            'duration_s': round(duration, 1),
            'deactivated': deactivated_count,
            'scraped_olx': len(scraped_by_source.get('olx', [])),
            'scraped_otodom': len(scraped_by_source.get('otodom', [])),
            'new': new_count,
            'updated': updated_count,
            'skipped_removed': skipped_removed,
            'active': active,
            'with_coords': with_coords,
            'total_in_db': len(self.database['offers']),
        })

        print("\n" + "=" * 60)
        print("📊 PODSUMOWANIE SCANU")
        print("=" * 60)
        print(f"✅ Aktywne oferty: {active} (z pinezką: {with_coords})")
        print(f"🆕 Nowe: {new_count} | 🔄 Zaktualizowane: {updated_count}")
        print(f"📦 Łącznie w bazie: {len(self.database['offers'])}")
        print(f"⏱️ Czas: {duration:.1f}s")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    SonarSprzedazy().run_scan()
