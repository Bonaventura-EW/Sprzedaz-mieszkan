# CHANGELOG

## [Niewydane]

### Zmienione — 🗺️ jedna mapa (canvas) zamiast dwóch wariantów
Wariant CANVAS sprawdził się w praktyce, więc został jedyną mapą projektu —
stary wariant Leaflet (markery DOM) usunięty. Mniej kodu do utrzymania,
spójna nawigacja.
- **`docs/index.html`** — ładuje teraz `assets/script2.js` (canvas) zamiast
  `assets/script.js`; z nawigacji usunięto link „🗺️ Mapa 2".
- **Usunięto `docs/mapa2.html`** i **`docs/assets/script.js`** (stary Leaflet).
  `script2.js` ma pełny parytet, w tym deep-link `index.html#offer=<id>`
  używany przez podstrony „📐 Statystyki" i „🔄 Ruch".
- **`docs/{analytics,statystyki,monitoring,oferty,zmiany,debug}.html`** —
  z nawigacji usunięto link „🗺️ Mapa 2" (link „🗺️ Mapa" → `index.html`
  bez zmian).
- **`docs/assets/script2.js`** — nagłówkowy komentarz zaktualizowany (już nie
  odwołuje się do usuniętego `script.js`; opis „jedyna mapa projektu").
- **`src/map_generator.py`**, **`CLAUDE.md`** — odwołania `script.js` →
  `script2.js`; opis przepływu danych odzwierciedla jeden wariant mapy.

### Naprawione — 👻 rekordy-widma z kart „podbicia" Otodom (pushed-up)
Otodom w listingu zwracał DODATKOWĄ kartę „podbicia" (pushed-up) dla tej samej
oferty: syntetyczne id `"9"+<realne_id>+"00067"`, placeholderowa data
`1999-02-29 00:00:01` i puste `images`. `normalize_item` brał ją za osobne
ogłoszenie → powstawały rekordy-widma (duplikaty realnych ofert), które
podwajały pinezki na mapie i zawyżały statystyki (deduplikacja w `main.py` jest
tylko cross-portal OLX↔Otodom, więc otodom↔otodom ich nie łapie).
- **`otodom_scraper.py`** — `normalize_item` odrzuca item, gdy
  `createdAtFirst`/`dateCreated` == `PLACEHOLDER_CREATED` (`1999-02-29 00:00:01`).
  Druga linia obrony: `_scrape_listing` deduplikuje teraz także po `slug`
  (slug zawiera `-IDxxxx`, jednoznacznie identyfikuje ofertę) — odporne na
  ew. zmianę schematu syntetycznego id.
- **`tests/test_normalizers.py`** — test regresyjny
  `test_otodom_skips_pushed_up_phantom_card`.
- **`data/offers.json`** — jednorazowy cleanup: usunięto 304 rekordy-widma
  (3239 → 2935). Naprawiono 2 osierocone `duplicate_of` (OLX wskazujące na
  usunięte widmo) — przepięte na realnego bliźniaka Otodom (ten sam URL).
- **`docs/*`** — przegenerowane `data.json`, `api/*`, `debug_data.json`,
  `monitoring_data.json` ze sprzątniętych danych.

### Dokumentacja — opis optymalizacji
- **`OPTYMALIZACJA-MAPA2.txt`** — dokument opisujący optymalizację mapy
  (problem, diagnoza, rozwiązanie canvas, co zachowane 1:1, kompromisy,
  jak sprawdzić, dalsze kroki).

### Dodane — 🗺️ Mapa 2 (wariant canvas, wysoka wydajność)
Nowa zakładka **Mapa 2** (`docs/mapa2.html` + `docs/assets/script2.js`) obok
mapy głównej — ten sam zestaw ofert i filtrów, ale pinezki rysowane na JEDNYM
`<canvas>` zamiast jako ~2300 markerów DOM (`L.divIcon`). Efekt: płynny pan/zoom
przy tysiącach ofert, **bez klastrowania**.
- **Kształty zachowane 1:1** — krople (dokładny adres) i kwadraty z przerywaną
  ramką (lokalizacja przybliżona) rysowane własnymi klasami `PinMarker`/
  `SquareMarker` (rozszerzają `L.CircleMarker`, nadpisują `_updatePath`,
  `_updateBounds`, `_containsPoint`). Badge nowości (N), zmiany ceny (↓/↑) i ×
  dla nieaktywnych rysowane na canvasie.
- **Dlaczego laguje stara mapa**: `L.marker`+`L.divIcon` tworzy węzeł DOM na
  pinezkę; `preferCanvas` ich nie przyspiesza (działa tylko na warstwy
  wektorowe). Przy pan/zoom przeglądarka przesuwa ~2300 węzłów, a każda zmiana
  filtra przebudowuje cały DOM.
- **Dodatkowa optymalizacja**: stan filtrów czytany RAZ na render
  (`buildFilterContext`) zamiast ~15 `getElementById` na każdą z ~2300 ofert.
- Mapa główna (`index.html` + `script.js`) **bez zmian** — zostaje jako
  fallback. Link „Mapa 2" dodany do nawigacji wszystkich podstron.

### Dokumentacja
- **`CLAUDE.md` pkt 11: KAŻDĄ zmianę zapisujemy w CHANGELOG** (sekcja
  `[Niewydane]`) — bez wyjątków, jako twardy wymóg zakończenia zadania.

### Nasycanie mapy — seria skanów (2026-06-22)
Po wpięciu silnika pinezek puszczona seria ~11 skanów `workflow_dispatch`
(`scanner.yml`), aż liczba pinezek przestała rosnąć. Efekt na żywych danych:
- **pinezki na mapie (po dedup): 1715 → 2299** (+584, +34%), rozkład
  `street` 1996 · `exact` 64 · `approx` 239,
- **`otodom_bez_detali` (Debug): 401 → 43** (−90%) — backfill detali Otodom
  (120/skan) prawie wyczerpany,
- największy przyrost w końcówce dał `approx` (37 → 239), czyli geolokalizacja
  Otodom walidowana dzielnicą — mechanizm z `otodom_coords_plausible` działa.

Obserwacje strukturalne (udokumentowane też w `CLAUDE.md` pkt 5a) — to floor,
nie błąd, kolejne skany go nie ruszą:
- **Okno paginacji Otodom**: listing oddaje ~1837 ofert mimo `totalItems` ~3100,
  więc `otodom_bez_detali` ma strukturalny floor (~40–60) i `scraped_otodom`
  jest mniejsze niż liczba aktywnych (resztę trzyma karencja dezaktywacji).
- **OLX bywa chwilowo blokowany** (jeden skan oddał 0 ofert) — ochrona przed
  masową dezaktywacją per źródło zadziałała (`deactivated: 0`), pinezki nie
  zniknęły. Pozostałe kategorie Debug to trwały floor: `brak_adresu` ~70–77
  (brak ulicy w treści), `geokoder_pusty` 17 (Nominatim nie zna ulicy),
  `duplikat` ~700 (ukryte celowo).

### Ulepszony silnik pinezek (na podstawie zakładki Debug)
Analiza kategorii `geokoder_pusty` / `brak_adresu` ujawniła konkretne wzorce —
naprawione w `location_refiner.py`:
- **Prefiks „ul"/„al" case-insensitive** — łapiemy też „Al. Racławickie", „Ul. …"
  (wcześniej tylko małe litery).
- **Obcinanie numeru budynku** z nazwy ulicy: „Wrońska1B"→„Wrońska",
  „Nałęczowska 18a"→„Nałęczowska" (też dla pola `street` z Otodom) — wcześniej
  Nominatim nie znajdował ulicy z numerem.
- **Cięcie na granicy zdania** — kropka po pełnym słowie kończy nazwę:
  „Fantastyczna. Zielone"→„Fantastyczna" (skróty/inicjały typu „Gen."/„K." zostają).
- **Wiele wariantów odmiany** — próbujemy wszystkich form mianownika:
  „Pawiej"→„Pawia", „Wschodniej"→„Wschodnia", „Nadbystrzyckiej"→„Nadbystrzycka".
- Pomiar na próbce Debug: ~16/21 ofert z `geokoder_pusty` zyskuje pinezkę.

### Dodane
- **Zakładka 🐛 Debug** (`docs/debug.html` + `src/debug_generator.py` →
  `docs/debug_data.json`) zamiast sekcji „oferty bez lokalizacji GPS" na mapie.
  Pokazuje oferty, które scraper pobrał, ale nie trafiły na mapę, z podziałem na
  powód (wzór: skipped_debug.html z SONAR-POKOJOWY): **brak adresu**,
  **geokoder pusty** (ulica wykryta, brak coords), **zła dzielnica** (coords
  Otodom odrzucone), **Otodom bez detali** (czeka na stronę szczegółów),
  **duplikat**. Karty liczników, filtr kategorii i wyszukiwarka. Sekcja „bez GPS"
  usunięta z mapy (`index.html`/`script.js`) — odciąża też mapę.

### Naprawione (dezaktywacja)
- **Aktywne oferty Otodom znikały z mapy jako „nieaktywne"**. Dwie przyczyny:
  (1) scrape listingu Otodom urywał się na pierwszej pustej/nieudanej stronie
  (~1800 z 3200 ofert), więc oferty z dalszych stron wypadały ze skanu; teraz
  pobieramy CAŁY listing (przerwa dopiero po 3 pustych stronach z rzędu, z
  ponowieniem). (2) Brak oferty w POJEDYNCZYM skanie powodował natychmiastową
  dezaktywację — dodana **karencja**: dezaktywujemy dopiero, gdy oferty nie widać
  od `DEACTIVATE_GRACE_DAYS` (2 dni). Próg ochrony przed masową dezaktywacją
  podniesiony 0.3 → 0.5.

### Wykorzystanie geolokalizacji Otodom
- **Walidacja współrzędnych Otodom względem dzielnicy** (`otodom_coords_plausible`,
  krok 3c). Otodom podaje geolokalizację — teraz JEJ UŻYWAMY na mapie (zamiast
  wyrzucać przybliżone coords), ale reverse geocodingiem sprawdzamy, czy pinezka
  jest w granicach Lublina i w dzielnicy zgodnej z ogłoszeniem. Zgodne pinezki
  `approx` zostają (kwadrat na mapie), niezgodne / poza miastem → „bez GPS".
  Etykiety warstw/legendy i popup zaktualizowane.

### Naprawione (lokalizacja)
- **Ulica „ul" bez kropki nie była wykrywana** (np. „ul Lipińskiego" w tytule).
  Regex wymagał kropki po „ul"/„al"; teraz kropka jest opcjonalna
  (`\bul\b\.?\s*`), a `\bul\b` chroni przed łapaniem „ul" wewnątrz słów typu
  „ulica". Łapie też „ul.Lwowska" bez spacji. Odblokowuje sporo ofert OLX/Otodom.
- **Weryfikacja „dokładnych" pinezek Otodom** (`location_refiner.verify_otodom_coords`,
  wpięte w `main.py`). Otodom bywa nieprecyzyjny — pinezka potrafi stać kilka km
  od ulicy podanej w tytule/treści. Teraz dla pinezek `exact` z Otodom robimy
  **reverse geocoding** (na jakiej ulicy NAPRAWDĘ stoi punkt) i porównujemy z
  ulicą z ogłoszenia; jeśli to inna ulica i pinezka jest > 0,7 km od podanej —
  przenosimy ją na ulicę z ogłoszenia (precyzja `street`, znacznik
  `otodom_coord_corrected`). Poprawne pinezki, także na długich ulicach (np.
  Mełgiewska), zostają nietknięte — reverse zwraca tę samą ulicę. Reverse jest
  cache'owany (osobny budżet `MAX_REVERSE_GEOCODES`/skan). Na bieżących danych
  skorygowano 6 z 102 pinezek exact (Narcyzowa 3,7 km, Czwartek 1,7 km i in.).

### Wydajność
- **Lżejsza lista „bez lokalizacji GPS"**: potrafi mieć >1000 kart, więc jest
  teraz **malowana leniwie** — tylko po rozwinięciu sekcji i z limitem 200 kart
  — zamiast przebudowywać cały HTML przy każdej zmianie filtra.
- **Klastrowanie markerów wycofane** (na życzenie) — mapa pokazuje pojedyncze
  pinezki, bez grupowania w „bąble".

### Naprawione
- **Oferty z ulicą w tytule nie zawsze dostawały pinezkę** (np. „ul. Mełgiewska").
  Pętla doprecyzowania lokalizacji w `main.py` przerywała się po wyczerpaniu
  limitu 100 zapytań do Nominatim i pomijała WSZYSTKIE kolejne oferty — także te,
  których ulica była już w cache (czyli za darmo). Teraz limit ogranicza tylko
  NOWE zapytania na żywo (`StreetGeocoder(max_live=…)`), a wyniki z cache są
  stosowane do wszystkich aktywnych ofert. Efekt na bieżących danych: pinezki
  ze ~246 do ~860 bez ani jednego dodatkowego zapytania do Nominatim.

### Zmienione
- **Zmiana nazwy: „SONAR SPRZEDAŻY" → „SONAR SPRZEDAŻY MIESZKAŃ"** w całym
  projekcie (strony, tytuły, nagłówki, workflow, dokumentacja, docstringi).
- **Nowy schemat kolorystyczny — śliwkowo-bursztynowy** (deep violet + amber),
  celowo odróżniający SONAR SPRZEDAŻY MIESZKAŃ od zielonego SONARA DZIAŁKOWEGO: paleta
  CSS (`:root`), nagłówek/nawigacja/karty/przyciski, logo i favikona (blok
  mieszkalny w nowych barwach), kolory rynku na mapie (pierwotny = bursztyn,
  wtórny = fiolet) oraz serie wykresów w Analityce/Monitoringu/Statystykach.
  Zielenie semantyczne (spadek ceny, nowe oferty, oszczędność) zostały. Wersje
  cache assetów podbite (`?v=2`).

### Dodane
- Podstrona **📐 Statystyki** (`docs/statystyki.html`) z dodatkowymi przekrojami
  rynku: porównanie **rynku pierwotnego vs wtórnego** (mediana ceny/m², ceny,
  powierzchni, % od właściciela + wykres słupkowy), mediana ceny/m² **wg liczby
  pokoi** i **wg piętra**, **sortowalny ranking dzielnic** (oferty / mediana
  ceny/m² / ceny / powierzchni / % pierwotny) oraz **„Okazje cenowe"** —
  oferty z ceną/m² ≥15% poniżej mediany swojej dzielnicy (dzielnice z min.
  4 ofertami), z linkiem do ogłoszenia i do pinezki na mapie. Wpięta w
  nawigację wszystkich podstron. Czyta `docs/data.json` (bez zmian w backendzie).

## [0.1.0] — 2026-06-21

Pierwsza wersja **SONARA SPRZEDAŻY MIESZKAŃ** — monitoring ofert sprzedaży mieszkań
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
