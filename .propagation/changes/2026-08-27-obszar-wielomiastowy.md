---
id: 2026-08-27-obszar-wielomiastowy
repo: Bonaventura-EW/sprzedaz-mieszkan
family: sonar
date: 2026-08-27
category: feature
what: Obszar zbierania z jednego miasta rozszerzony na listę miast (rejestr CITIES) — u nas Lublin + Świdnik.
why: Sonar zaszywał nazwę miasta w scraperach, geokodowaniu i walidacji pinezek, więc dołożenie sąsiedniego miasta wymagało zmian w kilku plikach i cicho psuło statystyki porównawcze.
how: Rejestr `CITIES` w location_refiner jako jedno źródło prawdy (nazwa + bbox), `city_key()` normalizujący odmianę i zapis bez ogonków, `offer_city_key()` i `city_consistent()` zamiast porównań `'lublin' in city.lower()`. Nominatim pytany o miasto oferty; klucz cache dla miasta bazowego zostaje bez prefiksu, żeby nie wychłodzić istniejącego cache'u. Scrapery mają `LISTING_URLS` (listing na miasto) i wspólne `seen_ids`. Miasto trafia do data.json i staje się częścią każdego klucza grupowania w rankingu okazji.
surface: src/location_refiner.py, src/olx_scraper.py, src/otodom_scraper.py, src/main.py, src/map_generator.py, docs/okazje.html, docs/assets/script2.js, tests/test_location_refiner.py
generality: family
propagate: maybe
commit: (uzupełniane przy commicie)
---

# Kontekst dla braci

**Kiedy to jest dla Was.** Tylko jeśli ktoś u Was chce zbierać z więcej niż
jednego miasta. Jeśli nie — zignorujcie; koszt jest realny (dotyka scraperów,
geokodowania i frontendu), a zysk zerowy przy jednym mieście.

**Trzy pułapki, na które warto się przygotować** — każda z nich kosztowała nas
osobne znalezisko, a żadna nie jest widoczna w „dodaj drugi URL listingu":

1. **Sam URL to za mało.** Nazwa miasta była zaszyta w trzech miejscach
   geokodowania: zapytanie strukturalne do Nominatima (`city: 'Lublin'`),
   sprawdzenie `display_name` i walidacja miasta z reverse geocodingu. Oferty
   z drugiego miasta pobierały się poprawnie, ale ich pinezki lądowały w sekcji
   „bez GPS". Poszukajcie u siebie wszystkich literałów z nazwą miasta, zanim
   dodacie listing.
2. **Bboxy sąsiadujących miast zachodzą na siebie.** Nasz bbox Lublina
   geometrycznie zawiera cały Świdnik, więc sprawdzenie „czy punkt jest
   w bboxie" nie rozróżnia miast. O przynależności musi decydować nazwa miasta
   z adresu (geokodowanie: `display_name`; reverse: pole `city`), a bbox zostaje
   tanim filtrem wstępnym.
3. **Statystyki porównawcze cicho kłamią.** To najgroźniejsze. Jeśli macie
   ranking/porównanie oparte o medianę (u nas zakładka „Okazje"), a drugie
   miasto jest tańsze, to KAŻDA oferta z niego wyjdzie jako okazja — bo
   porównuje się z medianą całego zbioru zdominowanego przez miasto większe.
   Miasto musi być częścią każdego klucza grupowania. To samo dotyczy
   deduplikacji po cenie i metrażu: bez GPS identyczna kawalerka z dwóch miast
   sklei się w jedną ofertę, więc dołóżcie warunek na miasto.

**Zgodność cache'u geokodowania.** Klucze cache dla miasta bazowego zostawiliśmy
BEZ prefiksu (`"żywnego"`), a prefiksujemy tylko nowe miasta
(`"swidnik|wyszyńskiego"`). Wygląda to na niekonsekwencję i taka jest celowo:
przepisanie wszystkich kluczy wychładza cały cache, a przy budżecie ~100 zapytań
na skan odbudowa trwałaby kilkanaście przebiegów. Jeśli u Was cache jest mały
albo budżet duży — możecie prefiksować wszystko i mieć czystszy kod.

**Czego NIE zrobiliśmy**: wariantu z promieniem (`distanceRadius` na Otodomie)
ani z całym powiatem. Promień bierze też kierunki, których nikt nie chciał,
a powiat wciąga wsie daleko poza obszar zainteresowania. Lista konkretnych miast
jest nudna, ale przewidywalna — i łatwo ją rozszerzyć o kolejny wpis.
