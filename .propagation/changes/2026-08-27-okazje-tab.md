---
id: 2026-08-27-okazje-tab
repo: Bonaventura-EW/sprzedaz-mieszkan
family: sonar
date: 2026-08-27
category: feature
what: Nowa zakładka „Okazje" — ranking ofert wg ceny za m² względem mediany porównywalnych, nie względem całego miasta.
why: Użytkownik szuka okazji, a sortowanie po surowym zł/m² pokazuje głównie tanie lokalizacje i pułapki formalne (TBS, udziały, licytacje) zamiast realnie zaniżonych ofert.
how: Statyczna strona `docs/okazje.html` czytająca istniejący `docs/data.json` (zero zmian w scraperach i generatorach). Dla każdej aktywnej oferty liczymy medianę zł/m² najwęższej grupy z wystarczającą próbką (dzielnica+pokoje+rynek ≥5 → dzielnica+pokoje ≥5 → dzielnica ≥5 → pokoje+rynek w mieście ≥8 → całe miasto) i z niej rabat oraz szacowaną oszczędność (Δzł/m² × m²). Oferty nietypowe wykrywane regexami na tytule + progiem 55% mediany miasta są domyślnie ukryte i wykluczone z liczenia median. Widok kart i tabeli, filtry i sortowanie w całości po stronie klienta.
surface: docs/okazje.html, docs/index.html, docs/analytics.html, docs/statystyki.html, docs/monitoring.html, docs/oferty.html, docs/zmiany.html, docs/debug.html
generality: family
propagate: yes
commit: (uzupełniane przy commicie)
---

# Kontekst dla braci

**Co jest przenośne 1:1**: cała mechanika „okazji" — kaskada grup odniesienia,
rabat liczony względem mediany grupy zamiast mediany całego zbioru, oraz
wykluczenie ofert-pułapek z liczenia median. To działa wszędzie tam, gdzie
oferta ma cenę, powierzchnię i jakąś oś porównania (dzielnica / lokalizacja).

**Co trzeba dopasować u siebie**:
- *Wymiary grupowania*. U nas: dzielnica + liczba pokoi + rynek pierwotny/wtórny.
  Dla działek naturalne będzie dzielnica/gmina + przedział powierzchni (działka
  1500 m² i 400 m² to inny produkt, liczba „pokoi" nie istnieje). Dla pokoi /
  garaży — dzielnica + typ. Zasada jest ta sama: od najwęższej grupy w dół,
  z progiem minimalnej próbki, i **zawsze pokazuj użytkownikowi, z czym
  porównałeś ofertę** (etykieta grupy + n) — bez tego rabat jest nieweryfikowalny.
- *Progi próbki* (u nas 5 / 5 / 5 / 8). Przy mniejszym zbiorze ofert trzeba je
  obniżyć, przy większym można podnieść — celem jest ~75-80% pokrycia
  najwęższą grupą.
- *Reguły „ofert nietypowych"*. Nasze regexy (TBS, SIM, udział, syndyk,
  licytacja, prawo lokatorskie, zamiana) są specyficzne dla sprzedaży mieszkań.
  U braci listę trzeba napisać od nowa, ale **próg cenowy (u nas <55% mediany
  miasta) jest uniwersalny** — łapie to, czego słowa kluczowe nie złapią,
  łącznie ze zwykłymi błędami w danych.
- Skanujemy **tylko tytuł**, nie opis: w opisie „udział" bywa niewinny
  („udział w kosztach"). Fałszywe alarmy psują zaufanie do rankingu bardziej
  niż przeoczenia, które i tak wyłapie próg cenowy.

**Świadoma decyzja**: nietypowe oferty są *ukrywane, nie usuwane* — checkbox je
przywraca z bursztynową ramką i wypisanym powodem. Ranking, który po cichu
wycina dane, kłamie; ranking, który je pokazuje z ostrzeżeniem, uczy
użytkownika, na co patrzeć.

**Odrzucona alternatywa**: generator w Pythonie (`okazje_generator.py` →
`docs/okazje_data.json`). Cała potrzebna treść jest już w `data.json`, które
strona i tak by pobierała, a liczenie po stronie klienta pozwala zmieniać progi
i filtry bez czekania na kolejny skan. Gdyby u brata `data.json` był dużo
większy albo doszłyby cięższe metryki (np. odległość od centrum liczona per
oferta), generator zaczyna się opłacać.
