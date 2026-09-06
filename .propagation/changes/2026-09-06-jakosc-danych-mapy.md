---
id: 2026-09-06-jakosc-danych-mapy
repo: Bonaventura-EW/sprzedaz-mieszkan
family: sonary
date: 2026-09-06
category: bugfix
what: Dwie ciche straty jakości danych — walidacja dzielnicy wyrzucała z mapy 117 poprawnych pinezek na skan, a ranking okazji jako najlepsze okazje pokazywał oferty, które nie są sprzedażą mieszkania (zamiana, TBS, udział, licytacja).
why: Obie rzeczy wyglądały jak „tak ma być": licznik zla_dzielnica=142 w Debugu czytało się jako sukces filtra, a 9 zł/m² na szczycie okazji jak ciekawostkę. Dopiero przegląd wszystkich przypadków pokazał, że filtr dzielnicy myli „ulica po granicy" z „pinezka na drugim końcu miasta", a ranking okazji porównuje ceny z zupełnie różnych transakcji.
how: (1) Gdy reverse geocoding zwraca inną dzielnicę niż ogłoszenie, pytamy Nominatima o BBOX deklarowanej dzielnicy i sprawdzamy, czy pinezka w nim leży — nazwą ulicy tego nie rozstrzygniemy, bo pinezkę postawił nasz geokoder na tej właśnie ulicy, więc reverse zawsze ją potwierdzi (również dla pinezek fałszywych). Zapytań jest tyle, ile dzielnic (~28), granice się nie przesuwają, więc po pierwszym skanie wszystko jest w cache. (2) Ofertę uznajemy za „cena nieporównywalna" dopiero, gdy sygnał TEKSTOWY (zamiana/TBS/partycypacja/udział/licytacja) spotyka się z ceną za m² poniżej połowy mediany miasta; sam tekst daje fałszywe trafienia na zwykłych sprzedażach („0% prowizji, możliwa zamiana").
surface: src/location_refiner.py, src/offer_kind.py, src/main.py, src/map_generator.py, src/api_generator.py, src/debug_generator.py, docs/debug.html, tests/test_offer_kind.py, tests/test_location_refiner.py
generality: family
propagate: yes
commit: HEAD
---

# Kontekst dla braci

Obie zmiany wyszły z jednego nawyku, który polecam bardziej niż sam kod:
**przejrzeć CAŁĄ zawartość kubełka odrzuceń, nie licznik**. Licznik
„zla_dzielnica=142" wyglądał jak działający filtr przez wiele tygodni.

## 1. Walidacja dzielnicy wyrzuca poprawne pinezki

Dotyczy każdego repo, które geokoduje ulicę z tekstu ogłoszenia i weryfikuje
wynik reverse geocodingiem. Objaw: duży, stabilny licznik odrzuceń „zła
dzielnica", a w środku ulice, które po prostu są długie.

**Jak sprawdzić u siebie:** wypisz pary (dzielnica z ogłoszenia → dzielnica
z reverse) dla odrzuconych ofert i pogrupuj po ulicy. Jeśli w czołówce siedzą
pojedyncze ulice z kilkunastoma ofertami każda, a `reverse.road` **równa się**
ulicy, której szukaliście — to nie są błędne pinezki, tylko granice dzielnic.

**Pułapka nr 1 (kosztowała mnie pierwsze podejście):** kuszące jest przyjąć
regułę „jeśli reverse potwierdza ulicę z ogłoszenia, zostaw pinezkę". To
wyłącza filtr całkowicie — pinezkę postawił wasz geokoder na tej ulicy, więc
reverse ZAWSZE ją potwierdzi, także dla ulicy wyłuskanej ze stopki agencji.
U nas pojedyncza taka ulica (Zalewskiego) odpowiadała za 61 z 247 odrzuceń.
Rozstrzyga geografia, nie nazwa.

**Pułapka nr 2:** Nominatim na zapytanie o nieistniejącą dzielnicę nie zwraca
pustki, tylko „ratuje" je całym miastem. Bbox miasta przepuszcza wszystko, więc
trzeba sprawdzić `addresstype` wyniku (`suburb`/`quarter`/`neighbourhood`/…).

**Pułapka nr 3:** bbox to prostokąt na nieregularnym wielokącie — ulica
graniczna bywa tuż za krawędzią. Zapas ~450 m u nas wystarczył (9 ofert
uratowanych właśnie zapasem).

Dajcie bboxom **osobny budżet** zapytań. Dzielnic są dziesiątki, nie tysiące,
i po pierwszym skanie siedzą w cache na zawsze — nie ma powodu, żeby
konkurowały z budżetem na geokodowanie ulic.

## 2. Ranking okazji porównuje nieporównywalne

Dotyczy każdego repo z rankingiem „najtańsze za m²" albo z medianą/decylami
kolorującymi pinezki. Ogłoszenia, które nie są sprzedażą własności, mają cenę
z innej skali i lądują dokładnie na szczycie rankingu.

**Jak sprawdzić u siebie:** wypisz aktywne oferty z ceną za m² poniżej ~40%
mediany i przeczytaj tytuły. U nas cały ten ogon to były: zamiana za cenę
symboliczną, partycypacja TBS/SIM, cesja najmu, ułamkowy udział i cena
wywoławcza z licytacji.

**Pułapka:** nie filtrujcie po samym tekście. „0% prowizji, możliwa zamiana"
i „Sprzedam/zamienię" to zwykłe sprzedaże po zwykłej cenie — u nas wzorzec
tekstowy sam z siebie złapał 7 ofert, z czego 6 było poprawnych ofert
sprzedaży. Dopiero koniunkcja „podejrzany tekst ORAZ cena odstająca w dół"
trafia w sam ogon: 7 trafień, wszystkie prawdziwe, zero fałszywych.
Próg dobierzcie pomiarem, nie na oko — sprawdźcie, czy sąsiednie wartości
(0.5 i 0.6) dają ten sam wynik. Jeśli tak, próg leży na płaskowyżu i nie
przewróci go drobna zmiana rynku.

I liczcie medianę **per miasto**, jeśli zbieracie z więcej niż jednego —
inaczej całe tańsze miasto wyjdzie jako „cena odstająca".
