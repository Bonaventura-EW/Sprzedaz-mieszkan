/* SONAR SPRZEDAŻY MIESZKAŃ — frontend mapy (Leaflet).
 * Czyta data.json wygenerowany przez src/map_generator.py.
 *
 * Kształty pinezek:
 *  - dokładny adres (coords_precision == 'exact')  → pinezka-kropla 40×50
 *  - ulica z ogłoszenia (coords_precision == 'street') → kwadrat 34×34 (przerywana ramka)
 *  - nieaktywne → × (białe koło w pinezce / × na kwadracie)
 *  - badge N (nowa) i 💲↓/↑ (zmiana ceny)
 *
 * Zasada projektu: na mapie są TYLKO oferty ze znanym adresem (exact lub ulica).
 * Oferty bez konkretnej lokalizacji trafiają do sekcji „bez GPS" pod mapą.
 */

const LUBLIN_CENTER = [51.2465, 22.5684];
const NEW_OFFER_DAYS = 7;
// kolory kwantyli ceny za m²: tani (zielony) → drogi (fioletowy), 10 stopni (decyle)
const QUANTILE_COLORS = ['#15803d', '#4ca11e', '#84cc16', '#c4d62b', '#eab308',
                         '#f59e0b', '#f97316', '#ef4444', '#db2777', '#7c3aed'];
// stałe kolory rynku — wspólne z wykresem w analytics.html
const MARKET_COLORS = {
    'pierwotny': '#f59e0b',
    'wtorny': '#7c3aed',
    'nieokreslony': '#94a3b8',
};
const MARKET_LABELS = {
    'pierwotny': 'rynek pierwotny',
    'wtorny': 'rynek wtórny',
    'nieokreslony': 'rynek nieokreślony',
};

let map, markersLayer;
const _iconCache = new Map();  // memoizacja L.divIcon wg wyglądu (patrz makeIcon)
let markerById = {};  // id oferty -> L.marker (do fokusowania z linku #offer=…)
let allOffers = [];
let quantiles = [];
let marketFilterState = {};   // market -> bool
let roomsFilterState = {};     // bucket pokoi -> bool
let quantileBucketState = {};  // index kubełka ceny/m² -> bool (legenda z checkboxami)

init();

async function init() {
    map = L.map('map', { preferCanvas: true }).setView(LUBLIN_CENTER, 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap', maxZoom: 19,
        updateWhenZooming: false, keepBuffer: 2,
    }).addTo(map);
    markersLayer = L.layerGroup().addTo(map);

    let data;
    try {
        const resp = await fetch('data.json?t=' + Date.now());
        data = await resp.json();
    } catch (e) {
        document.getElementById('visible-count').textContent = 'błąd danych';
        return;
    }

    allOffers = data.offers || [];
    quantiles = (data.stats && data.stats.per_m2_quantiles || []).filter(q => q != null);

    if (data.last_scan) {
        document.getElementById('last-scan').textContent =
            new Date(data.last_scan).toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' });
    }
    const med = data.stats && data.stats.median_price_per_m2;
    document.getElementById('median-per-m2').textContent = med ? fmtPrice(med) + '/m²' : '—';

    buildMarketFilters();
    buildRoomsFilters();
    buildLegend();
    bindFilterEvents();
    render();

    // fokus oferty z linku (#offer=<id>) — pinezka z podstrony „🔄 Ruch"
    focusOfferFromHash();
    window.addEventListener('hashchange', focusOfferFromHash);
}

// warstwa (checkbox), do której należy oferta — wspólne z passesFilters
function layerIdFor(o) {
    const approx = isApprox(o);
    return o.active
        ? (approx ? 'layer-active-approx' : 'layer-active')
        : (approx ? 'layer-inactive-approx' : 'layer-inactive');
}

function focusOfferFromHash() {
    const m = location.hash.match(/offer=([^&]+)/);
    if (!m) return;
    const id = decodeURIComponent(m[1]);
    const o = allOffers.find(x => x.id === id);
    if (!o) return;

    const layer = document.getElementById(layerIdFor(o));
    if (layer) layer.checked = true;
    const sc = document.getElementById('src-' + o.source);
    if (sc) sc.checked = true;
    const market = o.market || 'nieokreslony';
    marketFilterState[market] = true;
    const mcb = document.querySelector(`#market-filters input[data-market="${market}"]`);
    if (mcb) mcb.checked = true;
    Object.keys(roomsFilterState).forEach(k => roomsFilterState[k] = true);
    document.querySelectorAll('#rooms-filters input').forEach(cb => cb.checked = true);
    if (colorMode() === 'price') quantileBucketState[quantileIndex(o)] = true;
    document.getElementById('time-filter').value = 'all';
    render();

    if (o.coords) {
        map.setView([o.coords.lat, o.coords.lon], 16, { animate: true });
        const mk = markerById[o.id];
        if (mk) setTimeout(() => mk.openPopup(), 250);
    }
    // oferty bez GPS nie są na mapie — znajdziesz je w zakładce 🐛 Debug
}

function fmtPrice(v) {
    if (v == null) return '—';
    return Math.round(v).toLocaleString('pl-PL') + ' zł';
}

function fmtArea(v) {
    if (v == null) return '—';
    return v.toLocaleString('pl-PL') + ' m²';
}

function fmtRooms(v) {
    if (v == null) return '—';
    return v + (v === 1 ? ' pokój' : (v >= 2 && v <= 4 ? ' pokoje' : ' pokoi'));
}

function fmtFloor(v) {
    if (v == null) return null;
    return v === 'parter' || v === 'suterena' || v === 'poddasze' ? v : 'piętro ' + v;
}

function isNew(offer) {
    if (!offer.first_seen) return false;
    return (Date.now() - new Date(offer.first_seen).getTime()) < NEW_OFFER_DAYS * 86400000;
}

function isApprox(offer) {
    // jedyne precyzje na mapie to 'exact' (pinezka) i 'street' (kwadrat)
    return offer.coords_precision !== 'exact';
}

function roomsBucket(offer) {
    if (offer.rooms == null) return 'b/d';
    if (offer.rooms >= 5) return '5+';
    return String(offer.rooms);
}

function colorMode() {
    const radio = document.querySelector('input[name="color-mode"]:checked');
    return radio ? radio.value : 'price';
}

function colorFor(offer) {
    if (colorMode() === 'market') {
        return MARKET_COLORS[offer.market || 'nieokreslony'] || '#94a3b8';
    }
    return QUANTILE_COLORS[quantileIndex(offer)];
}

// indeks kubełka ceny/m² (0..QUANTILE_COLORS.length-1) — wspólny dla koloru,
// legendy i filtra; brak ceny/kwantyli → kubełek środkowy (2)
function quantileIndex(offer) {
    const v = offer.price_per_m2;
    if (v == null || !quantiles.length) return 2;
    let i = 0;
    while (i < quantiles.length && v > quantiles[i]) i++;
    return i;
}

function buildMarketFilters() {
    const markets = {};
    allOffers.forEach(o => { const m = o.market || 'nieokreslony'; markets[m] = (markets[m] || 0) + 1; });
    const container = document.getElementById('market-filters');
    // stała kolejność: pierwotny, wtórny, nieokreślony
    ['pierwotny', 'wtorny', 'nieokreslony'].forEach(m => {
        if (!(m in markets)) return;
        marketFilterState[m] = true;
        const color = MARKET_COLORS[m];
        const label = document.createElement('label');
        label.innerHTML = `<input type="checkbox" checked data-market="${m}"> ` +
            `<span class="type-swatch" style="background:${color}"></span> ` +
            `${MARKET_LABELS[m]} <span class="count">(${markets[m]})</span>`;
        label.querySelector('input').addEventListener('change', e => {
            marketFilterState[m] = e.target.checked;
            render();
        });
        container.appendChild(label);
    });
}

function buildRoomsFilters() {
    const buckets = {};
    allOffers.forEach(o => { const b = roomsBucket(o); buckets[b] = (buckets[b] || 0) + 1; });
    const order = ['1', '2', '3', '4', '5+', 'b/d'];
    const container = document.getElementById('rooms-filters');
    order.forEach(b => {
        if (!(b in buckets)) return;
        roomsFilterState[b] = true;
        const label = document.createElement('label');
        label.style.cssText = 'display:inline-block;margin-right:10px';
        const txt = b === 'b/d' ? 'b/d' : (b === '5+' ? '5+ pok.' : b + ' pok.');
        label.innerHTML = `<input type="checkbox" checked data-rooms="${b}"> ${txt} <span class="count">(${buckets[b]})</span>`;
        label.querySelector('input').addEventListener('change', e => {
            roomsFilterState[b] = e.target.checked;
            render();
        });
        container.appendChild(label);
    });
}

function buildLegend() {
    const container = document.getElementById('legend');
    container.innerHTML = '';
    if (colorMode() === 'market') {
        const present = new Set(allOffers.map(o => o.market || 'nieokreslony'));
        ['pierwotny', 'wtorny', 'nieokreslony'].forEach(m => {
            if (!present.has(m)) return;
            const row = document.createElement('div');
            row.className = 'legend-row';
            row.innerHTML = `<span class="legend-dot" style="background:${MARKET_COLORS[m]}"></span> ${MARKET_LABELS[m]}`;
            container.appendChild(row);
        });
        return;
    }
    if (!quantiles.length) { container.textContent = 'brak danych'; return; }
    const bounds = [null, ...quantiles, null];
    for (let i = 0; i < QUANTILE_COLORS.length; i++) {
        const lo = bounds[i], hi = bounds[i + 1];
        let text;
        if (lo == null) text = `do ${fmtPrice(hi)}/m²`;
        else if (hi == null) text = `powyżej ${fmtPrice(lo)}/m²`;
        else text = `${fmtPrice(lo)} – ${fmtPrice(hi)}/m²`;
        const row = document.createElement('label');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:12px;padding:2px 0;cursor:pointer';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = quantileBucketState[i] !== false;
        cb.style.cssText = 'width:15px;height:15px;margin:0;flex:0 0 auto;accent-color:#7c3aed';
        cb.addEventListener('change', () => { quantileBucketState[i] = cb.checked; render(); });
        const dot = document.createElement('span');
        dot.style.cssText = `width:14px;height:14px;border-radius:50%;flex:0 0 auto;border:1px solid rgba(0,0,0,0.25);background:${QUANTILE_COLORS[i]}`;
        const lbl = document.createElement('span');
        lbl.textContent = text;
        row.append(cb, dot, lbl);
        container.appendChild(row);
    }
}

function bindFilterEvents() {
    ['src-olx', 'src-otodom', 'layer-active', 'layer-active-approx',
     'layer-inactive', 'layer-inactive-approx', 'only-new', 'only-private']
        .forEach(id => document.getElementById(id).addEventListener('change', render));
    document.getElementById('time-filter').addEventListener('change', render);
    document.querySelectorAll('input[name="color-mode"]').forEach(r =>
        r.addEventListener('change', () => { _iconCache.clear(); buildLegend(); render(); }));
    ['price-min', 'price-max', 'area-min', 'area-max']
        .forEach(id => document.getElementById(id).addEventListener('input', debounce(render, 300)));
}

function debounce(fn, ms) {
    let t;
    return () => { clearTimeout(t); t = setTimeout(fn, ms); };
}

function passesFilters(o) {
    const srcCheckbox = document.getElementById('src-' + o.source);
    if (srcCheckbox && !srcCheckbox.checked) return false;

    // warstwy: aktywne/nieaktywne × dokładny adres / ulica
    const approx = isApprox(o);
    const layerId = o.active
        ? (approx ? 'layer-active-approx' : 'layer-active')
        : (approx ? 'layer-inactive-approx' : 'layer-inactive');
    if (!document.getElementById(layerId).checked) return false;

    // 📅 filtr "z ostatnich X dni" (po first_seen)
    const timeDays = document.getElementById('time-filter').value;
    if (timeDays !== 'all') {
        const cutoff = Date.now() - parseInt(timeDays, 10) * 86400000;
        if (!o.first_seen || new Date(o.first_seen).getTime() < cutoff) return false;
    }

    if (document.getElementById('only-new').checked && !isNew(o)) return false;
    if (document.getElementById('only-private').checked && !o.is_private_owner) return false;

    if (!marketFilterState[o.market || 'nieokreslony']) return false;
    if (roomsFilterState[roomsBucket(o)] === false) return false;

    // filtr zakresów ceny/m² (checkboxy w legendzie; tylko w trybie koloru ceny)
    if (colorMode() === 'price' && quantileBucketState[quantileIndex(o)] === false) return false;

    const pMin = parseFloat(document.getElementById('price-min').value);
    const pMax = parseFloat(document.getElementById('price-max').value);
    if (!isNaN(pMin) && (o.price == null || o.price < pMin)) return false;
    if (!isNaN(pMax) && (o.price == null || o.price > pMax)) return false;

    const aMin = parseFloat(document.getElementById('area-min').value);
    const aMax = parseFloat(document.getElementById('area-max').value);
    if (!isNaN(aMin) && (o.area_m2 == null || o.area_m2 < aMin)) return false;
    if (!isNaN(aMax) && (o.area_m2 == null || o.area_m2 > aMax)) return false;

    return true;
}

/* ===== Ikony markerów ===== */

function badgesHtml(o) {
    const hasPriceChange = o.previous_price && o.price_trend;
    let html = '';
    if (hasPriceChange) {
        const down = o.price_trend === 'down';
        html += `<div style="position:absolute;top:-8px;right:-8px;background:${down ? '#28a745' : '#dc3545'};color:white;border-radius:10px;min-width:28px;height:20px;font-size:11px;font-weight:bold;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 4px rgba(0,0,0,0.3);padding:0 4px;border:2px solid white;">💲${down ? '↓' : '↑'}</div>`;
    } else if (isNew(o)) {
        html += `<div style="position:absolute;top:-5px;right:-5px;background:#ff0000;color:white;border-radius:50%;width:16px;height:16px;font-size:10px;font-weight:bold;display:flex;align-items:center;justify-content:center;box-shadow:0 1px 3px rgba(0,0,0,0.3);">N</div>`;
    }
    return html;
}

function badgeType(o) {
    if (o.previous_price && o.price_trend) return o.price_trend === 'down' ? 'd' : 'u';
    if (isNew(o)) return 'n';
    return '';
}

function makeIcon(o) {
    const color = colorFor(o);
    const fresh = isNew(o);
    const approx = isApprox(o);
    const key = (approx ? 's' : 'p') + color + (o.active ? 1 : 0)
        + (fresh ? 1 : 0) + badgeType(o);
    const cached = _iconCache.get(key);
    if (cached) return cached;

    const stroke = fresh ? '#ff0000' : 'white';
    const strokeW = fresh ? 3 : 2;

    let icon;
    if (approx) {
        // KWADRAT 34×34 z przerywaną obwódką (lokalizacja do ulicy)
        const s = 34;
        const cross = !o.active
            ? `<text x="17" y="17" text-anchor="middle" dominant-baseline="central" font-size="22" font-weight="700" fill="white" font-family="-apple-system, sans-serif" style="paint-order: stroke; stroke: rgba(0,0,0,0.5); stroke-width: 2px;">×</text>`
            : '';
        icon = L.divIcon({
            className: 'square-marker',
            html: `<div style="position:relative;width:${s}px;height:${s}px;">
                <svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">
                    <rect x="3" y="3" width="${s - 6}" height="${s - 6}"
                          fill="${color}" fill-opacity="0.85"
                          stroke="${stroke}"
                          stroke-width="3" stroke-dasharray="4 3"/>
                    ${cross}
                </svg>
                ${badgesHtml(o)}
            </div>`,
            iconSize: [s, s],
            iconAnchor: [s / 2, s / 2],
            popupAnchor: [0, -s / 2],
        });
    } else {
        // PINEZKA-KROPLA 40×50 (dokładny adres)
        const inner = !o.active
            ? `<circle cx="20" cy="18" r="9" fill="white"/><text x="20" y="18" text-anchor="middle" dominant-baseline="central" font-size="16" font-weight="700" fill="#1f2937" font-family="-apple-system, sans-serif">×</text>`
            : `<circle cx="20" cy="18" r="7" fill="white" fill-opacity="0.9"/>`;
        icon = L.divIcon({
            className: 'pin-marker',
            html: `<div style="position:relative;width:40px;height:50px;">
                <svg width="40" height="50" viewBox="0 0 40 50">
                    <path d="M20 0 C9 0 0 9 0 20 C0 35 20 50 20 50 C20 50 40 35 40 20 C40 9 31 0 20 0 Z"
                          fill="${color}"
                          stroke="${stroke}"
                          stroke-width="${strokeW}"/>
                    ${inner}
                </svg>
                ${badgesHtml(o)}
            </div>`,
            iconSize: [40, 50],
            iconAnchor: [20, 50],
            popupAnchor: [0, -50],
        });
    }
    _iconCache.set(key, icon);
    return icon;
}

function popupHtml(o) {
    const newBadge = isNew(o) ? ' <span class="badge-new">NOWA</span>' : '';
    const market = o.market || 'nieokreslony';
    const marketBadge = `<span class="badge-market market-${market}">${MARKET_LABELS[market]}</span>`;
    const trend = o.price_trend === 'down'
        ? ` <span class="trend-down">↓ było ${fmtPrice(o.previous_price)}</span>`
        : o.price_trend === 'up'
            ? ` <span class="trend-up">↑ było ${fmtPrice(o.previous_price)}</span>` : '';
    const img = o.image ? `<img class="popup-img" src="${o.image}" loading="lazy" alt="">` : '';
    const where = [o.street, o.district].filter(Boolean).join(', ');
    const precision = o.coords_precision === 'exact'
        ? ' (dokładny adres)'
        : o.coords_precision === 'street' ? ' (lokalizacja: ulica)'
        : o.coords_precision === 'approx' ? ' (przybliżona — Otodom)' : '';
    const floor = fmtFloor(o.floor);
    const roomsFloor = [o.rooms ? fmtRooms(o.rooms) : null, floor].filter(Boolean).join(' • ');
    const alsoAt = o.also_at
        ? `<a class="secondary" href="${o.also_at}" target="_blank" rel="noopener">Druga oferta ↗</a>` : '';
    const status = o.active ? '' : '<div style="color:#dc2626;font-weight:700;font-size:12px;">⏸ OFERTA NIEAKTYWNA</div>';
    return `
        ${img}${status}
        <div class="popup-title">${escapeHtml(o.title)}${newBadge}</div>
        <div class="popup-price">${fmtPrice(o.price)}${trend}</div>
        <div class="popup-meta">
            📐 ${fmtArea(o.area_m2)} • ${o.price_per_m2 ? fmtPrice(o.price_per_m2) + '/m²' : '—'}<br>
            ${roomsFloor ? '🚪 ' + escapeHtml(roomsFloor) + '<br>' : ''}
            🏷️ ${marketBadge} • ${o.source.toUpperCase()}${o.is_private_owner ? ' • od właściciela' : ''}<br>
            ${where ? '📍 ' + escapeHtml(where) + precision + '<br>' : (precision ? '📍 ' + precision.trim() + '<br>' : '')}
            🗓️ w bazie od ${o.first_seen ? new Date(o.first_seen).toLocaleDateString('pl-PL') : '—'} (${o.days_active} dni)
        </div>
        <div class="popup-desc">${escapeHtml(o.description || '')}</div>
        <div class="popup-links">
            <a href="${o.url}" target="_blank" rel="noopener">Zobacz ogłoszenie ↗</a>${alsoAt}
        </div>`;
}

function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function render() {
    markersLayer.clearLayers();
    markerById = {};
    const visible = allOffers.filter(passesFilters);
    const located = visible.filter(o => o.coords);

    located.forEach(o => {
        const marker = L.marker([o.coords.lat, o.coords.lon], {
            icon: makeIcon(o),
            title: `${o.title || ''} — ${fmtPrice(o.price)}`,
            zIndexOffset: (isApprox(o) ? 0 : 200) + (o.active ? 100 : 0),
        });
        marker.bindPopup(() => popupHtml(o), { maxWidth: 330 });
        markersLayer.addLayer(marker);
        markerById[o.id] = marker;
    });

    renderStats(visible);
    renderCounts();
}

function renderStats(visible) {
    document.getElementById('visible-count').textContent = visible.length;
    const prices = visible.map(o => o.price).filter(p => p != null);
    document.getElementById('min-price').textContent = prices.length ? fmtPrice(Math.min(...prices)) : '—';
    document.getElementById('max-price').textContent = prices.length ? fmtPrice(Math.max(...prices)) : '—';
}

function renderCounts() {
    const c = (pred) => allOffers.filter(pred).length;
    document.getElementById('count-olx').textContent = `(${c(o => o.source === 'olx')})`;
    document.getElementById('count-otodom').textContent = `(${c(o => o.source === 'otodom')})`;
    document.getElementById('count-active').textContent = `(${c(o => o.active && !isApprox(o))})`;
    document.getElementById('count-active-approx').textContent = `(${c(o => o.active && isApprox(o))})`;
    document.getElementById('count-inactive').textContent = `(${c(o => !o.active && !isApprox(o))})`;
    document.getElementById('count-inactive-approx').textContent = `(${c(o => !o.active && isApprox(o))})`;
    document.getElementById('count-new').textContent = `(${c(o => o.active && isNew(o))})`;
    document.getElementById('count-private').textContent = `(${c(o => o.active && o.is_private_owner)})`;
}
