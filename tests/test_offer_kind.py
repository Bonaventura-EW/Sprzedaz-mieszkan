"""Testy rozpoznawania ofert z ceną nieporównywalną (FIX 2026-09-06).

Klucz: sam tekst NIE wystarcza. „0% prowizji, możliwa zamiana" to zwykła
sprzedaż po zwykłej cenie — ukrycie jej byłoby gorsze niż problem, który
naprawiamy. Ofertę odsuwamy dopiero, gdy tekst I cena zgadzają się co do tego,
że to nie jest sprzedaż mieszkania.
"""

from offer_kind import (classify_offer, tag_non_comparable,
                        NON_COMPARABLE_MAX_RATIO, MIN_CITY_SAMPLE, label)


def _offer(title, ppm, city='Lublin', description='', active=True):
    return {'id': title[:12], 'title': title, 'description': description,
            'active': active, 'price_per_m2': ppm, 'location': {'city': city}}


def _market(n=MIN_CITY_SAMPLE, ppm=10000, city='Lublin'):
    """Tło rynkowe, żeby mediana miasta miała z czego powstać."""
    return [_offer(f'Zwykłe mieszkanie {i}', ppm, city) for i in range(n)]


# ── classify_offer: sam sygnał tekstowy ──────────────────────────────
def test_classify_recognizes_non_sale_wording():
    assert classify_offer(_offer('ZAMIENIĘ  mieszkanie', 9)) == 'zamiana'
    assert classify_offer(_offer('mieszkanie w systemie SIM (TBS) Lublin', 1121)) == 'tbs_sim'
    assert classify_offer(_offer('1/2 udziału w mieszkaniu 2-pokojowym', 4697)) == 'udzial'
    assert classify_offer(_offer('Lokal mieszkalny - druga licytacja publiczna', 5186)) == 'licytacja'
    assert classify_offer(_offer('Odstąpię najem mieszkania', 3128)) == 'cesja_najmu'


def test_classify_ignores_ordinary_sale():
    assert classify_offer(_offer('Słoneczne 2 pokoje z balkonem, LSM', 10500)) is None
    assert classify_offer(_offer('Kawalerka 28m2 | Pełna Własność | Do remontu', 4912)) is None


def test_classify_reads_description_only_for_unambiguous_phrases():
    # „pod wynajem" w opisie to NIE cesja najmu — inaczej wpadłaby setka ofert
    assert classify_offer(_offer('3 pokoje, Czechów', 10000,
                                 description='Idealne pod wynajem, blisko UMCS.')) is None
    assert classify_offer(_offer('3 pokoje, Czechów', 10000,
                                 description='Odstąpię najem, umowa do 2030.')) == 'cesja_najmu'
    # „udział w częściach wspólnych" to standardowa klauzula, nie sprzedaż udziału
    assert classify_offer(_offer('3 pokoje, Czechów', 10000,
                                 description='W cenie udział w częściach wspólnych.')) is None


# ── tag_non_comparable: dopiero DWA sygnały naraz ────────────────────
def test_tag_requires_both_signals():
    offers = _market() + [
        _offer('ZAMIENIĘ mieszkanie', 9),                       # tekst + cena → ukryta
        _offer('0% prowizji, możliwa zamiana lub raty', 13004),  # tekst, cena normalna
        _offer('2 Pokoje w Suterenie, Centrum', 3062),           # cena niska, ale to sprzedaż
    ]
    tagged = tag_non_comparable(offers)
    assert tagged == 1
    by_title = {o['title']: o for o in offers}
    assert by_title['ZAMIENIĘ mieszkanie']['price_not_comparable'] == 'zamiana'
    assert 'price_not_comparable' not in by_title['0% prowizji, możliwa zamiana lub raty']
    assert 'price_not_comparable' not in by_title['2 Pokoje w Suterenie, Centrum']


def test_tag_uses_per_city_median():
    """Świdnik jest tańszy — mediana Lublina uznałaby tamtejsze mieszkania za
    odstające (pkt 6b w CLAUDE.md)."""
    offers = _market(ppm=12000, city='Lublin') + _market(ppm=5000, city='Świdnik')
    swidnik_tbs = _offer('Mieszkanie TBS – Świdnik', 4800, city='Świdnik')
    offers.append(swidnik_tbs)
    tag_non_comparable(offers)
    # 4800 to niemal mediana Świdnika (5000) — nie odstaje, mimo słowa TBS
    assert 'price_not_comparable' not in swidnik_tbs

    swidnik_cheap_tbs = _offer('Inne TBS – Świdnik', 2000, city='Świdnik')
    offers.append(swidnik_cheap_tbs)
    tag_non_comparable(offers)
    assert swidnik_cheap_tbs['price_not_comparable'] == 'tbs_sim'


def test_tag_clears_flag_when_offer_no_longer_qualifies():
    offers = _market()
    o = _offer('Mieszkanie TBS – Lublin', 1000)
    offers.append(o)
    tag_non_comparable(offers)
    assert o['price_not_comparable'] == 'tbs_sim'
    # sprzedający poprawił cenę na rynkową → znacznik znika, oferta wraca na mapę
    o['price_per_m2'] = 9800
    tag_non_comparable(offers)
    assert 'price_not_comparable' not in o


def test_tag_skips_city_with_too_small_sample():
    """Mediana z garstki ofert jest zbyt chwiejna, żeby na niej wyrokować."""
    offers = [_offer(f'Mieszkanie {i}', 10000, city='Świdnik') for i in range(5)]
    offers.append(_offer('Mieszkanie TBS – Świdnik', 100, city='Świdnik'))
    assert tag_non_comparable(offers) == 0


def test_tag_ignores_inactive_offers():
    offers = _market()
    o = _offer('ZAMIENIĘ mieszkanie', 9, active=False)
    offers.append(o)
    assert tag_non_comparable(offers) == 0
    assert 'price_not_comparable' not in o


def test_threshold_is_a_fraction_of_median():
    assert 0 < NON_COMPARABLE_MAX_RATIO < 1


def test_label_is_human_readable():
    assert 'zamiana' in label('zamiana')
    assert label(None) is None
