"""Ścieżki do katalogów projektu, liczone względem lokalizacji tego pliku.

Konwencja przeniesiona z rodziny sonarów (SONAR-MIESZKANIOWY / SONAR-DZIAŁKOWY):
kotwiczymy ścieżki do __file__, dzięki czemu skrypty znajdują dane niezależnie
od bieżącego katalogu (np. odpalane z roota repo albo przez pytest).
"""

from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
DATA_DIR = ROOT_DIR / "data"
DOCS_DIR = ROOT_DIR / "docs"

OFFERS_JSON = str(DATA_DIR / "offers.json")
REMOVED_JSON = str(DATA_DIR / "removed_listings.json")
SCAN_HISTORY_JSON = str(DATA_DIR / "scan_history.json")

DOCS_DATA_JSON = str(DOCS_DIR / "data.json")
