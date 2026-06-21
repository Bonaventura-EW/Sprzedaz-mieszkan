/* Animowane logo SONARA SPRZEDAŻY — "skan bloku mieszkalnego".
 * Wstrzykiwane do elementów .sonar-logo, żeby nie duplikować SVG w każdej stronie. */

const SONAR_LOGO_SVG = `
<svg width="40" height="40" viewBox="0 0 64 64" aria-hidden="true">
  <defs>
    <radialGradient id="lgBg" cx="50%" cy="42%" r="62%">
      <stop offset="0%" stop-color="#0c3d22"/>
      <stop offset="100%" stop-color="#041b0e"/>
    </radialGradient>
    <linearGradient id="lgSweep" x1="50%" y1="50%" x2="100%" y2="50%">
      <stop offset="0%" stop-color="#a3e635" stop-opacity="0.85"/>
      <stop offset="100%" stop-color="#a3e635" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="lgScan" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#a3e635" stop-opacity="0"/>
      <stop offset="50%" stop-color="#a3e635" stop-opacity="0.9"/>
      <stop offset="100%" stop-color="#a3e635" stop-opacity="0"/>
    </linearGradient>
    <mask id="lgMask"><circle cx="32" cy="32" r="29" fill="white"/></mask>
    <mask id="lgBlockMask"><rect x="22" y="17" width="20" height="30" rx="1.5" fill="white"/></mask>
  </defs>

  <circle cx="32" cy="32" r="31" fill="url(#lgBg)"/>
  <circle cx="32" cy="32" r="29.5" fill="none" stroke="#a3e635" stroke-width="1" opacity="0.55"/>
  <circle cx="32" cy="32" r="22" fill="none" stroke="#a3e635" stroke-width="0.4" opacity="0.25"/>

  <!-- blok mieszkalny: bryła z oknami -->
  <g mask="url(#lgMask)">
    <rect x="22" y="17" width="20" height="30" rx="1.5" fill="#a3e635" opacity="0.10"/>
    <rect x="22" y="17" width="20" height="30" rx="1.5" fill="none"
          stroke="#a3e635" stroke-width="1.7"/>

    <!-- okna (mrugają jak namierzone punkty) -->
    <g fill="#d9f99d">
      <rect x="26" y="21" width="4" height="4"><animate attributeName="opacity" values="1;0.2;1" dur="1.8s" repeatCount="indefinite"/></rect>
      <rect x="34" y="21" width="4" height="4"><animate attributeName="opacity" values="0.2;1;0.2" dur="1.8s" repeatCount="indefinite"/></rect>
      <rect x="26" y="28" width="4" height="4"><animate attributeName="opacity" values="0.6;1;0.6" dur="2.2s" repeatCount="indefinite"/></rect>
      <rect x="34" y="28" width="4" height="4"><animate attributeName="opacity" values="1;0.4;1" dur="2.4s" repeatCount="indefinite"/></rect>
      <rect x="26" y="35" width="4" height="4"/>
      <rect x="34" y="35" width="4" height="4"><animate attributeName="opacity" values="0.3;1;0.3" dur="2s" repeatCount="indefinite"/></rect>
    </g>

    <!-- pozioma linia skanu przesuwająca się po bloku -->
    <g mask="url(#lgBlockMask)">
      <rect x="22" y="0" width="20" height="9" fill="url(#lgScan)">
        <animate attributeName="y" values="14;43;14" dur="3.2s" repeatCount="indefinite"/>
      </rect>
    </g>
  </g>

  <!-- obrotowy snop radaru -->
  <g mask="url(#lgMask)" opacity="0.55">
    <path d="M32,32 L32,3 A29,29 0 0,1 61,32 Z" fill="url(#lgSweep)">
      <animateTransform attributeName="transform" type="rotate" from="0 32 32" to="360 32 32" dur="4s" repeatCount="indefinite"/>
    </path>
  </g>
</svg>`;

document.querySelectorAll('.sonar-logo').forEach(el => { el.innerHTML = SONAR_LOGO_SVG; });
