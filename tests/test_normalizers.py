"""Testy normalizacji ofert OLX i Otodom do wspólnego schematu (mieszkania)."""

from olx_scraper import normalize_ad, strip_html, MARKET_MAP as OLX_MARKETS, _parse_floor
from otodom_scraper import normalize_item
from cid import extract_cid, olx_offer_id, otodom_offer_id


OLX_AD = {
    'url': 'https://www.olx.pl/d/oferta/mieszkanie-testowe-CID3-ID1abcDE.html?reason=x',
    'title': '2 pokojowe mieszkanie Czechów ',
    'isBusiness': False,
    'createdTime': '2026-06-01T10:00:00+02:00',
    'description': '<p>Ładne mieszkanie</p><p>blisko centrum</p>',
    'price': {'regularPrice': {'value': 480000, 'currencyCode': 'PLN'}},
    'map': {'lat': 51.2396, 'lon': 22.5526, 'radius': 6},  # centroid miasta
    'location': {'cityName': 'Lublin', 'cityNormalizedName': 'lublin', 'districtName': None},
    'photos': ['https://example.com/foto.jpg'],
    'params': [
        {'key': 'market', 'normalizedValue': 'secondary'},
        {'key': 'm', 'normalizedValue': '36.6'},
        {'key': 'price_per_m', 'normalizedValue': '13114.75'},
        {'key': 'rooms', 'normalizedValue': 'two'},
        {'key': 'floor_select', 'normalizedValue': 'floor_3'},
    ],
}

OTODOM_ITEM = {
    'id': 67500001,
    'slug': 'mieszkanie-2-pok-ID4BRnh',
    'title': 'Apartament 2 pokoje',
    'totalPrice': {'value': 598000},
    'pricePerSquareMeter': {'value': 12157},
    'areaInSquareMeters': 49.19,
    'roomsNumber': 'TWO',
    'floorNumber': 'SECOND',
    'estate': 'FLAT',
    'isPrivateOwner': False,
    'shortDescription': 'Mieszkanie przy Zemborzyckiej',
    'createdAtFirst': '2026-06-10T13:32:27Z',
    'images': [{'medium': 'https://example.com/m.jpg', 'large': 'https://example.com/l.jpg'}],
    'location': {
        'address': {'street': {'name': 'ul. Zemborzycka', 'number': ''},
                    'city': {'name': 'Lublin'}},
        'reverseGeocoding': {'locations': [
            {'name': 'Lublin', 'locationLevel': 'city_or_village'},
            {'name': 'Dziesiąta', 'locationLevel': 'district'},
        ]},
    },
}

OTODOM_INVESTMENT = dict(
    OTODOM_ITEM, id=67500002, slug='nowa-inwestycja-ID4xxxx',
    estate='INVESTMENT', roomsNumber=None, floorNumber=None,
)


def test_extract_cid():
    assert extract_cid(OLX_AD['url']) == 'CID3-ID1abcDE'
    assert extract_cid('brak-cid') == 'brak-cid'
    assert extract_cid(None) == ''


def test_olx_normalize():
    o = normalize_ad(OLX_AD)
    assert o['id'] == 'olx:CID3-ID1abcDE'
    assert o['source'] == 'olx'
    assert o['url'].endswith('.html')  # bez query params
    assert o['title'] == '2 pokojowe mieszkanie Czechów'
    assert o['price'] == 480000
    assert o['area_m2'] == 36.6
    assert o['price_per_m2'] == 13114.75
    assert o['market'] == 'wtorny'
    assert o['rooms'] == 2
    assert o['floor'] == '3'
    # OLX dla mieszkań daje centroid miasta — coords celowo puste
    assert o['location']['coords'] is None
    assert o['location']['coords_precision'] is None
    assert o['is_private_owner'] is True
    assert 'Ładne mieszkanie' in o['description']
    assert '<p>' not in o['description']


def test_olx_market_primary():
    ad = dict(OLX_AD)
    ad['params'] = [{'key': 'market', 'normalizedValue': 'primary'},
                    {'key': 'm', 'normalizedValue': '50'}]
    assert normalize_ad(ad)['market'] == 'pierwotny'


def test_olx_market_unknown_fallback():
    ad = dict(OLX_AD)
    ad['params'] = [{'key': 'm', 'normalizedValue': '50'}]
    assert normalize_ad(ad)['market'] == 'nieokreslony'


def test_olx_normalize_no_price():
    ad = dict(OLX_AD, price={})
    assert normalize_ad(ad) is None


def test_olx_per_m2_computed_when_missing():
    ad = dict(OLX_AD)
    ad['params'] = [{'key': 'm', 'normalizedValue': '50'}]
    o = normalize_ad(ad)
    assert o['price_per_m2'] == round(480000 / 50, 2)


def test_olx_floor_parser():
    assert _parse_floor('floor_0') == 'parter'
    assert _parse_floor('floor_7') == '7'
    assert _parse_floor('floor_higher_10') == '>10'
    assert _parse_floor('garret') == 'poddasze'
    assert _parse_floor(None) is None


def test_otodom_normalize():
    o = normalize_item(OTODOM_ITEM)
    assert o['id'] == 'otodom:67500001'
    assert o['source'] == 'otodom'
    assert o['url'] == 'https://www.otodom.pl/pl/oferta/mieszkanie-2-pok-ID4BRnh'
    assert o['price'] == 598000
    assert o['area_m2'] == 49.19
    assert o['price_per_m2'] == 12157.0
    assert o['rooms'] == 2
    assert o['floor'] == '2'
    # rynek dla zwykłego mieszkania znamy dopiero ze strony szczegółów
    assert o['market'] == 'nieokreslony'
    assert o['location']['street'] == 'ul. Zemborzycka'
    assert o['location']['district'] == 'Dziesiąta'
    assert o['location']['coords'] is None  # coords dopiero ze strony szczegółów
    assert o['is_private_owner'] is False
    assert o['image'] == 'https://example.com/m.jpg'


def test_otodom_investment_is_primary():
    o = normalize_item(OTODOM_INVESTMENT)
    assert o['market'] == 'pierwotny'


def test_otodom_normalize_hidden_price():
    item = dict(OTODOM_ITEM, totalPrice=None)
    assert normalize_item(item) is None


def test_strip_html():
    assert strip_html('<p>a</p><p>b</p>') == 'a\nb'
    assert strip_html('') == ''
    assert strip_html(None) == ''


def test_market_map_contents():
    assert OLX_MARKETS['primary'] == 'pierwotny'
    assert OLX_MARKETS['secondary'] == 'wtorny'


def test_offer_id_helpers():
    assert olx_offer_id('x-CID3-ID9z.html') == 'olx:CID3-ID9z'
    assert otodom_offer_id(123) == 'otodom:123'
