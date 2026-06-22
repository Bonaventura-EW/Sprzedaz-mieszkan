# CLAUDE.md

Wytyczne dla Claude Code (i innych agentów) pracujących w tym repozytorium.
Czytaj na starcie każdej sesji.

## Czym jest projekt

**SONAR SPRZEDAŻY MIESZKAŃ** — agent monitorujący oferty **sprzedaży mieszkań w Lublinie**
(OLX + Otodom), z mapą na GitHub Pages i podziałem na **rynek pierwotny / wtórny**.
Kolejny z rodziny sonarów; architektura wzorowana na `SONAR-DZIAŁKOWY`
i `SONAR-MIESZKANIOWY`.

Najważniejsza zasada produktu: **pinezka na mapie pojawia się TYLKO wtedy, gdy
znamy szczegółowy adres oferty** — czyli:
- dokładny punkt wskazany przez ogłoszeniodawcę na Otodom (`coords_precision == 'exact'`),
- albo ulica wykryta w tytule/treści ogłoszenia i zgeokodowana (`'street'`).

Oferty bez konkretnego adresu trafiają do listy „bez lokalizacji GPS" pod mapą,
a nie na generyczny centroid (to byłaby dezinformacja).

## Przepływ danych

```
olx_scraper.py     → listing OLX → __PRERENDERED_STATE__ → znormalizowane oferty
                     (rynek/pokoje/piętro z params; coords CELOWO puste — patrz niżej)
otodom_scraper.py  → listing Otodom (__NEXT_DATA__) + strony szczegółów TYLKO
                     dla nowych ofert i z LIMITEM na skan (coords, rynek, opis)
  ↓
main.py            → aktualizacja data/offers.json (historia cen, dezaktywacja,
                     reaktywacja, deduplikacja OLX↔Otodom, scan_history)
location_refiner.py→ ulica z tytułu/opisu → Nominatim → precyzja street
                     (cache: data/geocoding_cache.json, limit 100 zapytań/skan)
  ↓ (main: usuwa coords 'approx' = centroidy — pinezka tylko dla znanego adresu)
map_generator.py   → docs/data.json       (mapa: oferty po dedup + kwantyle ceny/m²)
api_generator.py   → docs/api/*.json      (status / offers / history / health)
monitoring_generator.py → docs/monitoring_data.json (dashboard skanów)
debug_generator.py → docs/debug_data.json (oferty bez pinezki wg powodu → docs/debug.html)
  ↓
docs/index.html + assets/script.js → mapa Leaflet (GitHub Pages)
```

## Workflowy GitHub Actions

| Plik | Co robi |
|------|---------|
| `scanner.yml` | skan 2×/dzień (8:17, 18:17 PL) + `workflow_dispatch`; commituje `data/` i `docs/` na `main`, od razu deployuje Pages (OIDC) |
| `pages.yml` | deploy `docs/` na GitHub Pages po pushu na `main` dotykającym `docs/**` (dla pushów ręcznych) |
| `tests.yml` | pytest na push/PR dotykającym `src/`, `tests/` |

> 🏷️ **„Uruchom scan" = odpal workflow `scanner.yml` na `main`**
> (`workflow_dispatch`), NIE lokalne `python main.py`.

> ⚠️ **GitHub Pages trzeba raz włączyć ręcznie** (Settings → Pages →
> Source: **GitHub Actions**) — domyślny token Actions nie może utworzyć
> site'u Pages przy pierwszym uruchomieniu.

## Jak uruchomić

> ⚠️ Skrypty uruchamiaj z katalogu `src/` (importy między modułami zakładają
> `src/` na sys.path; ścieżki danych są kotwiczone w `paths.py` do `__file__`).

```bash
pip install -r requirements.txt
cd src
python main.py             # pełny skan
python map_generator.py    # docs/data.json
python api_generator.py    # docs/api/*.json
python monitoring_generator.py
cd ../docs && python -m http.server 8000
```

Testy: `pytest` z roota repo (konfiguracja w `pytest.ini`, `pythonpath = src`).

## Pułapki i konwencje (WAŻNE)

1. **Stabilne ID z prefiksem źródła**: `olx:CID3-IDxxxx` (slug OLX zmienia się
   przy edycji tytułu — patrz `cid.py`) oraz `otodom:<numeric_id>`.
2. **Dekodowanie OLX**: `__PRERENDERED_STATE__` to escapowany string JS;
   po `unicode_escape` trzeba naprawić polskie znaki re-enkodowaniem
   latin-1 → utf-8 (`decode_prerendered_state` w `olx_scraper.py`).
3. **OLX dla mieszkań NIE daje sensownych coords** — w listingu wszystkie oferty
   mają ten sam centroid miasta (radius 3–6 km). Dlatego OLX-owi celowo NIE
   ustawiamy współrzędnych (`coords = None`); lokalizację bierze wyłącznie
   `location_refiner` z ulicy w tytule/opisie. Nie „naprawiaj" tego ustawiając
   centroid jako pinezkę.
4. **Rynek pierwotny/wtórny**:
   - OLX: param `market` (`primary`→`pierwotny`, `secondary`→`wtorny`) prosto z listingu,
   - Otodom: `estate == 'INVESTMENT'` → pierwotny już z listingu; dla zwykłych
     mieszkań (`FLAT`) rynek znamy dopiero ze strony szczegółów (`ad.market`),
     do tego czasu `market == 'nieokreslony'` (dobierze się przy pobraniu detali).
5. **Otodom: szczegóły tylko dla nowych ofert i z LIMITEM na skan**
   (`detail_limit`, domyślnie 120). Mieszkań są tysiące — pobieranie wszystkich
   detali na raz ściągnęłoby blokadę. Listing pobieramy w całości (potrzebny do
   poprawnej dezaktywacji), detale dobierają się przez kilka skanów. Nie psuj
   tej optymalizacji.
5a. **Okno paginacji Otodom (~1800–1850 z ~3100) — to NIE jest błąd scrapera.**
   Otodom przez listing oddaje tylko ograniczone okno wyników (obserwowane
   ~1837 ofert, mimo `totalItems` ~3100). Dlatego `scraped_otodom` w monitoringu
   jest sporo mniejsze niż liczba aktywnych ofert — resztę utrzymuje na mapie
   karencja dezaktywacji (`DEACTIVATE_GRACE_DAYS`) i ochrona z pkt 8.
   KONSEKWENCJA: oferty spoza okna nie dobiorą szczegółów, dopóki nie wrócą do
   listingu, więc `otodom_bez_detali` w Debugu ma strukturalny floor (~40–60) —
   kolejne skany go nie wyzerują. Nie „naprawiaj" tego wymuszaniem pełnej
   paginacji ani agresywną dezaktywacją ofert spoza okna (to psuje ochronę z pkt 8).
6. **Hierarchia precyzji coords**: `exact` (Otodom, punkt wskazany) > `street`
   (zgeokodowana ulica z tekstu) > `approx` (przybliżona geolokalizacja Otodom).
   `_flag_generic_otodom_coords` degraduje fałszywie dokładne klastry (≥3 oferty
   w 250 m) do `approx`. Współrzędne `approx` z Otodom NIE są ślepo usuwane —
   walidujemy je względem dzielnicy (`otodom_coords_plausible`, krok 3c w
   `main.py`): pinezka musi być w granicach Lublina i w dzielnicy zgodnej z
   ogłoszeniem (reverse geocoding). Zgodne zostają na mapie (kwadrat), niezgodne
   / poza Lublinem → usuwane (sekcja „bez GPS"). OLX nadal bez coords (centroid
   miasta). `_strip_approx_coords` (metoda) pozostaje pomocniczo/testowo.
6a. **Weryfikacja pinezek Otodom** (`verify_otodom_coords`): Otodom bywa
   nieprecyzyjny. Dla `exact` robimy reverse geocoding i jeśli pinezka stoi na
   innej ulicy niż podana w tytule/treści (i > 0,7 km od niej), przenosimy ją na
   ulicę z ogłoszenia (`street`, znacznik `otodom_coord_corrected`). Reverse
   poprawnie zostawia pinezki na długich ulicach. Osobny budżet `MAX_REVERSE_GEOCODES`.
7. **OLX dokleja wyniki „z okolicy"** na końcu listingu — filtrujemy po
   `cityNormalizedName == 'lublin'`.
8. **Ochrona przed masową dezaktywacją** (`main.py::_mark_inactive`): działa
   PER ŹRÓDŁO — jeśli scraper źródła zwróci 0 ofert albo <30% liczby aktywnych,
   dezaktywacja tego źródła jest pomijana (blokada portalu ≠ zniknięcie ofert).
   Nie usuwaj tej ochrony.
9. **Deduplikacja OLX↔Otodom** (`main.py::_tag_cross_portal_duplicates`): ta sama
   cena + powierzchnia ±1% + (gdy oba mają GPS) dystans <2 km → duplikat dostaje
   `duplicate_of`, obie strony `also_at`. Kanoniczna zostaje oferta z najlepszą
   precyzją coords; przy remisie Otodom. `map_generator`/`api_generator` **chowają**
   oferty z aktywnym `duplicate_of`.
10. **Nie modyfikuj ręcznie `data/offers.json`** — plik generowany przez skan.
11. **KAŻDĄ zmianę zapisuj w `CHANGELOG.md`** (sekcja `## [Niewydane]`) — bez
    wyjątków, nawet drobne poprawki, dokumentację czy operacje (np. seria skanów).
    W kodzie dodatkowo oznaczaj zmianę datowanym komentarzem
    `# FIX YYYY-MM-DD: opis`. To twardy wymóg: nie kończ zadania bez wpisu w
    CHANGELOG.

## Konwencja commitów

Format `typ(zakres): opis` po polsku (`fix(scanner):`, `feat(map):`).
Skany automatyczne commitują jako `🤖 Automatyczny scan: <data>`.
