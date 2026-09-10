"""Generator szeregów czasowych trendu: data/offers.json → docs/api/trend.json.

Odtwarza dzienną historię liczby AKTYWNYCH ofert oraz ODPŁYWU (ofert
zarchiwizowanych danego dnia) w rozbiciu na kategorie (rynek / źródło / pokoje).
Zamiast „profili wyszukiwania" (jak w bliźniaczym SZPERACZ) używamy kategorii
naturalnych dla tego sonaru.

Rekonstrukcja z pól oferty:
- obecna danego dnia D, gdy first_seen.date() <= D <= end.date(),
  gdzie end = deactivated_at (jeśli nieaktywna) albo ostatni PEŁNY dzień
  (jeśli aktywna), albo last_seen (nieaktywna bez daty dezaktywacji),
- odpływ danego dnia D = liczba ofert z deactivated_at.date() == D.

Maska pokrycia skanami (FIX 2026-09-10, propagacja z SONAR-MIESZKANIOWY,
manifest 2026-09-04-trend-charts-audit → issue #14):
- seria kończy się na ostatnim PEŁNYM dniu (wszystkie zaplanowane przebiegi
  `scanner.yml` zakończone), a nie na „dziś" — inaczej trwająca doba (albo dzień
  bez skanu) rysowała się jak zamknięta i dawała fałszywy zjazd na prawej
  krawędzi wykresu (bug #1);
- dni z niepełną liczbą skanów (`scan_history.json`) są POMIJANE w serii Indeksu —
  skan widzi tylko wycinek listingu, więc rekonstrukcja takiego dnia jest zaniżona
  i udawała „rekord odpływu" (bug #2). Nasz wariant CANVAS nie rysuje przerwy
  (jak ApexCharts u brata) — po prostu nie emitujemy punktu, więc linia przechodzi
  nad brakującym dniem zamiast nurkować.
- FIX 2026-09-10: ta sama maska obowiązuje na wykresach PRZEPŁYWU (odpływ, napływ,
  reaktywacje, wyróżnienia) — tam jednak NIE wolno usuwać dnia z serii, bo szeregi
  sparse są zerowo-wypełniane przez front (`expandDaily`), więc brak dnia czytałby
  się jako „0 odpływu", czyli ten sam fałszywy dołek, tylko głębszy. Dlatego
  wartości zostają w API (surowy pomiar), a maskę podajemy OSOBNO w `coverage`
  i `trend.html` rysuje te dni jako lukę: bez punktu, bez wkładu do średniej 7 dni
  i bez prawa do rekordu. Skok NASTĘPNEGO dnia (nadrobione potwierdzenia) to już
  bug #3/#4 — opóźnienie `DEACTIVATE_GRACE_DAYS`, świadomie nieruszane.
Odpływ liczony z opóźnieniem `DEACTIVATE_GRACE_DAYS` (bug #3/#4 manifestu) NIE jest
tu ruszany — naprawa wymaga zmiany definicji końca odcinka życia (last_seen zamiast
deactivated_at), co pokrywa się z otwartym issue #11; celowo nie mieszamy.

Duplikaty OLX↔Otodom (`duplicate_of`) są pomijane, by nie liczyć podwójnie
(jak mapa i api_generator chowają duplikaty).

Format wyjścia (kontrakt dla docs/trend.html):
{
  "generated": ISO,
  "labels":   { key: {"label": str, "is_category": bool} },
  "profiles": { key: [{"date": "YYYY-MM-DD", "count": int}, ...] },  # ciągła seria dzienna
  "outflow":  { key: [{"date": "YYYY-MM-DD", "count": int}, ...] },  # sparse: dni z odpływem
  "inflow":   { key: [...] },  # sparse: napływ dnia = nowe + reaktywacje
  "reactivations": { key: [...] },  # sparse: reaktywacje danego dnia
  "promoted": { key: [...] },  # sparse: liczba płatnie wyróżnionych ofert (OLX) danego dnia
  "measured": { "wszystkie": [...] },  # sparse: ZMIERZONA dzienna liczba aktywnych po dedup
  "coverage": {                        # maska pokrycia doby przebiegami skanera
    "scans_per_day": int,
    "last_complete": "YYYY-MM-DD" | null,
    "incomplete": ["YYYY-MM-DD", ...],       # dni bez pełnego pomiaru
    "reasons": {"YYYY-MM-DD": "niepelny_skan" | "brak_zrodla"}
  }
}

Zmierzona seria „measured" (propagacja z SONAR-POKOJOWY, issue #11):
- Rekonstrukcja liczby aktywnych ofert wstecz z pól first_seen/last_seen zawyża
  środek osi i zaniża prawy koniec (oferta z przerwą w życiu jest liczona jako
  ciągle obecna; korpus jest przycinany wstecz), przez co widoczny kierunek
  trendu na prawym końcu — tam, gdzie ludzie patrzą — bywa odwrócony.
- Zamiast tego zapisujemy przy KAŻDYM skanie zmierzony stan bazy
  (`active_dedup` w data/scan_history.json, main._run_scan) i podajemy go jako
  osobną, nakładaną serię odniesienia. Wartość dnia to MAKSIMUM z odczytów
  (przebieg częściowy nie obniża historii), dzień bez skanu to LUKA, nie zero.
- Zgodnie z wzorcem brata NIE mieszamy metod w jednej linii: „measured" jest
  DEDUPLIKOWANA (jak `profiles['wszystkie']`) i zaczyna się tam, gdzie zaczyna
  się pomiar (od wdrożenia `active_dedup`) — dedupu nie da się odtworzyć wstecz,
  bo zależy od pełnego korpusu z danej chwili.
- Maska pokrycia doby (wyżej) tej serii NIE dotyczy: pomiar jest MIGAWKĄ stanu
  bazy, nie agregatem doby, więc dzień odsiany z Indeksu jako niepełny może mieć
  tu poprawny punkt. Oba szeregi czyta jedno wczytanie dziennika
  (`load_scan_history`), przekazywane do `build_trend(..., scan_history=)`.

Płatne wyróżnienia OLX (propagacja z SONAR-POKOJOWY):
- wyróżnienie danego dnia D = liczba ofert z datą == D w `promoted_dates`
  (scraper czyta flagę z parametru `search_reason` w URL-u OLX, main._track_promoted
  dopisuje max 1 wpis/dzień). To metryka STANU (ile ofert jest wyróżnionych danego
  dnia), tylko dla OLX — Otodom nie ma takiej atrybucji, więc kategoria „Otodom"
  ma tu pustą serię. Historia liczy się dopiero od wdrożenia detekcji: wyróżnienia
  to stan chwilowy listingu, nie da się ich odtworzyć wstecz.

Napływ i reaktywacje (FIX 2026-08-22, wzór SONAR-POKOJOWY):
- reaktywacja danego dnia D = liczba wpisów w `reactivation_dates` (fallback:
  skalarne `reactivated_at`) z datą == D,
- napływ danego dnia D = nowe (first_seen == D) + reaktywacje tego dnia.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytz

import paths

API_DIR = Path(paths.DOCS_DIR) / "api"

# Ile skanów planujemy na dobę. scanner.yml: cron '17 6,16 * * *' (UTC) =
# 8:17 i 18:17 czasu PL. Dzień, w którym zakończyło się MNIEJ przebiegów,
# widział tylko wycinek listingu — rekonstrukcja jest z niego zaniżona.
SCANS_PER_DAY = 2

# Definicje kategorii: (klucz, etykieta, is_category, predykat na ofercie)
CATEGORIES = [
    ('wszystkie', 'Wszystkie oferty', True, lambda o: True),
    ('rynek_pierwotny', 'Rynek pierwotny', False, lambda o: o.get('market') == 'pierwotny'),
    ('rynek_wtorny', 'Rynek wtórny', False, lambda o: o.get('market') == 'wtorny'),
    ('zrodlo_olx', 'OLX', False, lambda o: o.get('source') == 'olx'),
    ('zrodlo_otodom', 'Otodom', False, lambda o: o.get('source') == 'otodom'),
    ('pokoje_1', '1 pokój', False, lambda o: o.get('rooms') == 1),
    ('pokoje_2', '2 pokoje', False, lambda o: o.get('rooms') == 2),
    ('pokoje_3', '3 pokoje', False, lambda o: o.get('rooms') == 3),
    ('pokoje_4plus', '4+ pokoi', False, lambda o: isinstance(o.get('rooms'), int) and o.get('rooms') >= 4),
]


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


def load_scan_history():
    """Lista skanów z data/scan_history.json (albo [] przy braku/uszkodzeniu pliku).

    JEDNO wczytanie dziennika dla obu rzeczy, które z niego czerpią: maski
    pokrycia doby (`_scan_counts` → `_scan_coverage`, issue #14) i zmierzonej
    serii aktywnych (`_measured_daily`, issue #11). Awaria pliku nie może
    wywalić generatora — trend działa dalej, tylko bez maski i bez pomiaru.
    """
    try:
        with open(paths.SCAN_HISTORY_JSON, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(history, dict):
        history = history.get('scans', [])
    return history or []


def _scan_counts(scan_history):
    """{date: liczba ZAKOŃCZONYCH skanów danego dnia} z dziennika skanów.

    Źródło prawdy o pokryciu doby przebiegami — na nim stoi maska dni niepełnych
    (patrz `_scan_coverage`). Historia trzyma ostatnie ~200 skanów; o dniach
    spoza tego okna nie wie nic i tam zakładamy pełne pokrycie.
    """
    counts = {}
    for scan in scan_history or []:
        if scan.get('status') not in ('completed', 'warning'):
            continue
        d = _parse_date(scan.get('timestamp'))
        if d:
            counts[d] = counts.get(d, 0) + 1
    return counts


def _source_outage_days(scan_history):
    """Dni, w których KTÓREŚ ŹRÓDŁO nie oddało listingu ANI RAZU (blokada portalu)
    — czyli dni, w których przepływu tego źródła po prostu nie dało się zmierzyć.

    Sygnał z dziennika skanów: `scraped_<źródło>` oraz `incomplete_sources` (ślad
    częściowego listingu). Liczy się NAJLEPSZY przebieg doby: jeden nieudany scrape
    obok udanych niczego nie psuje (`last_seen` odświeży ten udany, a ochrona
    z main._mark_inactive i tak nie pozwoli wtedy dezaktywować). Dopiero doba, w
    której źródła nie zobaczyliśmy w ogóle, jest dziurą w pomiarze.

    Bez tego blokada portalu daje najgorszy możliwy artefakt: przez cały czas
    blokady ochrona (słusznie) wstrzymuje dezaktywację, a przy powrocie źródła
    cała zaległość ląduje w JEDNYM dniu jako gigantyczny „rekord odpływu"
    (u nas 10 dni bez OLX, 12–21.08, i 231 ofert jednego dnia po powrocie).
    Sama zmiana atrybucji na `last_seen` tu nie wystarcza — przesuwa tylko skok
    na pierwszy dzień blokady, gdzie równie mocno kłamie.
    """
    seen_ok = {}          # (dzień, źródło) -> czy któryś przebieg dał pełny listing
    days_with_data = set()
    for scan in scan_history or []:
        day = _parse_date(scan.get('timestamp'))
        if day is None:
            continue
        partial = set(scan.get('incomplete_sources') or ())
        for key, value in scan.items():
            if not key.startswith('scraped_'):
                continue
            source = key[len('scraped_'):]
            ok = bool(value) and source not in partial
            seen_ok[(day, source)] = seen_ok.get((day, source), False) or ok
            days_with_data.add(day)
    sources = {source for _, source in seen_ok}
    return {day for day in days_with_data
            if any(not seen_ok.get((day, source), False) for source in sources)}


def _scan_coverage(scan_history, today):
    """(dni_niepełne, ostatni_pełny_dzień) wg dziennika skanów.

    Dzień jest PEŁNY, gdy zakończyły się w nim wszystkie zaplanowane przebiegi
    (`SCANS_PER_DAY`) I każde źródło oddało listing. Niepełny — zero skanów
    (awaria Actions), jeden z dwóch (doba jeszcze trwa) albo źródło zwracające
    pustkę (blokada portalu, patrz `_source_outage_days`) — pokazuje wycinek
    listingu i wypada z serii Indeksu, zamiast udawać załamanie rynku.

    Pierwszy dzień dziennika pomijamy (historia bywa ucięta w połowie doby),
    a dni SPRZED dziennika zakładamy pełne — inaczej cała stara historia
    wyparowałaby jako „niepełna". Gdy w oknie nie ma ani jednego pełnego dnia
    (np. dziennik akurat pusty), zostawiamy zakres do „dziś" — awaria dziennika
    nie może skasować całego wykresu.
    """
    scan_counts = _scan_counts(scan_history)
    if not scan_counts:
        return set(), today
    outages = _source_outage_days(scan_history)
    logged = sorted(scan_counts)
    coverage_start = logged[0] + timedelta(days=1)
    incomplete = set()
    d = coverage_start
    while d <= today:
        if scan_counts.get(d, 0) < SCANS_PER_DAY or d in outages:
            incomplete.add(d)
        d += timedelta(days=1)
    last_complete = None
    d = today
    while d >= coverage_start:
        if d not in incomplete:
            last_complete = d
            break
        d -= timedelta(days=1)
    return incomplete, last_complete or today


def _measured_daily(scan_history):
    """Zmierzona dzienna liczba aktywnych ofert po dedup z dziennika skanów.

    Wartość dnia = maksimum z odczytów `active_dedup` tego dnia (przebieg
    częściowy nie obniża historii); dzień bez pomiaru zostaje LUKĄ (nie zero).
    Zwraca sparse listę [{'date', 'count'}] posortowaną rosnąco. Skany sprzed
    wdrożenia `active_dedup` nie mają tego pola i są pomijane — seria zaczyna się
    tam, gdzie zaczyna się pomiar.

    Uwaga: pomiar to MIGAWKA stanu bazy, więc — inaczej niż rekonstrukcja — nie
    psuje go niepełna doba. Dlatego maska pokrycia (`_scan_coverage`) tej serii
    NIE dotyczy; dzień odsiany z Indeksu może mieć tu poprawny punkt.
    """
    if not scan_history:
        return []
    by_day = {}
    for scan in scan_history:
        val = scan.get('active_dedup')
        if val is None:
            continue
        day = _parse_date(scan.get('timestamp'))
        if day is None:
            continue
        by_day[day] = max(by_day.get(day, val), val)
    return [{'date': d.isoformat(), 'count': c} for d, c in sorted(by_day.items())]


def build_trend(db, today=None, scan_history=None):
    tz = pytz.timezone('Europe/Warsaw')
    today = today or datetime.now(tz).date()

    # FIX 2026-09-10: maska pokrycia skanami (propagacja z SONAR-MIESZKANIOWY,
    # issue #14). Seria kończy się na ostatnim PEŁNYM dniu, a dni z niepełną
    # liczbą przebiegów wypadają z Indeksu. Bez `scan_history` (testy jednostkowe)
    # zachowujemy stare zachowanie: pełne pokrycie, seria do „dziś".
    incomplete, end_day = _scan_coverage(scan_history, today)
    outages = _source_outage_days(scan_history)   # do rozróżnienia powodu luki

    # Pomijamy duplikaty (kanoniczna zostaje) — jak mapa/api chowają duplikaty.
    offers = [o for o in db.get('offers', []) if not o.get('duplicate_of')]

    # Dla każdej oferty: dzień pojawienia i dzień zniknięcia (końca obecności).
    spans = []  # (start_date, end_date, deact_date|None, react_dates, offer)
    global_start = None
    for o in offers:
        start = _parse_date(o.get('first_seen')) or _parse_date(o.get('created_at'))
        if not start:
            continue
        deact = _parse_date(o.get('deactivated_at'))
        if o.get('active'):
            # aktywne ciągną się tylko do ostatniego PEŁNEGO dnia — dalej brak
            # zamkniętej doby, więc dzień bieżący nie jest zaniżany (bug #1)
            end = end_day
            deact = None
        elif _parse_date(o.get('last_seen')):
            # FIX 2026-09-10 (bug #4 z issue #14): odcinek życia kończy się w dniu,
            # w którym ofertę OSTATNI RAZ WIDZIELIŚMY, a odpływ przypada nazajutrz
            # (pierwszy dzień bez niej). `deactivated_at` to dzień POTWIERDZENIA —
            # opóźniony o DEACTIVATE_GRACE_DAYS, a przy blokadzie portalu nawet
            # o tygodnie, bo ochrona przed masową dezaktywacją wstrzymuje kasowanie.
            # Trzymanie się potwierdzenia zlepiało zaległość w jeden fałszywy skok.
            end = _parse_date(o.get('last_seen'))
            deact = end + timedelta(days=1)
        elif deact:
            end = deact
        else:
            end = _parse_date(o.get('last_seen')) or start
        if end < start:
            end = start
        # daty reaktywacji: pełna lista, a gdy jej brak — skalarny fallback
        raw_react = o.get('reactivation_dates')
        if raw_react is None:
            raw_react = [o['reactivated_at']] if o.get('reactivated_at') else []
        react_dates = [d for d in (_parse_date(x) for x in raw_react) if d]
        spans.append((start, end, deact, react_dates, o))
        if global_start is None or start < global_start:
            global_start = start

    if global_start is None:
        return {'generated': datetime.now(tz).isoformat(), 'labels': {},
                'profiles': {}, 'outflow': {}, 'inflow': {}, 'reactivations': {},
                'promoted': {}, 'measured': {},
                'coverage': {'scans_per_day': SCANS_PER_DAY, 'last_complete': None,
                             'incomplete': [], 'reasons': {}}}

    # Oś czasu: dzień po dniu od pierwszej archiwizacji do ostatniego PEŁNEGO
    # dnia (trwająca doba / dzień bez skanu nie wchodzi — bug #1).
    days = []
    d = global_start
    while d <= end_day:
        days.append(d)
        d += timedelta(days=1)
    day_index = {d: i for i, d in enumerate(days)}
    n_days = len(days)

    if not days:
        return {'generated': datetime.now(tz).isoformat(), 'labels': {},
                'profiles': {}, 'outflow': {}, 'inflow': {}, 'reactivations': {},
                'promoted': {}, 'measured': {},
                'coverage': {'scans_per_day': SCANS_PER_DAY, 'last_complete': None,
                             'incomplete': [], 'reasons': {}}}

    labels = {}
    profiles = {}
    outflow = {}
    inflow = {}
    reactivations = {}
    promoted = {}

    def _sparse(m):
        return [{'date': dd.isoformat(), 'count': c} for dd, c in sorted(m.items())]

    for key, label, is_category, pred in CATEGORIES:
        active_daily = [0] * n_days   # liczba obecnych danego dnia
        outflow_map = {}              # date -> liczba zarchiwizowanych tego dnia
        new_map = {}                  # date -> nowe oferty (first_seen)
        react_map = {}                # date -> reaktywacje
        promoted_map = {}             # date -> liczba ofert wyróżnionych tego dnia
        for start, end, deact, react_dates, o in spans:
            if not pred(o):
                continue
            si = day_index.get(start)
            if si is None:
                # oferta pojawiła się dopiero w dniach uciętych (po end_day) —
                # nie liczymy jej, dopóki nie trafi na dzień z pełnym pokryciem;
                # jej deact/reakt./promo też są poza osią, więc pomijamy całość
                continue
            ei = day_index.get(end, n_days - 1)
            for i in range(si, ei + 1):
                active_daily[i] += 1
            if deact and deact in day_index:
                outflow_map[deact] = outflow_map.get(deact, 0) + 1
            # pierwszy dzień osi = „zasianie" bazy (cały korpus dostał wtedy
            # first_seen) — to artefakt startu skanera, nie realny napływ; pomijamy
            if start in day_index and start != days[0]:
                new_map[start] = new_map.get(start, 0) + 1
            for rd in react_dates:
                if rd in day_index:
                    react_map[rd] = react_map.get(rd, 0) + 1
            # płatne wyróżnienia OLX: dzień, w którym oferta była promowana
            # (main._track_promoted, max 1 wpis/dzień). Historia zaczyna się od
            # wdrożenia detekcji — wyróżnień nie da się odtworzyć wstecz.
            for pd in (o.get('promoted_dates') or []):
                pdd = _parse_date(pd)
                if pdd and pdd in day_index:
                    promoted_map[pdd] = promoted_map.get(pdd, 0) + 1

        # napływ = nowe + reaktywacje (dzień po dniu)
        inflow_map = dict(new_map)
        for dd, c in react_map.items():
            inflow_map[dd] = inflow_map.get(dd, 0) + c

        labels[key] = {'label': label, 'is_category': is_category}
        # Dni o niepełnym pokryciu skanami POMIJAMY (bug #2): rekonstrukcja z nich
        # jest zaniżona. Wariant CANVAS interpoluje linię nad brakującym dniem
        # (brat na ApexCharts rysuje w tym miejscu jawną przerwę przez `null`).
        profiles[key] = [{'date': days[i].isoformat(), 'count': active_daily[i]}
                         for i in range(n_days) if days[i] not in incomplete]
        outflow[key] = _sparse(outflow_map)
        inflow[key] = _sparse(inflow_map)
        reactivations[key] = _sparse(react_map)
        promoted[key] = _sparse(promoted_map)

    # Zmierzona seria (nie rekonstruowana) — tylko dla „wszystkie": scan_history
    # trzyma zdeduplikowany łączny stan bazy, bez rozbicia na kategorie.
    measured = {}
    measured_series = _measured_daily(scan_history)
    if measured_series:
        measured['wszystkie'] = measured_series

    return {
        'generated': datetime.now(tz).isoformat(),
        'labels': labels,
        'profiles': profiles,
        'outflow': outflow,
        'inflow': inflow,
        'reactivations': reactivations,
        'promoted': promoted,
        'measured': measured,
        # FIX 2026-09-10: maska pokrycia doby jawnie w payloadzie — wykresy
        # przepływu zachowują surowe wartości, ale front rysuje te dni jako lukę
        # (bez punktu, bez wkładu do średniej, bez prawa do rekordu).
        'coverage': {
            'scans_per_day': SCANS_PER_DAY,
            'last_complete': end_day.isoformat(),
            'incomplete': [d.isoformat() for d in sorted(incomplete)],
            # powód luki — front tłumaczy ją użytkownikowi, a to dwie różne
            # historie: „nie domknęliśmy doby" vs „portal nas zablokował"
            'reasons': {d.isoformat(): ('brak_zrodla' if d in outages else 'niepelny_skan')
                        for d in sorted(incomplete)},
        },
    }


def generate():
    with open(paths.OFFERS_JSON, 'r', encoding='utf-8') as f:
        db = json.load(f)
    payload = build_trend(db, scan_history=load_scan_history())
    API_DIR.mkdir(parents=True, exist_ok=True)
    with open(API_DIR / 'trend.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    n_days = len(next(iter(payload['profiles'].values()), []))
    print(f"📈 Wygenerowano trend: {API_DIR / 'trend.json'} "
          f"({len(payload['profiles'])} kategorii × {n_days} dni)")


if __name__ == "__main__":
    generate()
