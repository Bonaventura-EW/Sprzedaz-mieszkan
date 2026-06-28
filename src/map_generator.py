"""Generator danych mapy: data/offers.json → docs/data.json.

Frontend (docs/index.html + assets/script2.js) czyta docs/data.json
serwowany przez GitHub Pages.
"""

import json
from datetime import datetime
from pathlib import Path

import pytz

import paths

DESCRIPTION_LIMIT = 1200  # frontend pokazuje skrót, pełny opis jest pod linkiem


def build_map_offer(offer: dict) -> dict:
    """Kompaktowa wersja oferty dla frontendu."""
    loc = offer.get('location') or {}
    price = offer.get('price') or {}
    description = (offer.get('description') or '')[:DESCRIPTION_LIMIT]
    return {
        'id': offer['id'],
        'source': offer.get('source'),
        'url': offer.get('url'),
        'title': offer.get('title'),
        'price': price.get('current'),
        'previous_price': price.get('previous_price'),
        'price_trend': price.get('price_trend'),
        'price_history': price.get('history', []),
        'price_changes': price.get('price_changes', []),
        'price_changed_at': price.get('price_changed_at'),
        'area_m2': offer.get('area_m2'),
        'price_per_m2': offer.get('price_per_m2'),
        'market': offer.get('market') or 'nieokreslony',
        'rooms': offer.get('rooms'),
        'floor': offer.get('floor'),
        'district': loc.get('district'),
        'street': loc.get('street'),
        'coords': loc.get('coords'),
        'coords_precision': loc.get('coords_precision'),
        'description': description,
        'is_private_owner': offer.get('is_private_owner'),
        'image': offer.get('image'),
        'first_seen': offer.get('first_seen'),
        'last_seen': offer.get('last_seen'),
        'active': offer.get('active', False),
        'days_active': offer.get('days_active', 0),
        'also_at': offer.get('also_at'),
        # FIX 2026-06-28: data dezaktywacji — zasila wykres „trwale znikniętych"
        # ofert na statystyki.html (zniknięcia grupowane per dzień/miesiąc).
        'deactivated_at': offer.get('deactivated_at'),
    }


def generate():
    with open(paths.OFFERS_JSON, 'r', encoding='utf-8') as f:
        db = json.load(f)

    all_offers = db.get('offers', [])
    # Deduplikacja OLX↔Otodom: ukrywamy ofertę-duplikat gdy jej kanoniczny
    # odpowiednik jest aktywny — na mapie zostaje jedna pinezka z oboma linkami
    active_ids = {o['id'] for o in all_offers if o.get('active')}
    deduped = [o for o in all_offers
               if not (o.get('duplicate_of') and o['duplicate_of'] in active_ids)]
    hidden = len(all_offers) - len(deduped)
    if hidden:
        print(f"🔗 Ukryto {hidden} duplikatów (to samo mieszkanie na obu portalach)")

    offers = [build_map_offer(o) for o in deduped]
    active = [o for o in offers if o['active']]
    per_m2_values = sorted(o['price_per_m2'] for o in active if o['price_per_m2'])

    def percentile(values, p):
        if not values:
            return None
        idx = min(len(values) - 1, int(round(p * (len(values) - 1))))
        return values[idx]

    tz = pytz.timezone('Europe/Warsaw')
    data = {
        'generated_at': datetime.now(tz).isoformat(),
        'last_scan': db.get('last_scan'),
        'next_scan': db.get('next_scan'),
        'stats': {
            'total': len(offers),
            'active': len(active),
            'active_with_coords': sum(1 for o in active if o['coords']),
            'median_price_per_m2': percentile(per_m2_values, 0.5),
            # progi do kolorowania pinezek wg ceny za m² — 9 decyli = 10 stopni
            # (zielony→fioletowy); QUANTILE_COLORS w script2.js musi mieć 10 kolorów
            'per_m2_quantiles': [percentile(per_m2_values, q)
                                 for q in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)],
        },
        'offers': offers,
    }

    out = Path(paths.DOCS_DATA_JSON)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    print(f"🗺️ Wygenerowano {out} ({len(active)} aktywnych / {len(offers)} łącznie)")


if __name__ == "__main__":
    generate()
