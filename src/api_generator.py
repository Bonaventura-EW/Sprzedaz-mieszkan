"""Generator statycznego API: data/offers.json → docs/api/*.json.

Endpointy (GitHub Pages, konwencja z rodziny sonarów):
- api/status.json  — statystyki bieżącego stanu bazy + czas skanów
- api/offers.json  — kompaktowa lista aktywnych ofert (dedup OLX↔Otodom)
- api/history.json — historia skanów (z data/scan_history.json)
- api/health.json  — prosty healthcheck (świeżość ostatniego skanu)
"""

import json
from datetime import datetime
from pathlib import Path

import pytz

import paths
from map_generator import build_map_offer

API_DIR = Path(paths.DOCS_DIR) / "api"
STALE_AFTER_HOURS = 26  # 2 skany/dzień → >26 h bez skanu = problem
HISTORY_SCANS = 6       # api/history.json trzyma 6 ostatnich skanów


def generate():
    tz = pytz.timezone('Europe/Warsaw')
    now = datetime.now(tz)

    with open(paths.OFFERS_JSON, 'r', encoding='utf-8') as f:
        db = json.load(f)

    all_offers = db.get('offers', [])
    active_ids = {o['id'] for o in all_offers if o.get('active')}
    active = [o for o in all_offers
              if o.get('active')
              and not (o.get('duplicate_of') and o['duplicate_of'] in active_ids)]

    per_m2 = sorted(o.get('price_per_m2') for o in active if o.get('price_per_m2'))
    by_source = {}
    by_market = {}
    for o in active:
        by_source[o['source']] = by_source.get(o['source'], 0) + 1
        m = o.get('market') or 'nieokreslony'
        by_market[m] = by_market.get(m, 0) + 1

    API_DIR.mkdir(parents=True, exist_ok=True)

    def write(name, payload):
        with open(API_DIR / name, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    # status ostatniego skanu (czy się udał + bilans ofert)
    last_entry = {}
    history_path_for_status = Path(paths.SCAN_HISTORY_JSON)
    if history_path_for_status.exists():
        with open(history_path_for_status, 'r', encoding='utf-8') as f:
            scans_for_status = json.load(f).get('scans', [])
        if scans_for_status:
            last_entry = scans_for_status[-1]

    write('status.json', {
        'generated_at': now.isoformat(),
        'last_scan': db.get('last_scan'),
        'next_scan': db.get('next_scan'),
        'last_scan_status': last_entry.get('status', 'completed') if last_entry else None,
        'last_scan_success': last_entry.get('status', 'completed') == 'completed' if last_entry else None,
        'last_scan_new_offers': last_entry.get('new'),
        'last_scan_disappeared_offers': last_entry.get('deactivated'),
        'last_scan_duration_s': last_entry.get('duration_s'),
        'active_offers': len(active),
        'total_in_db': len(all_offers),
        'median_price_per_m2': per_m2[len(per_m2) // 2] if per_m2 else None,
        'by_source': by_source,
        'by_market': by_market,
    })

    write('offers.json', {
        'generated_at': now.isoformat(),
        'count': len(active),
        'offers': [build_map_offer(o) for o in active],
    })

    # history.json — 6 ostatnich skanów (nowe nadpisują stare): status + bilans
    history = {}
    history_path = Path(paths.SCAN_HISTORY_JSON)
    if history_path.exists():
        with open(history_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    raw_scans = history.get('scans', [])

    def format_duration(seconds):
        if seconds is None:
            return None
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s" if m else f"{s}s"

    api_scans = []
    for i in range(len(raw_scans) - 1, max(len(raw_scans) - 1 - HISTORY_SCANS, -1), -1):
        scan = raw_scans[i]
        prev = raw_scans[i - 1] if i > 0 else None
        status = scan.get('status', 'completed')
        success = status == 'completed'
        new = scan.get('new', 0)
        disappeared = scan.get('deactivated', 0)
        active_count = scan.get('active')
        delta = None
        if success and prev and prev.get('status', 'completed') == 'completed' \
           and active_count is not None and prev.get('active') is not None:
            delta = active_count - prev['active']

        scan_time = ''
        try:
            scan_time = datetime.fromisoformat(scan['timestamp']).strftime('%H:%M')
        except (KeyError, ValueError):
            pass

        if success:
            title = f"✅ Skan {scan_time} — +{new} nowych / -{disappeared} znikło"
            body = (f"Pojawiło się {new} nowych, zniknęło {disappeared} "
                    f"ofert mieszkań na sprzedaż w Lublinie")
        else:
            title = f"❌ Skan {scan_time} — NIEUDANY"
            body = scan.get('error') or 'Skan zakończony błędem'

        api_scans.append({
            'timestamp': scan.get('timestamp'),
            'scanTimeFormatted': scan_time,
            'uiStatus': 'success' if success else 'failure',
            'rawStatus': status,
            'failureReason': scan.get('error') if not success else None,
            'durationSeconds': scan.get('duration_s'),
            'durationFormatted': format_duration(scan.get('duration_s')),
            'notification': {'title': title, 'body': body},
            'offers': {
                'new': new,
                'disappeared': disappeared,
                'updated': scan.get('updated', 0),
                'active': active_count,
                'activeDelta': delta,
                'totalInDb': scan.get('total_in_db'),
                'bySource': {
                    'olx': scan.get('scraped_olx'),
                    'otodom': scan.get('scraped_otodom'),
                },
            },
        })

    write('history.json', {
        'system': 'sonar-sprzedazy',
        'generated_at': now.isoformat(),
        'count': len(api_scans),
        'scans': api_scans,
    })

    last_scan = db.get('last_scan')
    hours_since = None
    if last_scan:
        hours_since = (now - datetime.fromisoformat(last_scan)).total_seconds() / 3600
    fresh = hours_since is not None and hours_since < STALE_AFTER_HOURS
    last_ok = last_entry.get('status', 'completed') == 'completed' if last_entry else True
    write('health.json', {
        'status': 'ok' if (fresh and last_ok) else 'stale' if not fresh else 'failing',
        'generated_at': now.isoformat(),
        'last_scan': last_scan,
        'last_scan_status': last_entry.get('status') if last_entry else None,
        'hours_since_last_scan': round(hours_since, 1) if hours_since is not None else None,
    })

    print(f"🔌 Wygenerowano API: {API_DIR} (status, offers[{len(active)}], history, health)")


if __name__ == "__main__":
    generate()
