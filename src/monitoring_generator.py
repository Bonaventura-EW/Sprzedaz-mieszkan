"""Generator danych monitoringu: data/scan_history.json → docs/monitoring_data.json.

Dashboard (docs/monitoring.html) pokazuje przebieg skanów: czasy, liczbę ofert
z OLX/Otodom, nowe/zaktualizowane oferty i stan bazy. Format dopasowany do
scan_history SONARA SPRZEDAŻY MIESZKAŃ (płaskie wpisy z main.py::_log_scan).
"""

import json
from pathlib import Path

import paths

OUTPUT_JSON = str(Path(paths.DOCS_DIR) / "monitoring_data.json")


def generate():
    history_path = Path(paths.SCAN_HISTORY_JSON)
    scans = []
    if history_path.exists():
        with open(history_path, 'r', encoding='utf-8') as f:
            scans = json.load(f).get('scans', [])

    # chronologicznie (w pliku już są od najstarszego, ale nie polegamy na tym)
    scans = sorted(scans, key=lambda s: s.get('timestamp', ''))
    recent = scans[-60:]  # ostatnie 30 dni przy 2 skanach/dzień

    durations = [s['duration_s'] for s in recent if s.get('duration_s')]
    charts = {
        'duration_over_time': [
            {'timestamp': s.get('timestamp'), 'duration': s.get('duration_s', 0)}
            for s in recent
        ],
        'offers_over_time': [
            {'timestamp': s.get('timestamp'),
             'olx': s.get('scraped_olx', 0),
             'otodom': s.get('scraped_otodom', 0),
             'new': s.get('new', 0),
             'updated': s.get('updated', 0)}
            for s in recent
        ],
        'db_over_time': [
            {'timestamp': s.get('timestamp'),
             'active': s.get('active', 0),
             'total': s.get('total_in_db', 0)}
            for s in recent
        ],
    }

    last = recent[-1] if recent else {}
    data = {
        'generated_at': last.get('timestamp'),
        'statistics': {
            'total_scans': len(scans),
            'avg_duration_s': round(sum(durations) / len(durations), 1) if durations else None,
            'last_scan': last.get('timestamp'),
            'last_duration_s': last.get('duration_s'),
            'last_new': last.get('new', 0),
            'last_active': last.get('active', 0),
            'last_olx': last.get('scraped_olx', 0),
            'last_otodom': last.get('scraped_otodom', 0),
        },
        'recent_scans': list(reversed(recent))[:30],  # najnowsze pierwsze (tabela)
        'charts': charts,
    }

    out = Path(OUTPUT_JSON)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print(f"📊 Wygenerowano {out} ({len(recent)} skanów)")


if __name__ == "__main__":
    generate()
