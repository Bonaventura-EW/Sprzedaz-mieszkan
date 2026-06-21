# CHANGELOG

## [0.1.0] — 2026-06-21

Pierwsza wersja **SONARA SPRZEDAŻY** — monitoring ofert sprzedaży mieszkań
w Lublinie (OLX + Otodom) z mapą na GitHub Pages. Architektura wzorowana na
`SONAR-DZIAŁKOWY`, dostosowana do mieszkań i podziału na rynek pierwotny/wtórny.

### Dodane

- **Scrapery** `olx_scraper.py` i `otodom_scraper.py` — mieszkania na sprzedaż
  w Lublinie z portali OLX (`__PRERENDERED_STATE__`) i Otodom (`__NEXT_DATA__`).
  Wyciągają cenę, powierzchnię, cenę/m², **rynek (pierwotny/wtórny)**, liczbę
  pokoi, piętro, opis i zdjęcie.
- **Podział na rynek pierwotny / wtórny**:
  - OLX: param `market` (`primary`→`pierwotny`, `secondary`→`wtorny`) z listingu;
  - Otodom: `estate == INVESTMENT` → pierwotny z listingu, a dla zwykłych
    mieszkań rynek (`ad.market`) ze strony szczegółów.
- **Zasada „pinezka tylko dla znanego adresu"** (`location_refiner.py` +
  `main.py`): OLX dla mieszkań podaje wyłącznie centroid miasta, więc jego
  współrzędne celowo pomijamy; lokalizację bierzemy z ulicy w tytule/treści
  (geokodowanie Nominatim, precyzja `street`) albo z dokładnego punktu Otodom
  (`exact`). Wszystkie współrzędne przybliżone (`approx`, centroidy) są usuwane —
  takie oferty trafiają do sekcji „bez lokalizacji GPS" pod mapą.
- **Limit pobierania szczegółów Otodom na skan** (`detail_limit`, domyślnie 120)
  — mieszkań są tysiące, więc detale (coords + rynek) dobierają się przez kilka
  skanów, a listing pobierany jest w całości (poprawna dezaktywacja).
- **Mapa Leaflet** (`docs/index.html` + `assets/script.js`): pinezki (dokładny
  adres) i kwadraty (ulica), kolorowanie wg ceny/m² (decyle) lub rynku, filtry
  źródła / rynku / liczby pokoi / ceny / powierzchni / czasu / od właściciela,
  badge nowości i zmian ceny, sekcja ofert bez GPS, fokus oferty z linku
  `#offer=<id>`.
- **Podstrony**: 📈 Analityka (histogram ceny/m², scatter cena↔powierzchnia,
  rozkład rynku i liczby pokoi, mediana wg dzielnicy, nowe oferty dziennie),
  📊 Monitoring (przebieg skanów), 📋 Oferty (cena w czasie — tabela + split),
  🔄 Ruch (nowe vs zniknięte z paskiem bilansu).
- **Logika bazy** (`main.py`): historia cen z ochroną przed skokami (>70%),
  dezaktywacja/reaktywacja, ochrona przed masową dezaktywacją per źródło,
  deduplikacja OLX↔Otodom (ta sama cena + powierzchnia ±1% + dystans <2 km),
  flagowanie generycznych centroidów Otodom.
- **Statyczne API** (`api_generator.py`): `status` / `offers` / `history` /
  `health` w `docs/api/`.
- **Workflowy**: `scanner.yml` (skan 2×/dzień + deploy Pages), `pages.yml`,
  `tests.yml`.
- **Testy** (`pytest`): normalizacja OLX/Otodom (rynek, pokoje, piętro),
  ekstrakcja ulic i doprecyzowanie lokalizacji, deduplikacja, usuwanie
  centroidów, flagowanie klastrów, ochrona przed dezaktywacją.
