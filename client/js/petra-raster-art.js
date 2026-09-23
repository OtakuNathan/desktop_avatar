import { artwork as palArtwork, colaHandArtwork } from './pal-raster-art.js';

const assets = new URL('../assets/model/petra-raster/', import.meta.url).href;
const plate = `<image href="${assets}soft-body.png" width="1024" height="1536"/>`;
const character = `<image href="${assets}standing-character.png" width="1024" height="1536"/>`;
const piece = name => `<g clip-path="url(#petra-${name})">${character}</g>`;
// All limb coordinates come from the complete standing drawing, without stretching.
export const petraRig = {
  shoulder: [401, 865], elbow: [361, 955], wrist: [334, 1069],
  mouth: [512, 686], pinch: [303, 1140],
  headPivotY: 465,
};
const gesture = (id, clip, x, y) => `<g id="${id}" opacity="0">
  <g transform="translate(334 1069) rotate(180) scale(.23) translate(${-x} ${-y})">
    <image href="${assets}gesture-hands.png" width="1254" height="1254" clip-path="url(#${clip})"/>
  </g></g>`;
const cola = colaHandArtwork
  .replace('translate(155 575) scale(.1)', 'translate(334 1069) scale(.15)')
  .replaceAll('__ASSETS__', new URL('../assets/model/pal-raster/', import.meta.url).href);
// Keep expression coordinates shared; map the face as a unit to this screen.
// Outer viewBox remains identical to the base, so head transforms stay registered.
const eyes = palArtwork.slice(palArtwork.indexOf('<svg class="eye-overlay"'))
  .replace('</defs>', '</defs><g id="face-layout" transform="translate(-59.533 14.5) scale(1.2)">')
  .replace(/<radialGradient id="iris"[\s\S]*?<\/radialGradient>/,
    '<radialGradient id="iris"><stop stop-color="#f2ffff"/><stop offset=".75" stop-color="#c9faff"/><stop offset="1" stop-color="#76eaff"/></radialGradient>')
  .replaceAll('r="29" fill="url(#iris)"', 'r="24" fill="url(#iris)"')
  .replaceAll('class="pupil"', 'class="pupil" visibility="hidden"')
  .replace('id="mouth" stroke-width="3"', 'id="mouth" stroke-width="4"')
  .replace('</svg>', `<g id="petra-lashes" fill="none" stroke="#b7f8ff" stroke-width="3" stroke-linecap="round" filter="url(#eye-glow)">
    <path data-eye="0" d="M215 271 Q207 270 204 264 M213 279 Q205 280 201 275"/>
    <path data-eye="1" d="M377 271 Q385 270 388 264 M379 279 Q387 280 391 275"/>
  </g></g></svg>`);

export const artwork = `<svg class="base" viewBox="0 0 1024 1536" aria-hidden="true">
  <defs>
    <clipPath id="petra-head"><path d="M0 0H1024V940H720V805H300V940H0Z"/></clipPath>
    <clipPath id="petra-body"><path d="M300 805H720V940H1024V1536H0V940H300Z"/></clipPath>
  </defs>
  <g clip-path="url(#petra-body)">${plate}</g>
  <g transform="scale(1.7316808)"><g id="head-rig"><g transform="scale(.5774736)" clip-path="url(#petra-head)">${plate}</g></g></g>
</svg><svg class="arm-overlay" viewBox="0 0 1024 1536" aria-hidden="true">
  <defs>
    <clipPath id="petra-upper"><path d="M403 812Q361 803 340 839Q322 881 339 922L341 950Q350 973 374 968L391 952L413 902L416 842Z"/></clipPath>
    <clipPath id="petra-forearm"><path d="M348 940Q366 931 384 947L390 981Q387 1016 365 1068Q344 1085 293 1063L283 1053Q290 990 326 962Z"/></clipPath>
    <clipPath id="petra-hand"><path d="M292 1060Q329 1068 357 1073L356 1095Q379 1115 370 1143L365 1166L347 1194L307 1195L279 1153L272 1117L280 1084Z"/></clipPath>
    <clipPath id="petra-right"><path d="M615 809H743V1203H647L632 1133L625 1035L619 934Z"/></clipPath>
    <clipPath id="gesture-wave"><rect width="627" height="627"/></clipPath>
    <clipPath id="gesture-scratch"><rect x="627" width="627" height="627"/></clipPath>
    <clipPath id="gesture-pinch"><rect y="627" width="627" height="627"/></clipPath>
    <clipPath id="gesture-ok"><rect x="627" y="627" width="627" height="627"/></clipPath>
  </defs>
  ${piece('right')}
  <g id="shoulder-joint">
    ${piece('upper')}
    <g id="elbow-joint">
      ${piece('forearm')}
      <g id="wrist-joint">
        ${cola}
        <g id="rest-hand">${piece('hand')}</g>
        ${gesture('wave-hand', 'gesture-wave', 320, 553)}
        ${gesture('scratch-hand', 'gesture-scratch', 950, 553)}
        ${gesture('pinch-hand', 'gesture-pinch', 320, 1140)}
        ${gesture('ok-hand', 'gesture-ok', 950, 1140)}
      </g>
    </g>
  </g>
</svg>${eyes}`;
