# SONAR SPRZEDAŻY 🛰️🏠

Automatyczny agent monitorujący oferty **sprzedaży mieszkań w Lublinie**
(źródła: **OLX** + **Otodom**) i zaznaczający je na mapie, z podziałem na
**rynek pierwotny i wtórny**. Kolejny z rodziny sonarów (obok
[SONAR-POKOJOWY](https://github.com/Bonaventura-EW/SONAR-POKOJOWY),
[SONAR-MIESZKANIOWY](https://github.com/Bonaventura-EW/SONAR-MIESZKANIOWY)
i [SONAR-DZIAŁKOWY](https://github.com/Bonaventura-EW/SONAR---DZIA-KOWY)).

**🌍 Strona:** <https://bonaventura-ew.github.io/Sprzedaz-mieszkan/>

> ⚙️ Jednorazowa konfiguracja po utworzeniu repo: **Settings → Pages →
> Source: GitHub Actions** — potem skaner publikuje stronę automatycznie.

## Zasada: pinezka tylko dla znanego adresu

Pinezka na mapie pojawia się **wyłącznie gdy w ogłoszeniu jest szczegółowy adres**:
- 📍 **pełna pinezka** — dokładny punkt wskazany na Otodom,
- ▢ **kwadrat** — ulica wykryta w tytule lub treści ogłoszenia (geokodowanie Nominatim).

Oferty bez konkretnego adresu (np. OLX podaje tylko centroid miasta) trafiają do
listy **„bez lokalizacji GPS"** pod mapą — nie udajemy, że wiemy gdzie są.

## Jak działa

- **GitHub Actions** uruchamia skan 2×/dzień (`.github/workflows/scanner.yml`)
- **GitHub Pages** serwuje statyczny frontend z katalogu `docs/`
- **Źródłem prawdy są pliki JSON** w `data/` (commitowane przez Actions)
- Bez serwera, bez bazy SQL

### Źródła danych

| Portal | Co dostajemy | Lokalizacja |
|--------|-------------|-------------|
| OLX (mieszkania na sprzedaż, Lublin) | cena, powierzchnia, cena/m², rynek, pokoje, piętro, opis | tylko ulica z tytułu/opisu (portal daje centroid miasta) |
| Otodom (mieszkania na sprzedaż, Lublin) | cena, powierzchnia, cena/m², rynek, pokoje, piętro, opis, ulica | **dokładna** ze strony szczegółów (dla nowych ofert) |

Oba portale osadzają dane w JSON (`__PRERENDERED_STATE__` / `__NEXT_DATA__`).
Rynek pierwotny/wtórny: OLX podaje go w listingu, Otodom na stronie szczegółów
(oraz `estate=INVESTMENT` = pierwotny).

## Funkcje mapy

- pinezki kolorowane wg **ceny za m²** (kwantyle: zielony = tanio, fioletowy = drogo)
  albo wg **rynku** (pierwotny / wtórny)
- filtry: źródło, rynek, liczba pokoi, cena, powierzchnia, czas, tylko nowe, tylko od właściciela
- historia cen (📉/📈) i reaktywacje ofert
- wykrywanie tego samego mieszkania na obu portalach (link „Druga oferta")
- podstrony: 📈 Analityka, 📐 Statystyki (pierwotny vs wtórny, ranking dzielnic, okazje cenowe), 📊 Monitoring, 📋 Oferty (cena w czasie), 🔄 Ruch (nowe/zniknięte)

## API (statyczne, GitHub Pages)

| Endpoint | Zawartość |
|----------|-----------|
| `api/status.json` | statystyki: liczba ofert, mediana ceny/m², podział wg źródła i rynku |
| `api/offers.json` | wszystkie aktywne oferty (po deduplikacji OLX↔Otodom) |
| `api/history.json` | historia ostatnich skanów |
| `api/health.json` | healthcheck (świeżość ostatniego skanu) |

Szczegóły: [docs/API.md](docs/API.md).

## Uruchomienie lokalne

```bash
pip install -r requirements.txt

cd src
python main.py            # pełny skan
python map_generator.py   # generuje docs/data.json
python api_generator.py   # generuje docs/api/*.json
python monitoring_generator.py

cd ../docs && python -m http.server 8000   # podgląd: http://localhost:8000
```

## Testy

```bash
pip install pytest
pytest
```
