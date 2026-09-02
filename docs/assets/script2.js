/* SONAR SPRZEDAŻY MIESZKAŃ — mapa (wariant CANVAS, wysoka wydajność).
 *
 * Jedyna mapa projektu (ładowana przez docs/index.html). Pinezki NIE są
 * markerami DOM (L.divIcon), tylko kształtami rysowanymi na JEDNYM <canvas>
 * (L.canvas). Zamiast ~2300 węzłów DOM mamy jeden paint → płynny pan/zoom przy
 * tysiącach ofert, BEZ klastrowania.
 *
 * Kształty (własne klasy Path na canvasie):
 *  - dokładny adres (coords_precision == 'exact')   → pinezka-kropla 40×50
 *  - ulica / przybliżona Otodom (inne)              → kwadrat 34×34 (ramka przerywana)
 *  - nieaktywne → × w środku; nowa → czerwona obwódka + badge N; zmiana ceny → badge ↓/↑
 *
 * Optymalizacje:
 *  - rendering wektorowy na canvasie (L.canvas, preferCanvas),
 *  - odczyt stanu filtrów RAZ na render (buildFilterContext) zamiast ~15
 *    document.getElementById na każdą z ~2300 ofert,
 *  - culling poza widokiem robi sam renderer canvas (_pxBounds / _empty).
 */

// FIX 2026-08-27: widok startowy obejmuje Lublin i Świdnik (Świdnik leży
// ~10 km na wschód od centrum Lublina) — środek przesunięty na wschód.
const AREA_CENTER = [51.2380, 22.6150];
const NEW_OFFER_DAYS = 7;
const QUANTILE_COLORS = ['#15803d', '#4ca11e', '#84cc16', '#c4d62b', '#eab308',
                         '#f59e0b', '#f97316', '#ef4444', '#db2777', '#7c3aed'];
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

let map, markersLayer, canvasRenderer;
let markerById = {};
let allOffers = [];
let quantiles = [];
let marketFilterState = {};
let roomsFilterState = {};
let quantileBucketState = {};

/* ===== Własne kształty rysowane na canvasie ===== */
// Bazują na L.CircleMarker (dziedziczą _project / _point / _empty / kółkowe
// _pxBounds), ale nadpisują _updatePath (własny rysunek) i _containsPoint /
// _updateBounds (trafianie klikiem i obrys dopasowane do kształtu).

const PIN_W = 40, PIN_H = 50;     // kropla: tip = latlng (na dole), bąbel u góry
const SQ = 34;                    // kwadrat: środek = latlng

const PinMarker = L.CircleMarker.extend({
    _updatePath: function () {
        // _updatePath bywa wołane przy _reset (poza pętlą rysowania) — jak we
        // wbudowanych kształtach Leaflet, rysujemy tylko w trakcie _draw.
        const r = this._renderer;
        if (!r._drawing || this._empty()) return;
        drawPin(r._ctx, this._point, this._st);
    },
    _updateBounds: function () {
        const w = this._clickTolerance();
        const p = this._point;
        this._pxBounds = new L.Bounds(
            L.point(p.x - PIN_W / 2 - w, p.y - PIN_H - w),
            L.point(p.x + PIN_W / 2 + w, p.y + 2 + w));
    },
    _containsPoint: function (p) {
        // bąbel kropli: środek ~32 px nad tipem, promień ~18
        const c = L.point(this._point.x, this._point.y - 32);
        return p.distanceTo(c) <= 18 + this._clickTolerance();
    },
});

const SquareMarker = L.CircleMarker.extend({
    _updatePath: function () {
        const r = this._renderer;
        if (!r._drawing || this._empty()) return;
        drawSquare(r._ctx, this._point, this._st);
    },
    _updateBounds: function () {
        const w = this._clickTolerance();
        const p = this._point, h = SQ / 2;
        this._pxBounds = new L.Bounds(
            L.point(p.x - h - w, p.y - h - w),
            L.point(p.x + h + w, p.y + h + w));
    },
    _containsPoint: function (p) {
        const h = SQ / 2 + this._clickTolerance();
        return Math.abs(p.x - this._point.x) <= h && Math.abs(p.y - this._point.y) <= h;
    },
});

function drawPin(ctx, p, st) {
    const ox = p.x - PIN_W / 2;   // mapuje SVG (0..40, 0..50) tak, że (20,50)->tip
    const oy = p.y - PIN_H;
    ctx.beginPath();
    ctx.moveTo(ox + 20, oy + 0);
    ctx.bezierCurveTo(ox + 9, oy + 0, ox + 0, oy + 9, ox + 0, oy + 20);
    ctx.bezierCurveTo(ox + 0, oy + 35, ox + 20, oy + 50, ox + 20, oy + 50);
    ctx.bezierCurveTo(ox + 20, oy + 50, ox + 40, oy + 35, ox + 40, oy + 20);
    ctx.bezierCurveTo(ox + 40, oy + 9, ox + 31, oy + 0, ox + 20, oy + 0);
    ctx.closePath();
    ctx.fillStyle = st.fill;
    ctx.fill();
    ctx.lineWidth = st.strokeW;
    ctx.strokeStyle = st.stroke;
    ctx.stroke();
    // FIX 2026-09-01: stos ofert pod tym samym adresem → liczba w środku bąbla
    if (st.count > 1) {
        drawStackCount(ctx, ox + 20, oy + 18, st.count, true);
        return;
    }
    // wewnętrzne kółko (białe) / × dla nieaktywnej
    ctx.beginPath();
    ctx.arc(ox + 20, oy + 18, st.inactive ? 9 : 7, 0, Math.PI * 2);
    ctx.fillStyle = st.inactive ? '#ffffff' : 'rgba(255,255,255,0.9)';
    ctx.fill();
    if (st.inactive) drawX(ctx, ox + 20, oy + 18, 15, '#1f2937');
    drawBadge(ctx, ox + 36, oy + 3, st);
}

function drawSquare(ctx, p, st) {
    const left = p.x - SQ / 2, top = p.y - SQ / 2, s = SQ;
    ctx.globalAlpha = 0.85;
    ctx.fillStyle = st.fill;
    ctx.fillRect(left + 3, top + 3, s - 6, s - 6);
    ctx.globalAlpha = 1;
    ctx.lineWidth = 3;
    ctx.strokeStyle = st.stroke;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(left + 3, top + 3, s - 6, s - 6);
    ctx.setLineDash([]);
    // FIX 2026-09-01: stos ofert pod tym samym adresem → liczba w środku kwadratu
    if (st.count > 1) {
        drawStackCount(ctx, p.x, p.y, st.count, false);
        return;
    }
    if (st.inactive) drawX(ctx, p.x, p.y, 20, '#ffffff');
    drawBadge(ctx, left + s - 2, top + 2, st);
}

// Liczba ofert w stosie (kilka ofert na identycznych coords) rysowana w środku
// kształtu. onPin=true: biały bąbel + ciemna cyfra (jak wewnętrzne kółko kropli);
// onPin=false: biała cyfra z ciemnym obrysem na wypełnionym kolorem kwadracie.
function drawStackCount(ctx, cx, cy, count, onPin) {
    const txt = count > 999 ? '999+' : String(count);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    if (onPin) {
        const r = txt.length >= 3 ? 11 : (txt.length === 2 ? 10 : 9);
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();
        ctx.fillStyle = '#1f2937';
        ctx.font = '700 ' + (txt.length >= 3 ? 9 : 11) + 'px -apple-system, system-ui, sans-serif';
        ctx.fillText(txt, cx, cy + 0.5);
    } else {
        ctx.font = '800 ' + (txt.length >= 3 ? 13 : 16) + 'px -apple-system, system-ui, sans-serif';
        ctx.lineWidth = 3;
        ctx.strokeStyle = 'rgba(0,0,0,0.55)';
        ctx.strokeText(txt, cx, cy + 0.5);
        ctx.fillStyle = '#ffffff';
        ctx.fillText(txt, cx, cy + 0.5);
    }
}

function drawX(ctx, cx, cy, size, color) {
    ctx.fillStyle = color;
    ctx.font = '700 ' + size + 'px -apple-system, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = 2;
    ctx.strokeStyle = 'rgba(0,0,0,0.45)';
    ctx.strokeText('×', cx, cy + 1);
    ctx.fillText('×', cx, cy + 1);
}

function drawBadge(ctx, cx, cy, st) {
    if (!st.badge) return;
    let bg, txt, r;
    if (st.badge === 'd') { bg = '#28a745'; txt = '↓'; r = 9; }
    else if (st.badge === 'u') { bg = '#dc3545'; txt = '↑'; r = 9; }
    else { bg = '#ff0000'; txt = 'N'; r = 8; }
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = bg;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#ffffff';
    ctx.stroke();
    ctx.fillStyle = '#ffffff';
    ctx.font = '700 ' + (r + 2) + 'px -apple-system, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(txt, cx, cy + 0.5);
}

function computeStyle(o) {
    const fresh = isNew(o);
    return {
        fill: colorFor(o),
        stroke: fresh ? '#ff0000' : '#ffffff',
        strokeW: fresh ? 3 : 2,
        inactive: !o.active,
        badge: badgeType(o),
    };
}

// FIX 2026-09-01: najtańsza (wg ceny/m²) oferta ze stosu — jej kolor/kształt
// reprezentuje całą pinezkę-stos (jak u brata SONAR-POKOJOWY).
function cheapestOffer(offers) {
    let best = offers[0];
    for (let i = 1; i < offers.length; i++) {
        const o = offers[i];
        if (o.price_per_m2 != null &&
            (best.price_per_m2 == null || o.price_per_m2 < best.price_per_m2)) best = o;
    }
    return best;
}

// Styl pinezki-stosu: kształt/kolor najtańszej pozycji + liczba ofert w środku.
function computeStackStyle(offers) {
    const st = computeStyle(cheapestOffer(offers));
    st.count = offers.length;
    st.badge = '';   // licznik zastępuje badge N / ↓ / ↑ przy stosie
    return st;
}

init();

async function init() {
    map = L.map('map', { preferCanvas: true }).setView(AREA_CENTER, 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap', maxZoom: 19,
        updateWhenZooming: false, keepBuffer: 2,
    }).addTo(map);
    // jeden wspólny renderer canvas dla wszystkich kształtów
    canvasRenderer = L.canvas({ padding: 0.5 });
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

    focusOfferFromHash();
    window.addEventListener('hashchange', focusOfferFromHash);
}

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
        if (mk) setTimeout(() => {
            mk.openPopup();
            // FIX 2026-09-01: deep-link do oferty w stosie → przewiń do jej wiersza
            const row = document.querySelector(`.stack-row[data-offer-id="${o.id}"]`);
            if (row) {
                row.classList.add('stack-row-focus');
                row.scrollIntoView({ block: 'nearest' });
            }
        }, 250);
    }
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

function quantileIndex(offer) {
    const v = offer.price_per_m2;
    if (v == null || !quantiles.length) return 2;
    let i = 0;
    while (i < quantiles.length && v > quantiles[i]) i++;
    return i;
}

function badgeType(o) {
    if (o.previous_price && o.price_trend) return o.price_trend === 'down' ? 'd' : 'u';
    if (isNew(o)) return 'n';
    return '';
}

function buildMarketFilters() {
    const markets = {};
    allOffers.forEach(o => { const m = o.market || 'nieokreslony'; markets[m] = (markets[m] || 0) + 1; });
    const container = document.getElementById('market-filters');
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
        r.addEventListener('change', () => { buildLegend(); render(); }));
    ['price-min', 'price-max', 'area-min', 'area-max']
        .forEach(id => document.getElementById(id).addEventListener('input', debounce(render, 300)));
}

function debounce(fn, ms) {
    let t;
    return () => { clearTimeout(t); t = setTimeout(fn, ms); };
}

// Odczyt całego stanu filtrów RAZ na render (zamiast per-oferta).
function buildFilterContext() {
    const val = id => document.getElementById(id).value;
    const checked = id => document.getElementById(id).checked;
    const timeDays = val('time-filter');
    return {
        srcOlx: checked('src-olx'),
        srcOtodom: checked('src-otodom'),
        layerActive: checked('layer-active'),
        layerActiveApprox: checked('layer-active-approx'),
        layerInactive: checked('layer-inactive'),
        layerInactiveApprox: checked('layer-inactive-approx'),
        timeCutoff: timeDays === 'all' ? null : Date.now() - parseInt(timeDays, 10) * 86400000,
        onlyNew: checked('only-new'),
        onlyPrivate: checked('only-private'),
        colorMode: colorMode(),
        pMin: parseFloat(val('price-min')),
        pMax: parseFloat(val('price-max')),
        aMin: parseFloat(val('area-min')),
        aMax: parseFloat(val('area-max')),
    };
}

function passes(o, c) {
    if (o.source === 'olx' && !c.srcOlx) return false;
    if (o.source === 'otodom' && !c.srcOtodom) return false;

    const approx = isApprox(o);
    const layerOk = o.active
        ? (approx ? c.layerActiveApprox : c.layerActive)
        : (approx ? c.layerInactiveApprox : c.layerInactive);
    if (!layerOk) return false;

    if (c.timeCutoff != null) {
        if (!o.first_seen || new Date(o.first_seen).getTime() < c.timeCutoff) return false;
    }
    if (c.onlyNew && !isNew(o)) return false;
    if (c.onlyPrivate && !o.is_private_owner) return false;

    if (!marketFilterState[o.market || 'nieokreslony']) return false;
    if (roomsFilterState[roomsBucket(o)] === false) return false;

    if (c.colorMode === 'price' && quantileBucketState[quantileIndex(o)] === false) return false;

    if (!isNaN(c.pMin) && (o.price == null || o.price < c.pMin)) return false;
    if (!isNaN(c.pMax) && (o.price == null || o.price > c.pMax)) return false;
    if (!isNaN(c.aMin) && (o.area_m2 == null || o.area_m2 < c.aMin)) return false;
    if (!isNaN(c.aMax) && (o.area_m2 == null || o.area_m2 > c.aMax)) return false;

    return true;
}

// kolejność rysowania na canvasie = kolejność dodania (późniejsze na wierzchu):
// kwadraty pod pinezkami, nieaktywne pod aktywnymi
function zKey(o) {
    return (isApprox(o) ? 0 : 2) + (o.active ? 1 : 0);
}

function render() {
    markersLayer.clearLayers();
    markerById = {};
    const ctx = buildFilterContext();

    const located = [];
    for (let i = 0; i < allOffers.length; i++) {
        const o = allOffers[i];
        if (passes(o, ctx) && o.coords) located.push(o);
    }

    // FIX 2026-09-01: grupuj oferty o identycznych coords w jedną pinezkę-stos.
    // Precyzja `street` (ulica bez numeru) zwraca ten sam punkt dla wielu ofert,
    // więc na canvasie klikalna była tylko wierzchnia — reszta niedostępna.
    // (propagacja z SONAR-POKOJOWY, coincident-marker-stacks)
    const groups = new Map();
    for (let i = 0; i < located.length; i++) {
        const o = located[i];
        const key = o.coords.lat.toFixed(6) + ',' + o.coords.lon.toFixed(6);
        let g = groups.get(key);
        if (!g) groups.set(key, g = []);
        g.push(o);
    }

    // jednostka rysowania = grupa; kolejność jak wcześniej (kwadraty pod
    // pinezkami, nieaktywne pod aktywnymi) wg maks. zKey w grupie.
    const units = [];
    for (const offers of groups.values()) {
        let z = 0;
        for (let i = 0; i < offers.length; i++) z = Math.max(z, zKey(offers[i]));
        units.push({ offers, z });
    }
    units.sort((a, b) => a.z - b.z);

    for (let i = 0; i < units.length; i++) {
        const offers = units[i].offers;
        const stack = offers.length > 1;
        const rep = stack ? cheapestOffer(offers) : offers[0];
        const pin = !isApprox(rep);
        const Cls = pin ? PinMarker : SquareMarker;
        const mk = new Cls([rep.coords.lat, rep.coords.lon], {
            renderer: canvasRenderer, radius: 20, interactive: true,
            bubblingMouseEvents: false,
        });
        if (stack) {
            mk._st = computeStackStyle(offers);
            mk.bindPopup(() => stackPopupHtml(offers), {
                maxWidth: 340, offset: pin ? [0, -44] : [0, -16],
            });
        } else {
            mk._st = computeStyle(rep);
            mk.bindPopup(() => popupHtml(rep), {
                maxWidth: 330, offset: pin ? [0, -44] : [0, -16],
            });
        }
        markersLayer.addLayer(mk);
        // KAŻDE id z grupy wskazuje ten sam marker (deep-link/hash trafia w stos).
        for (let j = 0; j < offers.length; j++) markerById[offers[j].id] = mk;
    }

    renderStats(ctx);
    renderCounts();
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

// FIX 2026-09-01: popup pinezki-stosu — nagłówek z liczbą ofert + przewijalna
// płaska lista (posortowana od najtańszej). Każdy wiersz to link do ogłoszenia;
// nie ma tu panelu kart jak u brata, więc podświetlanie zastępujemy linkiem.
// Skala u nas bywa duża (rekord 252 oferty na jednej ulicy) → lista scrolluje się.
function stackPopupHtml(offers) {
    const sorted = offers.slice().sort((a, b) =>
        (a.price == null ? Infinity : a.price) - (b.price == null ? Infinity : b.price));
    const rep = sorted[0];
    const where = [rep.street, rep.district].filter(Boolean).join(', ');
    const precision = rep.coords_precision === 'exact' ? 'dokładny adres'
        : rep.coords_precision === 'street' ? 'lokalizacja: ulica'
        : rep.coords_precision === 'approx' ? 'przybliżona — Otodom' : '';
    const rows = sorted.map(o => {
        const trend = o.price_trend === 'down'
            ? ` <span class="trend-down">↓</span>`
            : o.price_trend === 'up' ? ` <span class="trend-up">↑</span>` : '';
        const newB = isNew(o) ? ' <span class="badge-new">NOWA</span>' : '';
        const inact = o.active ? '' : ' <span class="stack-inactive">⏸ nieaktywna</span>';
        const meta = [fmtArea(o.area_m2),
            o.price_per_m2 ? fmtPrice(o.price_per_m2) + '/m²' : null,
            o.rooms ? fmtRooms(o.rooms) : null, fmtFloor(o.floor)]
            .filter(Boolean).join(' • ');
        return `<a class="stack-row" data-offer-id="${escapeHtml(o.id)}" ` +
            `href="${safeUrl(o.url)}" target="_blank" rel="noopener">` +
            `<div class="stack-row-top"><span class="stack-price">${fmtPrice(o.price)}</span>` +
            `${trend}${newB}${inact}</div>` +
            `<div class="stack-row-meta">${escapeHtml(meta)} • ${escapeHtml((o.source || '').toUpperCase())}` +
            `${o.is_private_owner ? ' • właściciel' : ''}</div>` +
            `<div class="stack-row-title">${escapeHtml(o.title || '')}</div></a>`;
    }).join('');
    return `<div class="stack-head">${offers.length} ofert pod tym adresem</div>` +
        (where || precision
            ? `<div class="stack-where">📍 ${escapeHtml(where)}${where && precision ? ' ' : ''}` +
              `${precision ? '(' + precision + ')' : ''}</div>`
            : '') +
        `<div class="stack-list">${rows}</div>`;
}

// href tylko http(s) — treść pochodzi z zewnętrznych portali (uwaga z manifestu brata).
function safeUrl(u) {
    return (typeof u === 'string' && /^https?:\/\//i.test(u)) ? u : '#';
}

function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderStats(ctx) {
    let count = 0, minP = Infinity, maxP = -Infinity;
    for (let i = 0; i < allOffers.length; i++) {
        const o = allOffers[i];
        if (!passes(o, ctx)) continue;
        count++;
        if (o.price != null) { if (o.price < minP) minP = o.price; if (o.price > maxP) maxP = o.price; }
    }
    document.getElementById('visible-count').textContent = count;
    document.getElementById('min-price').textContent = minP === Infinity ? '—' : fmtPrice(minP);
    document.getElementById('max-price').textContent = maxP === -Infinity ? '—' : fmtPrice(maxP);
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
