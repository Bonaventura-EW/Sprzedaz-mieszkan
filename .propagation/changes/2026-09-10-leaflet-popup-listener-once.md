---
id:          2026-09-10-leaflet-popup-listener-once
repo:        Bonaventura-EW/Sprzedaz-mieszkan
family:      sonary
date:        2026-09-10
category:    bugfix
what:        Delegowany listener w dymku Leaflet podpinany RAZ na węzeł treści, nie przy każdym otwarciu popupu.
why:         "_contentNode" popupu przeżywa zamknięcie dymka, więc wieszanie delegacji w handlerze "popupopen" mnożyło listenery — nawigacja w dymku (strzałki ‹ ›) przeskakiwała o tyle pozycji, ile razy dymek był otwierany.
how:         Leaflet 1.9.4 (DivOverlay.onAdd) woła _initLayout() tylko "if (!this._container)", a onRemove kontenera nie zeruje; instancja popupu z bindPopup() żyje na markerze. Wystarczy znacznik na węźle (node._stackWired) i wczesny return — bez off()/once() i bez przebudowy popupu. Nowy węzeł powstaje dopiero z nowym markerem, czyli przy przebudowie warstwy.
surface:     docs/assets/script2.js
generality:  family
propagate:   yes
commit:      (uzupełni się po merge)
---

# Kontekst

Pułapka wychodzi tylko w wariancie z **delegacją zdarzeń** na treści dymka. Brat
(`SONAR---DZIA-KOWY`, manifest `2026-09-02-stos-pelne-szczegoly`) użył inline
`onclick` w generowanym HTML, więc go nie ma — pojawia się dopiero u tego, kto
przenosi ten wzorzec „porządniej", przez `addEventListener` w `popupopen`.

Objaw jest cichy: przy pierwszym otwarciu dymka wszystko działa, więc ręczny test
przechodzi. Rozjeżdża się dopiero po zamknięciu i ponownym otwarciu tego samego
dymka (bez przebudowy warstwy markerów w międzyczasie). Odtworzone w Chromium na
wyciętej z repo funkcji: 5 ofert, dymek otwarty 3× → jeden klik „›" przenosił
z pozycji 1 na 4.

Warto sprawdzić u siebie każdy `on('popupopen', …)`, który woła
`addEventListener` na `e.popup._contentNode` albo na czymkolwiek wewnątrz
`_container` popupu.
