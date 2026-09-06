"""Rozpoznawanie ofert, których cena NIE jest ceną sprzedaży mieszkania.

FIX 2026-09-06: na szczycie `okazje.html` (ranking najtańszych za m²) siedziały
oferty, które w ogóle nie są sprzedażą własności — a to właśnie one wyglądają
jak najlepsze okazje, bo ich cena jest z zupełnie innej skali:

| co to jest                    | przykład z bazy                          | zł/m² |
|-------------------------------|------------------------------------------|-------|
| zamiana mieszkań              | „ZAMIENIĘ mieszkanie" (cena symboliczna) |     9 |
| partycypacja TBS/SIM          | „mieszkanie w systemie SIM (TBS)"        |  1121 |
| cesja/odstąpienie najmu       | „Odstąpię najem mieszkania TBS"          |  3128 |
| udział w nieruchomości        | „1/2 udziału w mieszkaniu 2-pokojowym"   |  4697 |
| licytacja (cena wywoławcza)   | „druga licytacja publiczna"              |     — |

Takie oferty zaniżają też medianę i decyle ceny za m² (`map_generator`), czyli
psują kolorowanie pinezek i statystyki — nie tylko ranking okazji.

Zasada doboru wzorców: **precyzja przed czułością**. Fałszywe trafienie chowa
prawdziwą ofertę z mapy, więc w tytule szukamy słów jednoznacznych, a w opisie
tylko fraz, które nie mają drugiego znaczenia. Dlatego NIE szukamy w opisie
samego „najem"/„wynajem" (setki ogłoszeń pisze „idealne pod wynajem") ani
samego „udział" („udział w częściach wspólnych" jest w co drugiej umowie).

**Sam tekst to jednak za mało** — sprawdzone na bazie: wzorzec „zamiana" łapie
też zwykłe sprzedaże („0% prowizji, możliwa zamiana", „Sprzedam/zamienię"),
gdzie zamiana jest tylko opcją, a cena najzwyklejsza w świecie. Dlatego ofertę
odsuwamy na bok dopiero, gdy **oba sygnały zgadzają się naraz**: tekst mówi
„to nie jest zwykła sprzedaż" ORAZ cena za m² odstaje w dół od mediany
(`NON_COMPARABLE_MAX_RATIO`). Dzięki temu nie da się ukryć normalnie wycenionego
ogłoszenia przez jedno niefortunne słowo w tytule, a łapiemy dokładnie ten
ogon, który psuł ranking.

Mediana liczona jest **per miasto** — patrz pkt 6b w CLAUDE.md: tańszy Świdnik
porównany do mediany Lublina wypadałby cały jako „cena odstająca".
"""

import re
import statistics
from collections import defaultdict
from typing import Dict, List, Optional

# ile znaków opisu przeglądamy — istotne frazy stoją na początku, a dalej rośnie
# ryzyko trafienia w klauzule umowne i stopkę agencji
DESCRIPTION_SCAN_CHARS = 600

# (kod, wzorzec w TYTULE, wzorzec w OPISIE — None gdy zbyt ryzykowny)
_RULES = (
    ('zamiana',
     r'\bzamieni[eę]\b|\bzamiana\b|\bdo zamiany\b|\bzamieni[ćc]\b',
     r'\bzamieni[eę] (?:mieszkanie|na)\b|\bzamiana na (?:wi[eę]ksze|mniejsze)\b'),
    ('tbs_sim',
     r'\bTBS\b|\bSIM\b|partycypacj',
     r'\bpartycypacj\w*\b|\bwk[łl]ad partycypacyjny\b'),
    ('cesja_najmu',
     r'odst[ąa]pi[eę]\w*\s+najem|odst[ąa]pienie najmu|cesj[aęi]\w*\s+najmu|'
     r'przekaz[eę]\s+najem',
     r'odst[ąa]pi[eę]\w*\s+najem|odst[ąa]pienie najmu|cesj[aęi]\w*\s+najmu'),
    ('udzial',
     r'\budzia[łl]\w*\b|\bwsp[óo][łl]w[łl]asno[śs][ćc]\w*\b',
     r'\b\d+\s*/\s*\d+\s+udzia[łl]\w*\b|\bsprzeda[żz]\w*\s+udzia[łl]\w*\b'),
    ('licytacja',
     r'\blicytacj\w*\b|\bkomornic\w*\b|\bprzetarg\w*\b|cena wywo[łl]awcza',
     r'\blicytacj[aei]\s+(?:publiczn|komornicz)\w*\b|cena wywo[łl]awcza'),
)

_COMPILED = tuple(
    (code, re.compile(title_pat, re.I), re.compile(desc_pat, re.I) if desc_pat else None)
    for code, title_pat, desc_pat in _RULES
)

# Czytelne etykiety na debug.html
LABELS = {
    'zamiana': 'zamiana mieszkań (cena symboliczna)',
    'tbs_sim': 'partycypacja TBS/SIM (nie własność)',
    'cesja_najmu': 'cesja/odstąpienie najmu (nie sprzedaż)',
    'udzial': 'udział w nieruchomości (nie całe mieszkanie)',
    'licytacja': 'licytacja/przetarg (cena wywoławcza)',
}


def classify_offer(offer: Dict) -> Optional[str]:
    """Kod powodu, dla którego cena oferty nie jest ceną sprzedaży mieszkania.

    Zwraca None dla zwykłej oferty sprzedaży (zdecydowana większość).
    """
    title = offer.get('title') or ''
    description = (offer.get('description') or '')[:DESCRIPTION_SCAN_CHARS]
    for code, title_re, desc_re in _COMPILED:
        if title_re.search(title):
            return code
        if desc_re is not None and desc_re.search(description):
            return code
    return None


def label(code: Optional[str]) -> Optional[str]:
    return LABELS.get(code) if code else None


# Cena za m² poniżej tego ułamka mediany miasta = „odstająca w dół". 0.5 wyszło
# z pomiaru na bazie: przy 0.5 i 0.6 wynik jest IDENTYCZNY (7 ofert), więc próg
# leży na płaskowyżu, a nie na ostrzu — drobna zmiana rynku go nie przewróci.
NON_COMPARABLE_MAX_RATIO = 0.5
# poniżej tylu ofert w mieście mediana jest zbyt chwiejna, żeby na niej wyrokować
MIN_CITY_SAMPLE = 30


def _city_medians(offers: List[Dict]) -> Dict[str, float]:
    per_city = defaultdict(list)
    for o in offers:
        if o.get('active') and o.get('price_per_m2'):
            city = (o.get('location') or {}).get('city') or '?'
            per_city[city].append(o['price_per_m2'])
    return {city: statistics.median(vals) for city, vals in per_city.items()
            if len(vals) >= MIN_CITY_SAMPLE}


def tag_non_comparable(offers: List[Dict]) -> int:
    """Oznacza oferty, których cena nie jest porównywalną ceną sprzedaży.

    Ustawia `price_not_comparable` = kod powodu (albo go zdejmuje, gdy oferta
    przestała spełniać warunek — np. sprzedający poprawił cenę). Generatory
    mapy i API chowają takie oferty, `debug_generator` je wylicza z powodem.

    Returns: liczba oznaczonych ofert.
    """
    medians = _city_medians(offers)
    tagged = 0
    for offer in offers:
        code = None
        ppm = offer.get('price_per_m2')
        if offer.get('active') and ppm:
            city = (offer.get('location') or {}).get('city') or '?'
            median = medians.get(city)
            if median and ppm < median * NON_COMPARABLE_MAX_RATIO:
                code = classify_offer(offer)
        if code:
            offer['price_not_comparable'] = code
            tagged += 1
        else:
            offer.pop('price_not_comparable', None)
    return tagged
