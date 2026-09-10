---
id:          2026-09-10-maska-pokrycia-na-przeplywach
repo:        Bonaventura-EW/Sprzedaz-mieszkan
family:      sonary
date:        2026-09-10
category:    bugfix
what:        Maska dni z niepełnym pokryciem skanami obowiązuje też na wykresach przepływu, a dzień-luka jest rysowany jako przerwa, nie jako zero.
why:         Dzień, w którym skaner nie domknął wszystkich przebiegów, pokazywał zaniżony odpływ/napływ i rysował dołek, którego nie było — ten sam błąd, który wcześniej naprawiono na wykresie stanu (Indeksie), tylko na wykresach przepływu.
how:         Wartości w API zostają surowe, a maska jedzie osobno jako sekcja "coverage" (scans_per_day, last_complete, incomplete) w trend.json. Front zamienia dni z maski na null przy rozwijaniu szeregu sparse do dziennego, pomija je w oknie średniej kroczącej, rysuje wykres segmentami z przerwą i nie pozwala im ustanawiać rekordu ani rozcieńczać tempa. Hover na luce tłumaczy, co się stało.
surface:     src/trend_generator.py, docs/trend.html, tests/test_trend_generator.py
generality:  family
propagate:   yes
commit:      (uzupełni się po merge)
---

# Kontekst

Uzupełnienie wcześniejszej propagacji maski pokrycia (`2026-09-04-trend-charts-audit`
od SONAR-MIESZKANIOWY), która u nas objęła tylko wykres stanu.

**Pułapka warta przeniesienia:** naprawa NIE jest symetryczna do wykresu stanu.
Seria stanu jest gęsta — usunięcie dnia sprawia, że linia po prostu przechodzi
nad nim. Serie przepływu bywają **sparse i zerowo-wypełniane przy rozwijaniu do
osi dziennej** (u nas `expandDaily`: `map[t] || 0`), więc „usuń dzień z serii"
znaczy tam „narysuj zero" — czyli dokładnie ten dołek, który naprawiamy, tylko
głębszy. Trzeba rozróżnić „zero zdarzeń" od „brak pomiaru": u nas przez `null`
w rozwiniętej serii plus jawna maska w payloadzie.

Warte sprawdzenia u siebie, zanim się to przeniesie:
- czy Twój front zerowo-wypełnia luki w seriach sparse (wtedy dotyczy Cię ta
  pułapka),
- czy średnia krocząca liczy okno po indeksach (wtedy luka ją zaniża — u nas
  pomijana, średnia liczy się z dostępnych dni),
- czy statystyki karty („rekord", „średnia/dzień") biorą wszystkie punkty —
  dzień bez pomiaru nie powinien mieć prawa do rekordu.

Osobno zostaje przyczyna skoku NASTĘPNEGO dnia: jeśli dezaktywacja jest
potwierdzana z opóźnieniem (u nas `DEACTIVATE_GRACE_DAYS`), nadrobione
potwierdzenia lądują dzień później i robią sztuczny szczyt. To wymaga zmiany
definicji końca odcinka życia oferty, nie maski — u nas świadomie odłożone.
