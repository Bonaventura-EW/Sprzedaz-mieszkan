---
id: 2026-09-03-trend-wspolna-belka
repo: Bonaventura-EW/sprzedaz-mieszkan
family: sonary
date: 2026-09-03
category: bugfix
what: Podstrona „Trend w czasie" dostała wspólną belkę nawigacji (.header/.header-nav) zamiast własnego topbara z jednym linkiem „← Mapa".
why: trend.html powstał jako samodzielna strona z osobnym designem i jako jedyna zakładka nie linkowała assets/style.css — z Trendu nie dało się przejść wprost do żadnej innej zakładki, a belka wyglądała inaczej niż na reszcie serwisu.
how: Dołączony wspólny arkusz `assets/style.css`, `.topbar` (`.btn-back`, `.logo`, `.page-title`) zastąpiony standardowym `<header class="header">` z pełnym `.header-nav` i `logo.js`. Własny przełącznik motywu Trendu zostaje — `.btn-theme` przestylowany na pigułkę belki i wstawiony obok „Ostatni scan". Sprawdzone kolizje selektorów: `.chart-card` ze wspólnego arkusza wnosi `margin-bottom`, wyzerowany lokalnie; belka dostaje font-family ze `style.css`, bo body strony używa DM Sans. `#last-scan` uzupełniany z `api/status.json`.
surface: docs/trend.html
generality: family
propagate: maybe
commit: 6363f09
---

# Kontekst dla braci

Sprawdźcie u siebie prostym testem: `grep -L "style.css" docs/*.html`. Jeżeli
`trend.html` (albo inna „designerska" podstrona zbudowana osobno) nie linkuje
wspólnego arkusza, prawdopodobnie ma ten sam problem — nawigacja tylko „wstecz
do mapy" i inna typografia belki.

**Pułapki przy adaptacji** (u nas realne, nie hipotetyczne):

1. Strona ze swoim własnym systemem CSS zderza się ze wspólnym arkuszem po
   nazwach klas, nie zmiennych — u nas zmienne (`--bg-primary` vs `--bg`) się
   nie pokrywały, ale `.chart-card` już tak. Warto przelecieć listę selektorów
   wspólnego arkusza i porównać z klasami strony.
2. Jeśli podstrona ma przełącznik jasny/ciemny, a belka jest zawsze ciemna
   (u nas fioletowy gradient), przycisk trzeba przestylować na kolory belki —
   inaczej w jasnym motywie znika na tle gradientu.
3. Body podstrony może mieć własny font — belka dziedziczy go i wygląda inaczej
   niż na reszcie zakładek; łatwiej narzucić `.header { font-family: … }` niż
   ruszać typografię strony.

`propagate: maybe`, bo to zależy od tego, czy brat w ogóle ma osobno zbudowaną
podstronę Trendu — jeśli jego trend.html od początku używa wspólnego arkusza,
nie ma tu nic do przeniesienia.
