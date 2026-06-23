================================================================================
API SONARA SPRZEDAŻY MIESZKAŃ — opis działania
================================================================================

Statyczne API (pliki JSON na GitHub Pages) opisujące stan bazy ofert sprzedaży
mieszkań w Lublinie (OLX + Otodom). Generowane przez `src/api_generator.py`
z `data/offers.json` przy każdym skanie. NIE jest to serwer — to cztery pliki
.json serwowane jako pliki statyczne (cache CDN GitHub Pages, brak rate-limitu).


JAK DZIAŁA (przepływ)
--------------------------------------------------------------------------------
1. `main.py` aktualizuje `data/offers.json` (oferty, historia cen, dezaktywacja,
   deduplikacja OLX↔Otodom) oraz `data/scan_history.json` (log skanów).
2. `api_generator.py` czyta oba pliki i zapisuje 4 endpointy do `docs/api/`.
3. Brane są tylko oferty AKTYWNE i po deduplikacji — ofertę z aktywnym
   `duplicate_of` (ten sam lokal na obu portalach) chowamy, zostaje kanoniczna.
4. Pliki zapisywane są skompaktowane (bez spacji), kodowanie UTF-8.


ENDPOINTY (bazowy URL: <GitHub Pages>/api/)
--------------------------------------------------------------------------------

api/status.json — migawka bieżącego stanu bazy + wynik ostatniego skanu
  generated_at                  czas wygenerowania pliku (ISO, Europe/Warsaw)
  last_scan / next_scan         czas ostatniego i planowanego skanu
  last_scan_status / _success   "completed" itd. + flaga bool czy się udał
  last_scan_new_offers          ile nowych ofert w ostatnim skanie
  last_scan_disappeared_offers  ile zniknęło
  last_scan_duration_s          czas trwania skanu w sekundach
  active_offers                 liczba aktywnych ofert (po deduplikacji)
  total_in_db                   wszystkie rekordy w bazie (z nieaktywnymi)
  median_price_per_m2           mediana ceny za m²
  by_source                     licznik wg źródła {"olx":..,"otodom":..}
  by_market                     licznik wg rynku {pierwotny/wtorny/nieokreslony}

api/offers.json — pełna lista aktywnych ofert (kompaktowa, dla mapy/frontu)
  generated_at, count           czas + liczba ofert
  offers[]                      tablica ofert; każda oferta zawiera m.in.:
     id            stabilne ID z prefiksem źródła (olx:CID3-IDxxxx / otodom:<id>)
     source        "olx" | "otodom"
     url, title, image, description
     price, previous_price, price_trend, price_history[], price_changes[]
     area_m2, price_per_m2, rooms, floor, market
     district, street
     coords        [lat, lon] lub null
     coords_precision  "exact" | "street" | "approx" | null
                       (pinezka na mapie TYLKO dla exact/street — patrz CLAUDE.md)
     is_private_owner, first_seen, last_seen, active, days_active
     also_at       link do tej samej oferty na drugim portalu (deduplikacja)

api/history.json — 6 ostatnich skanów (status + bilans), gotowe do UI/notyfikacji
  system, generated_at, count
  scans[]                       od najnowszego; każdy wpis:
     timestamp, scanTimeFormatted, durationSeconds/Formatted
     uiStatus ("success"/"failure"), rawStatus, failureReason
     notification {title, body}   gotowy tekst powiadomienia (PL)
     offers {new, disappeared, updated, active, activeDelta, totalInDb,
             bySource{olx,otodom}}

api/health.json — prosty healthcheck świeżości danych
  status                        "ok" | "stale" (brak skanu >26 h) | "failing"
  generated_at, last_scan, last_scan_status
  hours_since_last_scan         godzin od ostatniego skanu


UWAGI
--------------------------------------------------------------------------------
- STALE_AFTER_HOURS = 26 h (2 skany/dzień → dłuższa przerwa = problem).
- HISTORY_SCANS = 6 (history.json trzyma 6 ostatnich skanów).
- API jest read-only; brak autoryzacji, brak parametrów query — pełne pliki.
- Regeneracja ręczna:  cd src && python api_generator.py
