# API — SONAR SPRZEDAŻY MIESZKAŃ

Statyczne API serwowane przez GitHub Pages, regenerowane przy każdym skanie
(2×/dzień) przez `src/api_generator.py`.

Baza URL: `https://bonaventura-ew.github.io/Sprzedaz-mieszkan/api/`

## Endpointy

### `GET api/status.json`

Statystyki bieżącego stanu bazy.

```json
{
  "generated_at": "2026-06-21T20:07:04+02:00",
  "last_scan": "2026-06-21T20:06:18+02:00",
  "next_scan": "2026-06-22T08:00:00+02:00",
  "last_scan_status": "completed",
  "last_scan_success": true,
  "last_scan_new_offers": 18,
  "last_scan_disappeared_offers": 4,
  "last_scan_duration_s": 96.3,
  "active_offers": 291,
  "total_in_db": 328,
  "median_price_per_m2": 10470,
  "by_source": {"olx": 111, "otodom": 180},
  "by_market": {"wtorny": 123, "pierwotny": 28, "nieokreslony": 140}
}
```

Uwaga: `by_source` liczy oferty **po deduplikacji** — mieszkanie wystawione na
obu portalach liczone jest raz (zostaje wpis o najlepszej lokalizacji).
`nieokreslony` w `by_market` to oferty Otodom, dla których rynek dobierze się
przy pobraniu strony szczegółów w kolejnych skanach.

### `GET api/offers.json`

Wszystkie aktywne oferty po deduplikacji OLX↔Otodom. Każda oferta zawiera m.in.:
`id`, `source`, `url`, `title`, `price`, `area_m2`, `price_per_m2`, `market`
(`pierwotny`/`wtorny`/`nieokreslony`), `rooms`, `floor`, `district`, `street`,
`coords`, `coords_precision` (`exact`/`street`), `is_private_owner`, `image`,
`first_seen`, `last_seen`, `active`, `days_active`, `also_at`.

### `GET api/history.json`

Historia ostatnich skanów (status, czas, bilans nowe/zniknięte, podział na źródła).

### `GET api/health.json`

Prosty healthcheck — `status` (`ok`/`stale`/`failing`) i liczba godzin od
ostatniego skanu (próg nieświeżości: 26 h).
