# CHANGELOG

## [Niewydane]

### Dodane — checklista „Zanim zaczniesz pracę" w `CLAUDE.md`
Nowa sekcja na samej górze pliku: przed rozpoczęciem zadania sprawdź otwarte
issues (zwłaszcza `propagation`), otwarte PR-y i gałęzie `claude/*`, sekcję
`## [Niewydane]` w tym pliku, `.propagation/changes/` oraz ostatnie przebiegi
Actions. Powód z życia: belkę nawigacji na `trend.html` naprawiliśmy „na świeżo",
a automat propagacji miał już otwarte issue #13 z gotową analizą, listą pułapek
i trafną rekomendacją — kilka godzin wcześniej.

### Naprawione — belka nawigacji na zakładce „Trend w czasie"
`docs/trend.html` był jedyną podstroną bez wspólnej belki (fioletowy pasek
z logo i pigułkami Mapa / Okazje / Analityka / …). Powstał jako samodzielna
strona z własnym designem (własne zmienne CSS, `JetBrains Mono` + `DM Sans`,
przełącznik motywu) i **nie linkował `assets/style.css`** — miał zamiast tego
własny `.topbar` z jednym przyciskiem „← Mapa", więc z Trendu nie dało się
przejść wprost do żadnej innej zakładki.
- `docs/trend.html` — dołączony `assets/style.css?v=9`; `.topbar` (wraz z
  `.btn-back`, `.logo`, `.page-title`) zastąpiony standardowym
  `.header` + `.header-nav` z kompletem 9 linków i `trend.html` jako `active`.
- Zachowany przełącznik motywu Trendu — `.btn-theme` przestylowany na bursztynową
  pigułkę belki i wstawiony obok „Ostatni scan" (`.header-right`).
- `#last-scan` uzupełniany z `api/status.json` (fallback: `trend.generated`),
  tak jak na pozostałych podstronach; dołączony `assets/logo.js?v=7` (SVG logo).
- Kolizje ze wspólnym arkuszem: `.chart-card` z `style.css` wnosiło
  `margin-bottom: 16px` → wyzerowane lokalnie; belka dostała rodzinę czcionek
  ze `style.css`, żeby wyglądała identycznie jak na pozostałych zakładkach.
- Sprawdzone: jasny i ciemny motyw, 1920 / 1500 / 400 px (bez poziomego scrolla).

### Naprawione — grupowanie pinezek na identycznych współrzędnych (klikalność)
Precyzja `street` (geokodowanie ulicy bez numeru domu, `location_refiner.py`)
zwraca jeden reprezentatywny punkt dla całej ulicy, więc każda oferta bez numeru
na danej ulicy lądowała w dokładnie tym samym `lat/lon`. Na canvasie hit-testing
trafiał tylko wierzchni kształt — reszta była wizualnie i funkcjonalnie
niedostępna. Na naszych danych (`docs/data.json`) to **463 punktów-stosów i 4410
ofert nie do otwarcia**, rekordowo **257 ofert w jednym punkcie**
(np. ul. Księdza Ludwika Zalewskiego).
- `docs/assets/script2.js` — przed rysowaniem grupuję oferty po zaokrąglonych
  współrzędnych (`lat.toFixed(6),lon.toFixed(6)`). Grupa 1-elementowa idzie starą
  ścieżką; większa dostaje **jedną pinezkę tego samego kształtu** (kropla/kwadrat)
  z **liczbą ofert w środku** i kolorem najtańszej pozycji (wg ceny/m²).
- Popup stosu: nagłówek „N ofert pod tym adresem" + **przewijalna, płaska lista**
  posortowana od najtańszej; każdy wiersz to link do ogłoszenia (`http(s)`-only).
  Skala u nas bywa duża (257) → lista scrolluje się (`max-height`).
- W rejestrze `markerById` **każde id z grupy** wskazuje ten sam marker, więc
  deep-link `#offer=<id>` do oferty w stosie otwiera popup i **przewija do jej
  wiersza** (podświetlenie `.stack-row-focus`).
- `docs/assets/style.css` — style listy stosu; `docs/index.html` — bump
  `style.css`/`script2.js` na `?v=9` (cache-busting).
- Propagacja z **SONAR-POKOJOWY** (`2026-08-31-coincident-marker-stacks`,
  issue #8). U brata to Leaflet `L.divIcon`; u nas przeniesione na renderer
  canvas (własne klasy `Path`), a „podświetlenie karty w panelu" zastąpione
  linkiem, bo nie mamy panelu kart — tylko popup.

### Dodane — ⭐ wykrywanie płatnych wyróżnień OLX + trend (propagacja z SONAR-POKOJOWY)
Nie zbieraliśmy dotąd żadnej informacji o tym, ile ofert jest płatnie wypychanych
na górę listingu OLX ani jak ten udział zmienia się w czasie. Teraz scraper czyta
wyróżnienie z parametru atrybucji `search_reason=search|promoted`, który OLX
doszywa do URL-a oferty (pewniejsze niż klasy CSS / `data-testid`), a zakładka
„Trend w czasie" pokazuje dzienny wykres liczby wyróżnionych ofert.
- `src/olx_scraper.py` — `_is_promoted_href` (odczyt `search_reason` z query
  stringa URL-a, czytany w `normalize_ad` PRZED przycięciem `url.split('?')[0]`);
  pole `promoted` w znormalizowanej ofercie; licznik atrybucji + alarm w logach,
  gdy żadna oferta nie niesie `search_reason` (OLX zmienił format → metryka po
  cichu spadłaby do zera). Otodom nie ma tej atrybucji — feature dotyczy tylko OLX.
- `src/main.py` — `_track_promoted` zapisuje stan bieżący (`promoted`) i historię
  dni (`promoted_dates`, max 1 wpis/dzień — z niej liczy się szereg czasowy);
  `_add_new` zasiewa historię, `_mark_inactive` zdejmuje `promoted` ofertom poza
  bieżącym listingiem (historia zostaje). Licznik wyróżnionych w podsumowaniu skanu
  i w `scan_history.json`.
- `src/trend_generator.py` — nowa seria `promoted` w `trend.json` (per kategoria,
  sparse: liczba wyróżnionych ofert danego dnia). Historia startuje od wdrożenia —
  wyróżnień nie da się odtworzyć wstecz.
- `docs/trend.html` — czwarta karta przepływu „⭐ Płatne wyróżnienia (OLX)"
  (dzienna liczba + średnia 7 dni) na istniejącej mechanice `FLOW_CONFIGS`; dla
  metryki STANU pomijamy stat „Suma w oknie" (`noTotal`).
- `tests/test_promoted.py` — detekcja z URL-a, trackowanie dni, reset przy zniknięciu
  z listingu, dzienny szereg w `build_trend`.

Różnice wobec wersji brata (SONAR-POKOJOWY): brat parsuje HTML kart (BeautifulSoup)
i ma fallback na plakietkę `data-testid`; my czytamy `__PRERENDERED_STATE__` (JSON),
więc detekcja opiera się wyłącznie na `search_reason` w URL-u, bez fallbacku CSS.
Frontend brata to ApexCharts z osobnym wykresem udziału — u nas kategorie dzienne
`trend_generator` + karta `FLOW_CONFIGS`, bez osobnej serii udziału (proporcjonalna,
dublowałaby kształt).

### Dodane — 💲↓ znacznik obniżki w Okazjach prowadzi do historii ceny
Znacznik `💲↓ <kwota>` na karcie w zakładce Okazje mówił, że sprzedający zszedł
z ceny, ale nie dawało się sprawdzić kiedy i z jakiego poziomu. Teraz jest
linkiem do `oferty.html#offer=<id>`, który otwiera zakładkę Oferty **w widoku
Split, z tą ofertą zaznaczoną i jej wykresem ceny w czasie**.
- `docs/okazje.html` — znacznik jako `<a>` z podpowiedzią („Cena spadła o X —
  zobacz historię ceny tej oferty") i podświetleniem pod kursorem, żeby było
  widać, że jest klikalny.
- `docs/oferty.html` — obsługa `#offer=<id>` przy wejściu i przy `hashchange`
  (działa też wstecz/naprzód w przeglądarce): przełącza na Split, zaznacza ofertę,
  przewija do niej listę. Format hasha jest ten sam co w mapie (`index.html`).
- Filtry: zdejmujemy **tylko te**, które akurat ukrywają wskazaną ofertę
  („tylko aktywne" dla nieaktywnej, chipy źródła przy konflikcie, szukajka gdy
  nie pasuje) — reszta ustawień użytkownika zostaje nietknięta. Nieznane id nie
  robi nic: strona otwiera się normalnie w widoku tabeli.

### Naprawione — 🔎 reverse geocoding przepalał budżet na ofertach bez dzielnicy
Przy rozszerzaniu obszaru o Świdnik przestawiłem kolejność w `district_consistent`
tak, że reverse geocoding wołał się PRZED wyjściem dla ofert bez dzielnicy —
czyli dla całego OLX-a, gdzie i tak nie ma czego walidować. Ograniczony budżet
`MAX_REVERSE_GEOCODES` schodził więc na oferty, które nic z tego nie miały,
zamiast na te z dzielnicą do sprawdzenia.
- Wyjście wróciło przed wywołanie reverse. Miasta w tej ścieżce nie sprawdzamy:
  pinezkę `street` postawił nasz geokoder, związany bboxem i nazwą miasta oferty,
  więc kontrola niczego nie dokłada.
- Scenariusz „pinezka w sąsiedniej gminie" przeniesiony do testów
  `otodom_coords_plausible` — tam współrzędne pochodzą z Otodom (nie z naszego
  geokodera), reverse i tak leci, więc kontrola miasta faktycznie chroni.
- Nowy test pilnuje, że oferta bez dzielnicy nie wywołuje reverse ani razu. 63 testy.

### Naprawione — 🏙️ Otodom Świdnik: 404 na zgadniętej ścieżce listingu (skan #151)
Pierwszy skan po rozszerzeniu obszaru pokazał, że **OLX Świdnik działa (77 ofert),
a Otodom Świdnik zwracał 404**. Ścieżka Otodom to województwo/powiat/gmina/miasto,
a ja zbudowałem ją przez analogię do Lublina (`lubelskie/lublin/lublin/lublin`) —
tyle że Lublin jest miastem na prawach powiatu, a Świdnik leży w powiecie
**świdnickim**, więc slug powiatu nie równa się nazwie miasta.
- `LISTING_URLS` w `otodom_scraper.py` trzyma teraz **listę kandydatów** na miasto;
  `_pick_listing_url()` bierze pierwszą ścieżkę, która na stronie 1 cokolwiek
  zwróci, i loguje, który wariant zadziałał. Powód: URL-i nie da się sprawdzić
  z maszyny agenta (brak dostępu do otodom.pl), więc bez tego każda pomyłka
  w slugu kosztowała pełny skan. Efekt uboczny jest trwale przydatny — zmiana
  slugu po stronie Otodom degraduje się do kolejnego wariantu zamiast po cichu
  zbierać zero ofert.
- Miasto, które nie zebrało ani jednej oferty, krzyczy w logu (wcześniej cicha
  linijka „0 ofert" ginęła — ochrona przed masową dezaktywacją działa PER ŹRÓDŁO,
  więc puste miasto niczego nie zapala).
- **Filtr miasta dla Otodom**: listing dokleja miejscowości z okolicy — w bazie
  siedziało 6 ofert z Jakubowic Konińskich i 1 z Dominowa, wszystkie z Otodom.
  Teraz oferta z miastem spoza `CITIES` jest odrzucana już w scraperze (brak
  miasta w ofercie nadal przechodzi). To zabezpiecza też ostatniego kandydata
  ścieżki (poziom powiatu), żeby nie wciągnął Mełgwi i Piask.

### Dodane — 🗺️ obszar zbierania rozszerzony o Świdnik (Lublin + miasto Świdnik)
Wariant A z ustaleń: portale odpytujemy o dwa miasta, bez powiatu i bez promienia.
Sam URL listingu by nie wystarczył — pinezki ze Świdnika i tak wypadałyby jako
„poza Lublinem", bo nazwa miasta była zaszyta w trzech miejscach geokodowania.
- **`src/location_refiner.py`** — rejestr `CITIES` (Lublin, Świdnik) zamiast
  zaszytego „Lublin": `city_key()` (normalizuje odmianę i zapis bez ogonków),
  `offer_city_key()`, `city_consistent()`, `_in_city()`. Nominatim pytamy
  o miasto oferty, a nie zawsze o Lublin. Bboxy obu miast ZACHODZĄ na siebie
  (sąsiadują), więc o przynależności decyduje nazwa miasta w adresie, nie bbox.
  Klucz cache geokodowania dla Lublina został BEZ prefiksu — inaczej cały
  `data/geocoding_cache.json` stałby się zimny i skany przepalałyby budżet
  100 zapytań. Nazwa miasta dopisana do stop-words ekstrakcji ulic.
- **`src/olx_scraper.py`, `src/otodom_scraper.py`** — `LISTING_URL` →
  `LISTING_URLS` (osobny listing na miasto), paginacja w pętli po miastach ze
  wspólnym `seen_ids`. OLX: filtr `cityNormalizedName` przepuszcza teraz oba
  miasta zamiast samego Lublina.
- **`src/main.py`** — deduplikacja OLX↔Otodom pilnuje miasta: przy obszarze
  z dwóch miast sama zgodność ceny i metrażu to za mało, bo OLX nie ma GPS
  i identyczna kawalerka z Lublina i ze Świdnika sklejałaby się w jedną ofertę.
- **`src/map_generator.py`** — `city` jedzie do `docs/data.json`.
- **`docs/okazje.html`** — miasto jest częścią KAŻDEGO klucza grupowania
  (kaskada: miasto+dzielnica+pokoje+rynek → … → całe miasto → cały obszar).
  Bez tego tańszy Świdnik porównywałby się z medianą Lublina i **każde** tamtejsze
  mieszkanie wychodziłoby jako okazja. Doszedł filtr „Miasto", kolumna w tabeli,
  miasto w szukajce i na karcie.
- **`docs/assets/script2.js`** — `LUBLIN_CENTER` → `AREA_CENTER`
  `[51.2380, 22.6150]`: widok startowy obejmuje oba miasta (Świdnik leży ~10 km
  na wschód od centrum Lublina).
- Tytuły, README i CLAUDE.md mówią teraz „Lublin i Świdnik"; nowy punkt 6b
  w CLAUDE.md opisuje rejestr miast i pułapkę z grupowaniem okazji.
- Testy: 8 nowych (normalizacja nazw miast, pinezka w Świdniku przechodzi,
  oferta z Lublina z pinezką w Świdniku odrzucona, sąsiednia gmina odrzucona,
  refiner pyta o miasto oferty, nazwa miasta nie jest ulicą). 61 przechodzi.

⚠️ **Niezweryfikowane na żywo**: URL-i listingów Świdnika nie dało się sprawdzić
z sandboxa (ruch do olx.pl i otodom.pl blokowany przez proxy). Ścieżki są zbudowane
wg schematu działających listingów lubelskich (OLX `/sprzedaz/swidnik/`, Otodom
`/lubelskie/swidnik/swidnik/swidnik`) — do potwierdzenia pierwszym skanem
`scanner.yml`. Gdyby były błędne, scrapery zalogują puste strony i pominą miasto,
bez wpływu na oferty lubelskie (ochrona przed masową dezaktywacją działa per źródło).

### Zmienione — 💎 „rabat" → „poniżej ceny rynkowej" w zakładce Okazje
Słowo „rabat" sugerowało obniżkę ceny przez sprzedającego — a od tego jest na
karcie osobny znacznik `💲↓`, więc dwa różne pojęcia chodziły pod jedną nazwą.
Nowe słownictwo mówi wprost, o co chodzi: **„X% poniżej ceny rynkowej"** (za ten
metraż). Świadomie używamy pełnego „cena rynkowa", nie samego „rynek" — „rynek"
w tym projekcie znaczy już pierwotny/wtórny i kolidowałoby z badge'em obok.
- Procent przeniesiony z rzędu badge'ów do linii ceny (`7610 zł/m² · 46% poniżej
  ceny rynkowej`) — stoi teraz przy liczbie, którą opisuje, i ma miejsce na pełne
  zdanie zamiast samego „−46%" obok znaczników źródła.
- Etykiety: KPI „Najlepszy rabat" → „Najlepsza okazja" (podpis: „poniżej ceny
  rynkowej · …"), tryb „💎 Największy rabat" → „💎 Poniżej ceny rynkowej",
  filtr „Min. rabat" → „Min. różnica", sortowanie „rabat vs porównywalne" →
  „różnica do ceny rynkowej", kolumna tabeli „Rabat" → „Poniżej rynkowej".
- Minus zniknął z wartości procentowych — kierunek niesie słowo „poniżej",
  więc `−46%` przy „poniżej" było podwójnym zaprzeczeniem.
- Sekcja „jak liczymy okazję" mówi teraz wprost, że to **nie jest** obniżka ceny
  przez sprzedającego, i odsyła do znacznika `💲↓`.
- Podpis „mediana grupy" pod paskiem wyrównany do fioletowego znacznika
  (wcześniej dosunięty do prawej krawędzi, nie wskazywał tego, co opisuje).

### Dodane — 💎 zakładka „Okazje": ranking ofert wg ceny za m²
Nowa podstrona `docs/okazje.html` (link w nawigacji wszystkich zakładek) pokazuje
oferty o najlepszym stosunku ceny do metrażu. Sama najniższa cena/m² w mieście to
za mało — tanie zł/m² zwykle znaczy tylko „daleko od centrum", dlatego okazję
liczymy **względem porównywalnych mieszkań**.
- **Odniesienie** = mediana zł/m² najwęższej grupy, w której starcza danych:
  dzielnica+pokoje+rynek (≥5) → dzielnica+pokoje (≥5) → dzielnica (≥5) →
  pokoje+rynek w całym Lublinie (≥8) → cały Lublin. Karta pokazuje, z czym
  dokładnie porównano ofertę i ile mieszkań było w grupie.
- **Rabat** = o ile % cena/m² jest niższa od mediany grupy; **szacowana
  oszczędność** = różnica zł/m² × powierzchnia.
- Dwa tryby rankingu: „największy rabat" (domyślny, próg ≥10%) i „najniższa
  cena/m²" (odczyt dosłowny). Filtry: źródło, rynek, pokoje, dzielnica, cena,
  powierzchnia, nowe (7 dni), od właściciela, po obniżce, tylko z lokalizacją,
  szukajka; sortowanie po rabacie / zł/m² / oszczędności / cenie / powierzchni /
  dacie. Widok kart i tabeli, doładowywanie po 60 pozycji.
- **Oferty nietypowe** (TBS/SIM, udziały, licytacje/syndyk, prawo lokatorskie,
  zamiana oraz zł/m² poniżej 55% mediany miasta) są domyślnie ukryte — inaczej
  zajmowały cały szczyt rankingu, mimo że nie są zwykłą sprzedażą własności.
  Checkbox je przywraca z bursztynową ramką i powodem oznaczenia; te oferty są
  też wykluczone z liczenia median odniesienia, żeby nie zaniżały rynku.
- Ranking liczy tylko oferty aktywne, z `docs/data.json` (już po deduplikacji
  OLX↔Otodom) — bez zmian w scraperach i generatorach.
- Sekcja „💡 Okazje cenowe" na `statystyki.html` dostała link do pełnego rankingu.
- Zweryfikowane w headless Chromium na produkcyjnym `data.json` (2128 aktywnych):
  386 okazji przy progu 10%, brak błędów w konsoli, poprawne działanie filtrów,
  obu widoków, „pokaż więcej" i layoutu mobilnego (390 px, bez poziomego scrolla).

### Operacja — 🔎 przebieg propagacji (evaluate-propagation), 2026-08-24 08:00
Pierwszy przebieg etapu decyzji. Sprawdzono manifesty zmian u czwórki rodzeństwa
(`SONAR-POKOJOWY`, `SONAR-MIESZKANIOWY`, `SONAR---DZIA-KOWY`, `parkingi-i-garaze`)
— tylko `parkingi-i-garaze` miał realny manifest: `2026-08-23-olx-tls-impersonation`
(curl_cffi z impersonacją TLS Chrome, ominięcie blokady WAF CloudFront na OLX).
**Werdykt: skip** — ten sam fix już wdrożony tu niezależnie 2026-08-22 i potwierdzony
na produkcji skanem #142 (`scraped_olx` wróciło z 0 do 931). Bez akcji. Wpis w
`.propagation/decisions.jsonl`, `last-review.json` zaktualizowany.

### Operacja — ✅ merge do main + skan weryfikacyjny #142 (2026-08-22 22:40)
Zmerge'owano gałąź do `main` i odpalono `scanner.yml` (workflow_dispatch, run #142,
6 min, sukces). Wyniki potwierdzają wdrożenia:
- **OLX wrócił**: `scraped_olx = 931` (z 0 przez 11 dni) — `curl_cffi(impersonate)`
  pokonał blokadę WAF. `health.json` → `status: ok`, `source_alerts: []` (alert
  poprawnie zgasł).
- **Opcja A działa**: log skanera `🚫 76 pinezek 'street' w złej dzielnicy →
  sekcja 'bez GPS'`; Debug `zla_dzielnica=53`. Reszta klastra Zalewskiego (Otodom)
  dobierze się w kolejnych skanach (budżet reverse 100/skan).
- **Audyt pinezek OLX**: 283 pinezki OLX na mapie (reszta z 931 ukryta jako
  duplikaty Otodom), wszystkie precyzji `street`; reverse-check 116/116 bez
  niezgodności (pinezka stoi na deklarowanej ulicy), brak zrzutu na centroid
  miasta. Ograniczenie strukturalne: OLX nie ma dzielnicy → 3b3 go nie waliduje,
  ale w praktyce pinezki OLX nie są przesunięte.
- Stan: 2837 aktywnych (2525 z pinezką, 312 „bez GPS"); 682 duplikaty OLX↔Otodom.

### Naprawione — 🗺️ Opcja A: walidacja pinezek „street" względem dzielnicy
Refiner (`refine_offer_location`) stawiał pinezkę na ulicy wyłapanej z tekstu bez
sprawdzenia, czy leży w deklarowanej dzielnicy oferty. Ulica z opisu dewelopera
(adres biura, „dojazd od ul. X") potrafiła przesunąć pinezkę o kilka km — klaster
~270 ofert na „ul. Zalewskiego" mimo dzielnic Sławin/Śródmieście/Stare Miasto.
- **`src/location_refiner.py`** — nowa funkcja `district_consistent()`: reverse
  geocoding pinezki i porównanie dzielnicy z ogłoszeniem (leniwie: brak dzielnicy
  lub brak budżetu reverse → zostawiamy; inna dzielnica / poza Lublinem → odrzut).
- **`src/main.py`** — krok 3b3: pinezki precyzji `street` z podaną dzielnicą, które
  reverse lokuje w innej dzielnicy → coords usuwane (oferta → sekcja „bez GPS").
  OLX (bez dzielnicy) i pinezki bez pokrycia reverse zostają nietknięte.
- **`tests/test_location_refiner.py`** — 5 testów `district_consistent`.
- Suchy przebieg na obecnym cache: 7 usunięć od ręki (Jemiołuszki, Urbanowicza,
  Wieniawska…), reszta dobierze się przez kilka skanów (budżet reverse 100/skan).

### Dodane — ♻️ wykresy reaktywacji i napływu na trend.html (wzór SONAR-POKOJOWY)
Reaktywacje były zapisywane (`reactivated_at`), ale nigdzie nie pokazywane. Dodano
dwa wykresy „dzienny + średnia 7-dniowa" (jak odpływ): 🔀 Napływ (nowe+reaktywacje)
i ♻️ Reaktywacje, obok istniejącego 📉 Odpływu.
- **`src/main.py`** — reaktywacja prowadzi pełną listę `reactivation_dates`
  (skalarny `reactivated_at` zostaje dla kompatybilności; historia zasiewana).
- **`src/trend_generator.py`** — `build_trend()` zwraca dodatkowo `inflow` i
  `reactivations` (sparse). Napływ = nowe (first_seen) + reaktywacje; pierwszy dzień
  osi (zasianie bazy) pomijany jako artefakt startu skanera.
- **`docs/trend.html`** — mechanika „odpływu" uogólniona w reużywalny komponent
  `makeFlowChart` (jeden kod dla 3 kart: odpływ/napływ/reaktywacje), własne zakładki
  zakresu i tooltipy; kolory: koral / zieleń / fiolet.
- **`tests/test_trend_generator.py`** — 3 testy (napływ, reaktywacje, fallback
  skalarny, pominięcie dnia zerowego).
- Zweryfikowano renderem headless (Chromium): 4 karty, brak błędów JS.

### Naprawione — 🌐 OLX zwraca 0 ofert od 2026-08-11 (blokada WAF po TLS fingerprincie)
Od skanu 2026-08-11 19:14 `scraped_olx` = 0 (ostatni udany 2026-08-11 09:40:
933 oferty). Otodom działa bez zmian → to nie awaria pipeline'u, tylko blokada
OLX po „pythonowym" fingerprincie TLS (JA3) biblioteki `requests`. Rozwiązanie:
impersonacja TLS Chrome przez `curl_cffi`, z fallbackiem do `requests` gdy
biblioteki brak (środowisko bez curl_cffi nadal działa).
- **`src/olx_scraper.py`** — opcjonalny import `curl_cffi`; `OLXMieszkaniaScraper`
  używa `Session(impersonate="chrome")`, fallback do `requests.Session`;
  `_fetch` łapie szeroko wyjątki (curl_cffi ma własne); log wybranego silnika.
- **`requirements.txt`** — dodano `curl_cffi>=0.7`.
- ⚠️ Do potwierdzenia realnym skanem (`scanner.yml` na `main`) — z tego
  środowiska nie odpytujemy OLX na żywo.

### Dodane — 🚨 alert w API/monitoringu, gdy całe źródło przestaje zwracać oferty
Wcześniej skan z `scraped_olx == 0` kończył się `completed`, więc `health.json`
zostawał „ok" i nic nie sygnalizowało wypadnięcia OLX. Dodano alert per źródło.
- **`src/source_health.py`** (nowy) — `compute_source_alerts()`: wykrywa źródło,
  które w ostatnim skanie oddało 0 ofert, mimo historii ofert lub aktywnych
  ofert trzymanych w bazie karencją; liczy `consecutive_zero_scans`.
- **`src/api_generator.py`** — `health.json` niesie `source_alerts`, a `status`
  = `degraded`, gdy jakieś źródło jest martwe (dotąd tylko ok/stale/failing).
- **`src/monitoring_generator.py`** — `monitoring_data.json` niesie
  `source_alerts` (aktywne oferty per źródło czytane z `offers.json`, by alert
  przetrwał zsunięcie okna historii).
- **`docs/monitoring.html`** — czerwony baner alertu nad kartami KPI.
- **`tests/test_source_health.py`** (nowy) — 5 testów logiki alertu.

### Audyt — 🗺️ oznaczenia na mapie (bez zmian w kodzie; ustalenia)
Audyt `docs/data.json` (5340 ofert, 4940 z pinezką). Ustalono m.in. błędne
przypisania ulicy z opisu (refiner nie waliduje ulicy względem dzielnicy) —
klaster 272 ofert na „ul. Zalewskiego" mimo dzielnic Sławin/Śródmieście/Stare
Miasto. Szczegóły i propozycja poprawki przekazane w odpowiedzi (do decyzji).

### Dodane — 🕒 guzik „Zobacz trend w czasie" na mapie
Wyraźny bursztynowy przycisk CTA w panelu bocznym `index.html` (pod kartą
statystyk), prowadzący do podstrony `trend.html` — obok istniejącego linku
w górnej nawigacji.
- **`docs/index.html`** — link `.sidebar-cta`; bump `style.css?v=7` → `?v=8`.
- **`docs/assets/style.css`** — styl `.sidebar-cta` (gradient bursztynowy, hover).

### Dodane — 🕒 podstrona „Trend w czasie" (bliźniak SZPERACZ)
Nowa strona `docs/trend.html` odtwarza wygląd i mechanikę
`SZPERACZ/trend.html`: dwa wykresy canvas (dark/light, drag-to-zoom,
tooltipy, watermark) — trend liczby aktywnych ofert w czasie oraz odpływ
ofert (dzienny + średnia 7-dniowa). Zamiast „profili wyszukiwania" (których
ten sonar nie ma) używamy kategorii naturalnych: **Wszystkie**, rynek
**pierwotny/wtórny**, źródło **OLX/Otodom**, liczba **pokoi (1/2/3/4+)**.
Szeregi dzienne są rekonstruowane z pól oferty (`first_seen` / `last_seen` /
`deactivated_at`), a odpływ = liczba ofert zarchiwizowanych danego dnia.
Duplikaty OLX↔Otodom (`duplicate_of`) są pomijane, jak chowa je mapa/API.
- **`src/trend_generator.py`** (nowy) — `build_trend()` → `docs/api/trend.json`
  (`labels` / `profiles` / `outflow`); pomija duplikaty, kotwiczy oś czasu od
  pierwszej archiwizacji do dziś (Europe/Warsaw).
- **`docs/trend.html`** (nowy) — pobiera `api/trend.json` + `api/status.json`
  na żywo (czas skanu z `last_scan`), fonty JetBrains Mono / DM Sans.
- **`.github/workflows/scanner.yml`** — krok „Generate trend data"
  (`trend_generator.py`); `docs/api/` już jest commitowane, więc `trend.json`
  wchodzi automatycznie.
- **Nawigacja** — link „🕒 Trend" dodany do wszystkich podstron
  (`index`, `analytics`, `statystyki`, `monitoring`, `oferty`, `zmiany`, `debug`).
- **`tests/test_trend_generator.py`** (nowy) — 6 testów `build_trend`
  (rekonstrukcja dzienna, odpływ, pomijanie duplikatów, predykaty kategorii,
  etykiety, pusta baza).

### Dodane — 📉 wykres trwale znikniętych ofert na „📐 Statystyki"
Nowa sekcja na dole `statystyki.html` pokazuje, ile ogłoszeń trwale zeszło
z rynku, pogrupowanych po dacie zniknięcia (przełącznik **Dziennie /
Miesięcznie**), z podziałem słupków na OLX/Otodom. Liczymy oferty obecnie
nieaktywne wg ich `deactivated_at` — gdy ogłoszenie zostanie wznowione
(`active=true`), automatycznie wypada z wykresu, więc słupki z przeszłości
mogą maleć. Im dłużej sonar działa, tym wierniejszy obraz realnych zniknięć
(zgodnie z założeniem: świeże dni jeszcze „drgają", stare się stabilizują).
- **`src/map_generator.py`** — `build_map_offer` dorzuca pole `deactivated_at`
  (zasila wykres; pole było już w `data/offers.json`, brakowało go w `data.json`).
- **`docs/statystyki.html`** — nowa karta „📉 Oferty, które trwale zniknęły":
  segmentowany przełącznik dzień/miesiąc, skumulowany wykres słupkowy
  (Chart.js, źródła OLX/Otodom), nota metodologiczna i łączny licznik.
  Nad każdym słupkiem łączna suma zniknięć z danego dnia/miesiąca (własny
  plugin `stackTotals` — bez dodatkowej zależności CDN; pomija serie wyłączone
  w legendzie, więc suma zgadza się z tym, co widać).
- **`docs/data.json`** — przegenerowane, by od razu zawierało `deactivated_at`
  (kolejny scan i tak nadpisze).

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
