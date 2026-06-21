"""Stabilne identyfikatory ofert.

OLX zmienia slug w URL gdy sprzedawca edytuje tytuł ogłoszenia — stabilnym
identyfikatorem jest fragment `CID3-IDxxxx` (konwencja z rodziny sonarów).
Otodom ma stabilne, numeryczne `id` w danych __NEXT_DATA__, więc tam problem
nie występuje.

Identyfikatory w bazie mają prefiks źródła: `olx:CID3-IDxxxx` / `otodom:12345678`.
"""

import re

_CID_RE = re.compile(r'(CID3-ID[A-Za-z0-9]+)')


def extract_cid(s: str) -> str:
    """Wyciąga stabilny identyfikator CID3-IDxxxx z URL lub slugu OLX.

    Fallback: zwraca cały string (lub '' dla None), gdy brak CID.
    """
    m = _CID_RE.search(s or '')
    return m.group(1) if m else (s or '')


def olx_offer_id(url: str) -> str:
    """ID bazodanowe oferty OLX: `olx:CID3-IDxxxx`."""
    return f"olx:{extract_cid(url)}"


def otodom_offer_id(numeric_id) -> str:
    """ID bazodanowe oferty Otodom: `otodom:12345678`."""
    return f"otodom:{numeric_id}"
