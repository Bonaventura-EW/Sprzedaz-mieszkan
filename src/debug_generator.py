"""Generator danych debug: data/offers.json → docs/debug_data.json.

Strona docs/debug.html pokazuje oferty, które scraper pobrał, ale NIE trafiły na
mapę, z podziałem na powód (wzorowane na skipped_debug.html z SONAR-POKOJOWY):

- brak_adresu        — brak ulicy w tytule/treści i brak coords (nie da się umiejscowić)
- geokoder_pusty     — ulica wykryta, ale geokoder/coords jej nie umiejscowił
- zla_dzielnica      — coords Otodom odrzucone (pinezka w innej dzielnicy/poza Lublinem)
- otodom_bez_detali  — oferta Otodom czeka na pobranie strony szczegółów (coords/rynek)
- duplikat           — to samo mieszkanie na drugim portalu (ukryte na mapie)

Strona diagnostyczna — pomaga widzieć, czego parser/geokoder nie ogarnął.
"""

import json
from datetime import datetime
from pathlib import Path

import pytz

import paths
from location_refiner import street_candidates

SAMPLE_LIMIT = 400          # ile próbek na kategorię trzymać w JSON (liczniki są pełne)
DESC_PREVIEW = 300


CATEGORIES = ('brak_adresu', 'geokoder_pusty', 'zla_dzielnica',
              'otodom_bez_detali', 'duplikat')


def _classify(offer: dict, active_ids: set) -> str:
    """Zwraca kategorię oferty NIEobecnej na mapie (lub None gdy jest na mapie)."""
    loc = offer.get('location') or {}
    dup = offer.get('duplicate_of')
    if dup and dup in active_ids:
        return 'duplikat'
    if loc.get('coords'):
        return None  # ma pinezkę — jest na mapie
    if loc.get('district_mismatch'):
        return 'zla_dzielnica'
    if offer.get('source') == 'otodom' and not offer.get('_details_fetched'):
        return 'otodom_bez_detali'
    if street_candidates(offer):
        return 'geokoder_pusty'
    return 'brak_adresu'


def _sample(offer: dict, category: str) -> dict:
    loc = offer.get('location') or {}
    price = (offer.get('price') or {}).get('current')
    cands = street_candidates(offer)
    return {
        'category': category,
        'title': offer.get('title'),
        'url': offer.get('url'),
        'source': offer.get('source'),
        'market': offer.get('market'),
        'price': price,
        'area_m2': offer.get('area_m2'),
        'rooms': offer.get('rooms'),
        'district': loc.get('district'),
        'street': loc.get('street'),
        'address_parsed': cands[0] if cands else None,
        'description_preview': (offer.get('description') or '')[:DESC_PREVIEW],
        'also_at': offer.get('also_at'),
    }


def generate():
    with open(paths.OFFERS_JSON, 'r', encoding='utf-8') as f:
        db = json.load(f)
    offers = db.get('offers', [])
    active_ids = {o['id'] for o in offers if o.get('active')}

    counts = {c: 0 for c in CATEGORIES}
    samples = {c: [] for c in CATEGORIES}
    for o in offers:
        if not o.get('active'):
            continue
        cat = _classify(o, active_ids)
        if not cat:
            continue
        counts[cat] += 1
        if len(samples[cat]) < SAMPLE_LIMIT:
            samples[cat].append(_sample(o, cat))

    tz = pytz.timezone('Europe/Warsaw')
    data = {
        'scan_timestamp': db.get('last_scan') or datetime.now(tz).isoformat(),
        'generated_at': datetime.now(tz).isoformat(),
        'counts': counts,
        'total': sum(counts.values()),
        'samples': samples,
    }

    out = Path(paths.DOCS_DIR) / "debug_data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print(f"🐛 Wygenerowano {out} — "
          + ', '.join(f"{c}={counts[c]}" for c in CATEGORIES))


if __name__ == "__main__":
    generate()
