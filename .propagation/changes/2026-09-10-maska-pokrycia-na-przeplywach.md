---
id:          2026-09-10-maska-pokrycia-na-przeplywach
repo:        Bonaventura-EW/Sprzedaz-mieszkan
family:      sonary
date:        2026-09-10
category:    bugfix
what:        Dni bez wiarygodnego pomiaru (niedomknięta doba skanów ALBO źródło, którego nie zobaczyliśmy ani razu) są maskowane na wszystkich wykresach trendu, a odpływ liczy się od dnia realnego zniknięcia oferty, nie od dnia potwierdzenia dezaktywacji.
why:         Dwa artefakty pomiaru udawały zdarzenia rynkowe: niedomknięta doba rysowała dołek odpływu, którego nie było, a blokada portalu (10 dni bez OLX) zlepiała całą wstrzymaną zaległość w jeden dzień powrotu — fałszywy rekord 231 ofert, trzykrotność normy, spłaszczający resztę wykresu.
how:         (1) Odcinek życia oferty kończy się na last_seen, a odpływ przypada nazajutrz — pierwszego dnia bez niej; dzień potwierdzenia dezaktywacji jest bezużyteczny jako klucz, bo spóźnia się o karencję albo o cały czas blokady. (2) Maska obejmuje doby z niepełną liczbą przebiegów ORAZ doby, w których żaden przebieg nie zobaczył któregoś źródła; liczy się najlepszy przebieg doby, więc jeden nieudany scrape niczego nie unieważnia. (3) Wartości w API zostają surowe, maska jedzie osobno jako sekcja "coverage" (scans_per_day, last_complete, incomplete, reasons); front zamienia te dni na null przy rozwijaniu szeregu sparse do dziennego, pomija je w oknie średniej kroczącej, rysuje wykres segmentami z przerwą, nie pozwala im ustanawiać rekordu ani rozcieńczać tempa, a ciągły ciąg luk kreśli jednym pasem.
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

**Druga pułapka, ważniejsza od pierwszej:** jeśli masz ochronę przed masową
dezaktywacją (pomijanie kasowania, gdy źródło zwróci podejrzanie mało ofert), to
przy dłuższej blokadzie portalu ta ochrona ROBI artefakt, przed którym chroni —
tylko przesunięty. Zaległość czeka i wchodzi jednym dniem, gdy źródło wróci.
U nas: 10 dni bez OLX i skok do 231 ofert w dniu powrotu, trzykrotność normy.

Kolejność napraw ma znaczenie: sama zmiana atrybucji na `last_seen` przesuwa
skok na PIERWSZY dzień blokady, gdzie kłamie tak samo mocno (te oferty nie
zniknęły — to my przestaliśmy je widzieć). Dopiero maska „źródła nie widzieliśmy
ani razu tej doby" sprawia, że zaległość ląduje w dniach oznaczonych jako brak
pomiaru, czyli tam, gdzie faktycznie nic nie wiemy. Odwrotnie też nie działa:
sama maska bez zmiany atrybucji zostawia skok w dniu powrotu, bo dzień powrotu
jest już w pełni zmierzony.
