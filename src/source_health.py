"""Wykrywanie „martwego źródła" — alert, gdy scraper danego portalu przestaje
zwracać oferty, mimo że skan kończy się poprawnie.

Kontekst (FIX 2026-08-22): health.json sprawdzał tylko świeżość i status
ostatniego skanu. Gdy OLX zaczął oddawać 0 ofert (blokada WAF), skan nadal
kończył się `completed`, więc żaden alert się nie pojawił, a oferty OLX żyły
dalej dzięki ochronie przed masową dezaktywacją. Ten moduł liczy alert per
źródło i jest współdzielony przez api_generator (health.json) i
monitoring_generator (baner na dashboardzie).
"""

from typing import Dict, List, Optional

# źródła, dla których scan_history trzyma pole `scraped_<source>`
SOURCES = ('olx', 'otodom')


def compute_source_alerts(scans: List[Dict],
                          active_by_source: Optional[Dict[str, int]] = None,
                          window: int = 10) -> List[Dict]:
    """Zwraca listę alertów o źródłach, które w ostatnim skanie oddały 0 ofert,
    mimo że wcześniej działały (albo wciąż trzymają aktywne oferty w bazie).

    scans: wpisy scan_history w kolejności chronologicznej (najstarszy → najnowszy).
    active_by_source: liczba aktywnych ofert per źródło w bazie (opcjonalnie).
    """
    if not scans:
        return []
    active_by_source = active_by_source or {}
    recent = scans[-window:]
    alerts = []
    for source in SOURCES:
        key = f'scraped_{source}'
        vals = [s.get(key) for s in recent if s.get(key) is not None]
        if not vals:
            continue  # źródło nie występuje w historii — nie alarmujemy
        last = vals[-1] or 0
        recent_max = max((s.get(key) or 0) for s in recent)
        active_cnt = active_by_source.get(source, 0)
        # ile skanów z rzędu (licząc od końca CAŁEJ historii) oddało 0
        consecutive_zero = 0
        for s in reversed(scans):
            if s.get(key) is None:
                continue
            if (s.get(key) or 0) == 0:
                consecutive_zero += 1
            else:
                break
        # alert: ostatni skan 0, a źródło ma historię ofert lub wciąż aktywne
        # oferty w bazie (czyli powinno coś zwracać)
        if last == 0 and (recent_max > 0 or active_cnt > 0):
            alerts.append({
                'source': source,
                'last_scraped': last,
                'consecutive_zero_scans': consecutive_zero,
                'recent_max_scraped': recent_max,
                'active_in_db': active_cnt,
            })
    return alerts
