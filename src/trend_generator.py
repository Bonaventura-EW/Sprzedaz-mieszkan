"""Generator szeregów czasowych trendu: data/offers.json → docs/api/trend.json.

Odtwarza dzienną historię liczby AKTYWNYCH ofert oraz ODPŁYWU (ofert
zarchiwizowanych danego dnia) w rozbiciu na kategorie (rynek / źródło / pokoje).
Zamiast „profili wyszukiwania" (jak w bliźniaczym SZPERACZ) używamy kategorii
naturalnych dla tego sonaru.

Rekonstrukcja z pól oferty:
- obecna danego dnia D, gdy first_seen.date() <= D <= end.date(),
  gdzie end = deactivated_at (jeśli nieaktywna) albo dziś (jeśli aktywna),
  albo last_seen (nieaktywna bez daty dezaktywacji),
- odpływ danego dnia D = liczba ofert z deactivated_at.date() == D.

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
  "promoted": { key: [...] }  # sparse: liczba płatnie wyróżnionych ofert (OLX) danego dnia
}

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


def build_trend(db, today=None):
    tz = pytz.timezone('Europe/Warsaw')
    today = today or datetime.now(tz).date()

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
            end = today
            deact = None
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
                'promoted': {}}

    # Oś czasu: dzień po dniu od pierwszej archiwizacji do dziś.
    days = []
    d = global_start
    while d <= today:
        days.append(d)
        d += timedelta(days=1)
    day_index = {d: i for i, d in enumerate(days)}
    n_days = len(days)

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
            si = day_index.get(start, 0)
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
        profiles[key] = [{'date': days[i].isoformat(), 'count': active_daily[i]}
                         for i in range(n_days)]
        outflow[key] = _sparse(outflow_map)
        inflow[key] = _sparse(inflow_map)
        reactivations[key] = _sparse(react_map)
        promoted[key] = _sparse(promoted_map)

    return {
        'generated': datetime.now(tz).isoformat(),
        'labels': labels,
        'profiles': profiles,
        'outflow': outflow,
        'inflow': inflow,
        'reactivations': reactivations,
        'promoted': promoted,
    }


def generate():
    with open(paths.OFFERS_JSON, 'r', encoding='utf-8') as f:
        db = json.load(f)
    payload = build_trend(db)
    API_DIR.mkdir(parents=True, exist_ok=True)
    with open(API_DIR / 'trend.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    n_days = len(next(iter(payload['profiles'].values()), []))
    print(f"📈 Wygenerowano trend: {API_DIR / 'trend.json'} "
          f"({len(payload['profiles'])} kategorii × {n_days} dni)")


if __name__ == "__main__":
    generate()
