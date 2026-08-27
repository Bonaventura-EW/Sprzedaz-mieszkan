"""Testy ekstrakcji ulic i doprecyzowania lokalizacji (bez live Nominatim)."""

from location_refiner import (
    extract_street_candidates, nominative_variants, refine_offer_location,
    district_consistent, StreetGeocoder, city_key, city_consistent,
    offer_city_key, otodom_coords_plausible,
)


class ReverseGeocoder:
    """Atrapa geokodera do walidacji dzielnicy — reverse zwraca zadany adres."""
    def __init__(self, addr):
        self._addr = addr
    def reverse_address(self, lat, lon):
        return self._addr


def test_district_consistent_rejects_wrong_district():
    # pinezka w Lublinie, ale reverse pokazuje inną dzielnicę niż podana
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 51.1968, 'lon': 22.5428}, 'coords_precision': 'street',
        'district': 'Sławin'}}
    geo = ReverseGeocoder({'road': 'Zalewskiego', 'district': 'Za Cukrownią', 'city': 'Lublin'})
    assert district_consistent(offer, geo) is False
    assert offer['location'].get('district_mismatch') is True


def test_district_consistent_accepts_matching_district():
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 51.28, 'lon': 22.55}, 'coords_precision': 'street',
        'district': 'Sławin'}}
    geo = ReverseGeocoder({'road': 'X', 'district': 'Sławin', 'city': 'Lublin'})
    assert district_consistent(offer, geo) is True


def test_district_consistent_lenient_without_district():
    # OLX bez dzielnicy — nie ma czym walidować, zostawiamy pinezkę
    offer = {'source': 'olx', 'location': {
        'coords': {'lat': 51.24, 'lon': 22.55}, 'coords_precision': 'street',
        'district': None}}
    geo = ReverseGeocoder({'road': 'X', 'district': 'Rury', 'city': 'Lublin'})
    assert district_consistent(offer, geo) is True


def test_district_consistent_lenient_when_reverse_unavailable():
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 51.24, 'lon': 22.55}, 'coords_precision': 'street',
        'district': 'Rury'}}
    assert district_consistent(offer, ReverseGeocoder(None)) is True


def test_city_key_normalizes_spelling_and_inflection():
    assert city_key('Lublin') == 'lublin'
    assert city_key('Lublinie') == 'lublin'
    assert city_key('Świdnik') == 'swidnik'
    assert city_key('swidnik') == 'swidnik'     # bez ogonków
    assert city_key('Świdniku') == 'swidnik'    # miejscownik
    assert city_key('Warszawa') is None         # poza obszarem
    assert city_key('Mełgiew') is None          # sąsiednia gmina, ale nie nasza
    assert city_key(None) is None


def test_city_consistent_rules():
    assert city_consistent('Lublin', 'Lublin') is True
    assert city_consistent('Świdnik', 'Świdnik') is True
    assert city_consistent('Lublin', 'Świdnik') is False   # pinezka w złym mieście
    assert city_consistent(None, 'Warszawa') is False      # poza obszarem
    assert city_consistent('Lublin', None) is True         # brak reverse — leniwie
    assert city_consistent(None, 'Świdnik') is True        # ogłoszenie bez miasta


def test_offer_city_key_falls_back_to_base_city():
    assert offer_city_key({'location': {'city': 'Świdnik'}}) == 'swidnik'
    assert offer_city_key({'location': {'city': None}}) == 'lublin'
    assert offer_city_key({}) == 'lublin'


def test_district_consistent_accepts_pin_in_swidnik():
    # oferta ze Świdnika z pinezką w Świdniku — przed rozszerzeniem obszaru
    # wypadała jako „poza Lublinem"
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 51.2206, 'lon': 22.6961}, 'coords_precision': 'street',
        'city': 'Świdnik', 'district': None}}
    geo = ReverseGeocoder({'road': 'Kard. Wyszyńskiego', 'district': None, 'city': 'Świdnik'})
    assert district_consistent(offer, geo) is True


def test_district_consistent_rejects_lublin_offer_pinned_in_swidnik():
    # ogłoszenie mówi Lublin, a pinezka stoi w Świdniku → pinezka błędna
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 51.2206, 'lon': 22.6961}, 'coords_precision': 'street',
        'city': 'Lublin', 'district': 'Sławin'}}
    geo = ReverseGeocoder({'road': 'X', 'district': None, 'city': 'Świdnik'})
    assert district_consistent(offer, geo) is False


def test_district_consistent_skips_reverse_without_district():
    # Oferta bez dzielnicy (cały OLX) nie może zjadać budżetu MAX_REVERSE_GEOCODES —
    # pinezkę 'street' postawił nasz geokoder, związany bboxem i nazwą miasta.
    class CountingReverse:
        def __init__(self):
            self.calls = 0
        def reverse_address(self, lat, lon):
            self.calls += 1
            return {'road': 'X', 'district': 'Rury', 'city': 'Lublin'}

    offer = {'source': 'olx', 'location': {
        'coords': {'lat': 51.24, 'lon': 22.55}, 'coords_precision': 'street',
        'city': 'Lublin', 'district': None}}
    geo = CountingReverse()
    assert district_consistent(offer, geo) is True
    assert geo.calls == 0


def test_otodom_coords_rejects_neighbouring_municipality():
    # Mełgiew sąsiaduje ze Świdnikiem, ale jest poza obszarem zbierania.
    # Współrzędne 'approx' pochodzą z Otodom, więc tu reverse decyduje.
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 51.2206, 'lon': 22.6961}, 'coords_precision': 'approx',
        'city': 'Świdnik', 'district': None}}
    geo = ReverseGeocoder({'road': 'X', 'district': None, 'city': 'Mełgiew'})
    assert otodom_coords_plausible(offer, geo) is False


def test_otodom_coords_accepts_swidnik():
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 51.2206, 'lon': 22.6961}, 'coords_precision': 'approx',
        'city': 'Świdnik', 'district': None}}
    geo = ReverseGeocoder({'road': 'X', 'district': None, 'city': 'Świdnik'})
    assert otodom_coords_plausible(offer, geo) is True


def test_refine_asks_nominatim_about_offer_city():
    offer = {
        'title': 'Mieszkanie ul. Krężnickiej',
        'description': '',
        'location': {'coords': None, 'coords_precision': None,
                     'street': None, 'city': 'Świdnik'},
    }
    geo = FakeGeocoder()
    refine_offer_location(offer, geo)
    assert geo.last_city == 'swidnik'   # nie 'lublin'


def test_city_name_is_not_a_street():
    assert extract_street_candidates('Mieszkanie przy ul. Świdniku') == []


def test_district_consistent_rejects_outside_lublin():
    offer = {'source': 'otodom', 'location': {
        'coords': {'lat': 52.23, 'lon': 21.01}, 'coords_precision': 'street',
        'district': 'Rury'}}
    geo = ReverseGeocoder({'road': 'X', 'district': 'Śródmieście', 'city': 'Warszawa'})
    assert district_consistent(offer, geo) is False


def test_extract_street_basic():
    assert extract_street_candidates(
        "Mieszkanie 2 pok. Lublin, ul. Krężnicka") == ['Krężnicka']
    assert extract_street_candidates(
        "Kawalerka przy ul. Wyżynnej w Lublinie") == ['Wyżynnej']
    assert extract_street_candidates(
        "Mieszkanie przy alei Kraśnickiej, blisko centrum") == ['Kraśnickiej']


def test_extract_street_no_dot_abbrev():
    # sprzedający często piszą "ul"/"al" bez kropki
    assert extract_street_candidates(
        "Sprzedam mieszkanie 3 pok. na Czechowie, ul Lipińskiego Lublin") == ['Lipińskiego']
    assert extract_street_candidates("Mieszkanie al Kraśnicka, blisko centrum") == ['Kraśnicka']
    # "ul" wewnątrz słowa nie może być złapane
    assert extract_street_candidates("Komfortowa ulica Makowa w okolicy") == ['Makowa']


def test_extract_street_capital_prefix():
    # wielkie „Al."/„Ul." (częste na OLX) też muszą być łapane
    assert extract_street_candidates("BEZPOŚREDNIO: 2 pokoje, Al. Racławickie 22 | Centrum") == ['Racławickie']
    assert extract_street_candidates("Mieszkanie, Ul. Krakowska, parter") == ['Krakowska']


def test_extract_street_strips_building_number():
    assert extract_street_candidates("Mieszkanie ul. Wrońska1B, Bronowice") == ['Wrońska']
    assert extract_street_candidates("apartament ul. Nałęczowska 18a") == ['Nałęczowska']
    assert extract_street_candidates("ul. Zalewskiego 9, nowe") == ['Zalewskiego']


def test_extract_street_cuts_at_sentence_period():
    # kropka po pełnym słowie kończy nazwę (nie zabiera słowa z następnego zdania)
    assert extract_street_candidates("Czuby, ul. Fantastyczna. Zielone okolice") == ['Fantastyczna']
    assert extract_street_candidates("ul. Szafirowa. Bez prowizji") == ['Szafirowa']
    # skrót/inicjał z kropką NIE kończy nazwy
    assert extract_street_candidates("przy ul. Gen. Urbanowicza, park") == ['Gen. Urbanowicza']


def test_nominative_variants_multiple():
    # generujemy wiele wariantów — geokoder weźmie trafiony
    assert 'Pawia' in nominative_variants('Pawiej')
    assert 'Wschodnia' in nominative_variants('Wschodniej')
    assert 'Nadbystrzycka' in nominative_variants('Nadbystrzyckiej')


def test_extract_street_cuts_garbage():
    assert extract_street_candidates(
        "Mieszkanie 50m2 ul. Kosynierów. Dzielnica:Ponikwoda") == ['Kosynierów']
    assert extract_street_candidates("ulica Makowa. Oferta bez prowizji") == ['Makowa']


def test_extract_street_multiword():
    assert extract_street_candidates(
        "przy ul. Gen. Urbanowicza, blisko parku") == ['Gen. Urbanowicza']


def test_extract_street_none():
    assert extract_street_candidates("Mieszkanie bez ulicy w tekście") == []
    assert extract_street_candidates("") == []
    assert extract_street_candidates(None) == []


def test_nominative_variants():
    assert 'Krężnicka' in nominative_variants('Krężnickiej')
    assert 'Wyżynna' in nominative_variants('Wyżynnej')
    assert 'Zorza' in nominative_variants('Zorzy')
    assert nominative_variants('Makowa') == ['Makowa']  # już mianownik


class FakeGeocoder:
    """Atrapa geokodera — zwraca punkt dla znanych ulic, None dla reszty.

    Zapamiętuje miasto ostatniego zapytania, żeby testy mogły sprawdzić, że
    refiner pyta o miasto oferty, a nie zawsze o Lublin.
    """
    KNOWN = {'krężnicka': {'lat': 51.19, 'lon': 22.52, 'name': 'Krężnicka'}}

    def __init__(self):
        self.last_city = None

    def geocode_street(self, street, city=None):
        self.last_city = city
        for variant in nominative_variants(street):
            hit = self.KNOWN.get(variant.lower())
            if hit:
                return hit
        return None


def test_refine_sets_coords_from_street_when_missing():
    # OLX: brak coords (centroid miasta odrzucony) → ulica z tytułu daje pinezkę
    offer = {
        'title': 'Mieszkanie 2 pok. Lublin, ul. Krężnickiej',
        'description': '',
        'location': {'coords': None, 'coords_precision': None, 'street': None},
    }
    assert refine_offer_location(offer, FakeGeocoder()) is True
    assert offer['location']['coords_precision'] == 'street'
    assert offer['location']['coords'] == {'lat': 51.19, 'lon': 22.52}
    assert offer['location']['street'] == 'ul. Krężnicka'


def test_refine_upgrades_approx():
    offer = {
        'title': 'Mieszkanie ul. Krężnickiej',
        'description': '',
        'location': {'coords': {'lat': 51.25, 'lon': 22.57},
                     'coords_precision': 'approx', 'street': None},
    }
    assert refine_offer_location(offer, FakeGeocoder()) is True
    assert offer['location']['coords_precision'] == 'street'


def test_refine_keeps_exact_untouched():
    offer = {
        'title': 'Mieszkanie ul. Krężnicka',
        'description': '',
        'location': {'coords': {'lat': 51.28, 'lon': 22.53},
                     'coords_precision': 'exact', 'street': 'ul. Poligonowa'},
    }
    assert refine_offer_location(offer, FakeGeocoder()) is False
    assert offer['location']['coords'] == {'lat': 51.28, 'lon': 22.53}


def test_refine_no_street_found():
    offer = {
        'title': 'Mieszkanie przy ul. Nieistniejącej',
        'description': '',
        'location': {'coords': None, 'coords_precision': None, 'street': None},
    }
    assert refine_offer_location(offer, FakeGeocoder()) is False
    assert offer['location']['coords'] is None


def test_geocoder_negative_cache(tmp_path):
    g = StreetGeocoder(cache_file=str(tmp_path / 'cache.json'))
    g.cache['nieistniejąca'] = {'result': None, 'ts': 9e12}  # świeży negatyw
    assert g.geocode_street('Nieistniejąca') is None
    assert g.live_requests == 0  # nie strzelał do Nominatim


def test_stop_words_block_city_as_street():
    assert extract_street_candidates("Mieszkanie przy ul. Lublinie atrakcyjne") == []
    assert extract_street_candidates("ulica Lublin bez sensu") == []
