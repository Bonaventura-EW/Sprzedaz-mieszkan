---
id: 2026-09-06-odpornosc-skanu
repo: Bonaventura-EW/sprzedaz-mieszkan
family: sonary
date: 2026-09-06
category: bugfix
what: Trzy awarie skanu widoczne wyłącznie w logu przy zielonym workflow — jeden timeout strony ucinał resztę listingu OLX, skokowa zmiana ceny była ignorowana bezterminowo, a częściowe załamanie źródła nie zapalało alertu.
why: Workflow skanera świecił się na zielono 171 przebiegów z rzędu (każdy krok ma `|| echo "::warning::"`), a w logach siedziały realne awarie: dwa skany oddały 407 i 486 ofert OLX zamiast ~1000, oferta z zamaskowaną ceną wisiała miesiącami na 1201 zł/m² jako „okazja", a dashboard pokazywał wszystko jako zdrowe.
how: (1) `_fetch` dostał 3 próby z narastającą przerwą, a nieudana strona jest POMIJANA zamiast kończyć paginację (`break` → `continue`); listing przerywa dopiero seria błędów z rzędu albo bezpiecznik liczby nieudanych stron w mieście. Źródło z pominiętymi stronami trafia do `incomplete_sources` i jest w całości wyłączone z dezaktywacji — ochrona ilościowa tego nie łapie, bo jedna strona to ~4% listingu. (2) Skok ceny ponad próg wymaga potwierdzenia: ta sama nowa cena w 2 skanach z rzędu zostaje przyjęta, inna zeruje licznik (`price.pending_change`). (3) Alerty źródeł dostały `kind` — obok `dead` (0 ofert) doszedł `partial` (ostatni skan < 60% maksimum z okna).
surface: src/olx_scraper.py, src/main.py, src/source_health.py, src/api_generator.py, docs/monitoring.html, tests/test_scan_resilience.py
generality: family
propagate: yes
commit: HEAD
---

# Kontekst dla braci

Wszystkie trzy błędy są **strukturalne, nie lokalne** — jeśli macie tę samą
architekturę (scraper paginujący listing + bramka na skok ceny + alert „martwe
źródło"), prawie na pewno macie je też u siebie. Diagnoza wyszła z przeglądu
logów Actions, nie z testów: workflow był zielony przez cały czas.

**Jak sprawdzić u siebie w 3 minuty:**

1. `grep -n "if not html" -A2 src/*scraper*.py` — jeśli po nieudanym pobraniu
   strony jest `break`, macie bug nr 1. Objaw w logu skanu: `❌ ... błąd
   pobierania ...?page=N` i zaraz potem `✅ zebrano <ułamek zwykłej liczby>`.
2. `grep -rn "PODEJRZANA\|MAX_PRICE_CHANGE" src/` — jeśli gałąź `else` tylko
   drukuje i nic nie zapisuje, macie bug nr 2. Objaw: te same ID w logu
   **każdego** skanu, tydzień po tygodniu.
3. `grep -n "last == 0" src/source_health.py` — jeśli alert warunkuje się
   wyłącznie zerem, częściowe załamanie jest u was niewidoczne.

**Pułapki przy adaptacji** (u nas realne):

- **Ponowienia same w sobie NIE wystarczą.** Retry bez zamiany `break` na
  `continue` tylko zmniejsza szansę awarii; wystarczy jedna strona, która padnie
  3× (u nas timeouty szły seriami), i znowu tracicie ogon listingu.
- **Trzeba ograniczyć czas.** Nieudana strona kosztuje ~70 s (3 próby × timeout
  + przerwy). Bez limitu nieudanych stron rwący się listing rozciąga skan z ~2
  na ~20 minut. Mamy dwa bezpieczniki: N błędów **z rzędu** (blokada) i N
  błędów **łącznie w mieście** (flaki).
- **Niekompletny listing musi blokować dezaktywację osobno**, nie przez próg
  ilościowy. Nasza ochrona `MIN_SCRAPE_RATIO = 0.5` przepuszcza brak jednej
  strony (~40 ofert z ~1000), a to wystarczy, żeby dezaktywować oferty, które
  wcale nie zniknęły — u nas ratowała je dopiero karencja.
- **Potwierdzanie ceny musi zerować licznik przy INNEJ cenie.** Inaczej
  powtarzające się różne wyskoki „uzbierają się" na potwierdzenie i wpuścicie
  do bazy właśnie to, przed czym broni bramka.
- Jeśli macie podstronę okazji/rankingu ceny za m², warto przy okazji zerknąć,
  co siedzi na jej szczycie. U nas oprócz zamrożonej ceny wypływały tam oferty
  „zamienię mieszkanie" za 450 zł i udziały TBS/SIM — inna klasa problemu
  (nie naprawiona tą zmianą), ale widać ją tym samym zapytaniem:
  aktywne oferty z ceną/m² poniżej ~4000 zł.

`propagate: yes` — bugi 1 i 3 są czysto mechaniczne i przenoszą się wprost.
Bug 2 zależy od tego, czy w ogóle macie bramkę na skok ceny; jeśli przyjmujecie
każdą zmianę bez progu, nie macie tego problemu (macie inny — śmieci w historii cen).
