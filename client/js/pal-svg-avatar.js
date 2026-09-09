// Pal's lightweight 2D rig: independent face, head and arm groups, fixed feet.
const PERSISTENT = new Set(['standby', 'thinking', 'working', 'sleeping']);
const STATES = new Set([...PERSISTENT, 'happy', 'laugh', 'celebrate', 'panic', 'clap', 'agree', 'greeting', 'complain', 'dance', 'sad', 'angry', 'shock', 'wink', 'curious', 'awkward', 'smirk', 'cheeky', 'excited', 'shy', 'proud', 'confused', 'love', 'bored', 'snacking', 'drinking', 'stretching']);
const HAPPY = new Set(['happy', 'laugh', 'celebrate', 'clap', 'dance', 'love', 'excited']);
const SAD = new Set(['sad', 'awkward', 'bored', 'complain']);
const clamp = (x) => Math.max(0, Math.min(1, x));
const smooth = (a, b, t) => { const x = clamp((t - a) / (b - a)); return x * x * (3 - 2 * x); };
let activeAvatar = null;
let instance = 0;

function artwork(id) {
  return `<svg xmlns="http://www.w3.org/2000/svg" id="pal-svg-canvas" viewBox="0 0 320 500" role="img" aria-label="Pal robot companion">
  <defs>
    <linearGradient id="${id}-shell" x1="0" y1="0" x2=".8" y2="1"><stop stop-color="#fff"/><stop offset=".48" stop-color="#edf5f7"/><stop offset="1" stop-color="#9caeba"/></linearGradient>
    <linearGradient id="${id}-face" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#263e4a"/><stop offset=".48" stop-color="#101f2b"/><stop offset="1" stop-color="#08131e"/></linearGradient>
    <linearGradient id="${id}-joint" x2="0" y2="1"><stop stop-color="#718996"/><stop offset="1" stop-color="#283c49"/></linearGradient>
    <radialGradient id="${id}-core"><stop stop-color="#efffff"/><stop offset=".5" stop-color="#99ecff"/><stop offset="1" stop-color="#29a9ce"/></radialGradient>
    <radialGradient id="${id}-eye"><stop stop-color="#d3ffff"/><stop offset=".45" stop-color="#3ae9ff"/><stop offset="1" stop-color="#009df1"/></radialGradient>
    <filter id="${id}-glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="2"/></filter>
  </defs>
  <ellipse cx="160" cy="471" rx="78" ry="7" fill="#031321" opacity=".2"/>
  <g stroke="#526d7a" stroke-width="2.2" stroke-linejoin="round">
    <g data-part="legs">
      <path d="M119 383 Q132 377 145 386 L144 440 L111 440Z" fill="url(#${id}-joint)"/>
      <path d="M175 386 Q188 377 201 383 L209 440 L176 440Z" fill="url(#${id}-joint)"/>
      <path d="M112 415 Q128 406 146 416 L147 449 L109 449Z" fill="url(#${id}-shell)"/>
      <path d="M174 416 Q192 406 208 415 L211 449 L173 449Z" fill="url(#${id}-shell)"/>
      <path d="M111 440 Q100 447 100 461 Q115 469 146 462 L146 443 Q131 437 111 440Z" fill="url(#${id}-shell)"/>
      <path d="M174 443 L174 462 Q204 469 220 461 Q220 447 209 440 Q189 437 174 443Z" fill="url(#${id}-shell)"/>
      <path d="M103 459 Q122 465 144 459 M176 459 Q198 465 217 459" fill="none" stroke="#78909d"/>
    </g>
    <g data-part="body">
      <path d="M112 363 Q160 350 208 363 L198 400 Q160 413 122 400Z" fill="url(#${id}-joint)"/>
      <path d="M114 360 Q160 373 206 360 L199 389 Q160 407 121 389Z" fill="url(#${id}-shell)"/>
      <g data-part="arm-left">
        <circle cx="100" cy="305" r="19" fill="url(#${id}-joint)"/>
        <path d="M82 303 Q67 316 73 338 L93 344 Q107 325 101 311Z" fill="url(#${id}-shell)"/>
        <g data-part="forearm-left">
          <circle cx="82" cy="343" r="11" fill="url(#${id}-joint)"/>
          <path d="M72 341 Q60 355 62 370 L88 377 Q98 358 92 347Z" fill="url(#${id}-shell)"/>
          <path d="M65 372 Q55 379 61 394 Q67 401 76 397 L86 391 L88 378Z" fill="url(#${id}-shell)"/>
          <path d="M62 383 L70 387 L78 379" fill="none"/>
        </g>
      </g>
      <g data-part="arm-right">
        <circle cx="220" cy="305" r="19" fill="url(#${id}-joint)"/>
        <path d="M219 311 Q213 325 227 344 L247 338 Q253 316 238 303Z" fill="url(#${id}-shell)"/>
        <g data-part="forearm-right">
          <circle cx="238" cy="343" r="11" fill="url(#${id}-joint)"/>
          <path d="M228 347 Q222 358 232 377 L258 370 Q260 355 248 341Z" fill="url(#${id}-shell)"/>
          <path d="M232 378 L234 391 L244 397 Q253 401 259 394 Q265 379 255 372Z" fill="url(#${id}-shell)"/>
          <path d="M258 383 L250 387 L242 379" fill="none"/>
        </g>
      </g>
      <rect x="142" y="269" width="36" height="23" rx="9" fill="url(#${id}-joint)"/>
      <path d="M108 288 Q160 272 212 288 Q224 316 211 359 Q160 380 109 359 Q96 316 108 288Z" fill="url(#${id}-shell)"/>
      <path d="M120 294 Q157 284 198 293" stroke="#fff" stroke-width="4" fill="none" opacity=".8"/>
      <circle cx="160" cy="324" r="24" fill="#728d9c"/>
      <circle cx="160" cy="324" r="19" fill="url(#${id}-core)" stroke="#ccfaff"/>
      <path d="M155 315 L167 324 L155 333Z" fill="#efffff" stroke="none"/>
      <path d="M137 359 H183" stroke="#a1b3bc"/>
      <g data-part="head">
        <path d="M160 101 L163 73" stroke="#a2bac6" stroke-width="6"/>
        <circle cx="164" cy="66" r="10" fill="url(#${id}-core)" stroke="#d1f8ff"/>
        <rect x="40" y="172" width="25" height="68" rx="12" fill="url(#${id}-joint)"/>
        <rect x="38" y="175" width="17" height="61" rx="9" fill="url(#${id}-shell)"/>
        <rect x="255" y="172" width="25" height="68" rx="12" fill="url(#${id}-joint)"/>
        <rect x="265" y="175" width="17" height="61" rx="9" fill="url(#${id}-shell)"/>
        <path d="M54 168 Q63 104 160 104 Q257 104 266 168 L269 229 Q269 278 216 286 Q160 295 103 286 Q51 278 51 229Z" fill="url(#${id}-shell)"/>
        <path d="M71 155 Q93 116 160 117 Q222 117 247 153" fill="none" stroke="#fff" stroke-width="5" opacity=".7"/>
        <path d="M66 182 Q71 143 113 138 Q160 130 207 138 Q249 143 254 182 L253 235 Q250 266 219 272 Q160 284 101 272 Q70 266 67 235Z" fill="url(#${id}-face)" stroke="#718c98"/>
        <path d="M55 169 Q61 132 78 121 M268 176 L270 229 Q270 263 248 276" fill="none" stroke="#7ce9ff" stroke-width="3" opacity=".85"/>
        <path d="M42 180 L42 228 M278 180 L278 228" fill="none" stroke="#7ce9ff" stroke-width="3"/>
        <path d="M83 167 Q96 149 122 148" stroke="#fff" stroke-width="4" fill="none" opacity=".12" stroke-linecap="round"/>
        <g fill="none" stroke="#b0f4ff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
          <path data-part="eye-left" d="M104 206a10 14 0 1 0 20 0a10 14 0 1 0-20 0" fill="#b0f4ff"/>
          <path data-part="eye-right" d="M196 206a10 14 0 1 0 20 0a10 14 0 1 0-20 0" fill="#b0f4ff"/>
          <path data-part="brow-left" d="M101 177 Q114 171 127 177" stroke-width="4"/>
          <path data-part="brow-right" d="M193 177 Q206 171 219 177" stroke-width="4"/>
          <path data-part="mouth" d="M147 240 Q160 251 173 240" stroke-width="4.5"/>
        </g>
        <g data-part="blush" fill="#ffb1c8" stroke="none" opacity="0"><ellipse cx="96" cy="236" rx="10" ry="4"/><ellipse cx="224" cy="236" rx="10" ry="4"/></g>
      </g>
    </g>
  </g>
  <g data-part="sleep" fill="#b1edff" font-family="sans-serif" font-weight="700" text-anchor="middle" opacity="0"><text data-z="0">z</text><text data-z="1">z</text><text data-z="2">Z</text></g>
  <g data-part="thought" fill="#b1edff" opacity="0"><circle cx="254" cy="108" r="3"/><circle cx="268" cy="96" r="4"/><circle cx="285" cy="81" r="5"/></g>
  <g data-part="snack" opacity="0"><circle cx="99" cy="240" r="15" fill="#dba667" stroke="#976943" stroke-width="2"/><g fill="#795344"><circle cx="94" cy="235" r="2"/><circle cx="103" cy="243" r="2"/><circle cx="92" cy="247" r="2"/></g></g>
  <g data-part="cup" opacity="0"><path d="M213 231 H235 L232 255 H216Z" fill="#c9f6ff" stroke="#6aa2b2" stroke-width="2"/><path d="M235 235 Q250 236 235 247" fill="none" stroke="#6aa2b2" stroke-width="3"/></g>
  </svg>`;
}

export class PalSVGAvatar {
  constructor(container, { onActionFinished } = {}) {
    this.state = 'standby';
    this.elapsed = 0;
    this.clock = 0;
    this.ready = true;
    this.finished = false;
    this.onActionFinished = onActionFinished;
    this.widget = document.createElement('div');
    this.widget.id = 'pal-svg-widget';
    this.widget.innerHTML = artwork(`pal2d-${++instance}`);
    this.svg = this.widget.querySelector('svg');
    this.eyeFill = `url(#pal2d-${instance}-eye)`;
    this.parts = Object.fromEntries([...this.svg.querySelectorAll('[data-part]')].map(e => [e.dataset.part, e]));
    this.parts.body.append(this.parts['arm-left'], this.parts['arm-right']);
    this.zs = [...this.svg.querySelectorAll('[data-z]')];
    this.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    container.appendChild(this.widget);
    this.animate = this.animate.bind(this);
    this.render();
    this.frame = requestAnimationFrame(this.animate);
  }
  setState(value) {
    const aliases = { sleepy: 'sleeping', crying: 'sad', error: 'shock', wave: 'greeting' };
    const input = String(value || 'standby').toLowerCase();
    const state = aliases[input] || input;
    const next = STATES.has(state) ? state : 'standby';
    if (next === this.state && PERSISTENT.has(next)) return true;
    this.state = next;
    this.elapsed = 0;
    this.finished = false;
    this.svg.dataset.state = next;
    this.svg.setAttribute('aria-label', `Pal: ${next}`);
    this.render();
    return true;
  }
  stopMotion() { this.setState('standby'); }
  animate(now) {
    if (!this.ready) return;
    this.frame = requestAnimationFrame(this.animate);
    if (this.lastFrame && now - this.lastFrame < 1000 / 30) return;
    const delta = this.lastFrame ? Math.min((now - this.lastFrame) / 1000, 0.1) : 0;
    this.lastFrame = now;
    this.elapsed += delta;
    this.clock += delta;
    this.render();
    if (!PERSISTENT.has(this.state) && this.elapsed >= 2.8 && !this.finished) {
      this.finished = true;
      const completed = this.state;
      this.onActionFinished?.(completed);
      // The channel may synchronously preempt the reaction in its callback.
      if (this.state === completed) this.setState('standby');
    }
  }
  render() {
    const s = this.state, t = this.elapsed;
    const reduced = this.reducedMotion.matches;
    const phase = reduced ? 0 : this.clock;
    const settle = smooth(0, 0.45, t);
    const gesture = reduced ? 0 : settle * (1 - smooth(2.2, 2.8, t));
    const sleeping = s === 'sleeping';
    const thinking = s === 'thinking' || s === 'curious' || s === 'confused';
    const happy = HAPPY.has(s);
    const sad = SAD.has(s);
    const surprised = s === 'shock' || s === 'panic';
    const blinkPhase = phase % 4.9;
    const blink = !reduced && blinkPhase > 4.66 ? Math.sin((blinkPhase - 4.66) / .24 * Math.PI) : 0;
    const wink = s === 'wink' && (t < .28 || (t > .9 && t < 1.18));
    const headTilt = sleeping ? 7 * settle : thinking ? (-5 + Math.sin(phase * .7)) * settle : s === 'shy' ? 5 * gesture : s === 'greeting' ? -3 * gesture : 0;
    const nod = s === 'agree' ? Math.sin(t * 7) * 3 * gesture : 0;
    this.parts.head.setAttribute('transform', `translate(0 ${nod}) rotate(${headTilt} 160 276)`);
    this.parts.body.setAttribute('transform', `translate(0 ${-Math.sin(phase * 1.3) * .8})`);
    let left = 0, right = 0, foreLeft = 0, foreRight = 0;
    if (s === 'greeting') { left = 105 * gesture; foreLeft = Math.sin(t * 10) * 14 * gesture; }
    if (s === 'celebrate' || s === 'excited' || s === 'stretching') { left = 145 * gesture; right = -145 * gesture; }
    if (s === 'clap') { left = -38 * gesture; right = 38 * gesture; foreLeft = (-95 + Math.sin(t * 11) * 12) * gesture; foreRight = -foreLeft; }
    if (s === 'dance') { left = (45 + Math.sin(t * 6) * 35) * gesture; right = (-45 + Math.sin(t * 6) * 35) * gesture; }
    if (s === 'snacking') { left = -65 * gesture; foreLeft = -130 * gesture; }
    if (s === 'drinking') { right = 65 * gesture; foreRight = 130 * gesture; }
    this.parts['arm-left'].setAttribute('transform', `rotate(${left} 100 305)`);
    this.parts['arm-right'].setAttribute('transform', `rotate(${right} 220 305)`);
    this.parts['forearm-left'].setAttribute('transform', `rotate(${foreLeft} 82 343)`);
    this.parts['forearm-right'].setAttribute('transform', `rotate(${foreRight} 238 343)`);
    for (let i = 0; i < 2; i++) {
      const x = i ? 206 : 114;
      const eye = this.parts[i ? 'eye-right' : 'eye-left'];
      let d, fill = 'none';
      if (wink && i) d = `M${x+10} 196 L${x-8} 206 L${x+10} 216`;
      else if (sleeping || (s !== 'wink' && blink > .65)) d = `M${x-11} 209 Q${x} 213 ${x+11} 209`;
      else if (happy) d = `M${x-12} 211 Q${x} 189 ${x+12} 211`;
      else {
        const ry = surprised ? 21 : sad ? 11 : 17;
        d = `M${x-16} 206 a16 ${ry} 0 1 0 32 0 a16 ${ry} 0 1 0 -32 0`;
        fill = this.eyeFill;
      }
      eye.setAttribute('d', d); eye.setAttribute('fill', fill);
    }
    this.parts['brow-left'].setAttribute('d', thinking ? 'M101 174 Q114 166 127 170' : s === 'angry' ? 'M101 174 L127 183' : 'M101 177 Q114 171 127 177');
    this.parts['brow-right'].setAttribute('d', thinking ? 'M193 181 Q206 178 219 182' : s === 'angry' ? 'M193 183 L219 174' : 'M193 177 Q206 171 219 177');
    this.parts.mouth.setAttribute('d', surprised ? 'M153 242 a7 9 0 1 0 14 0 a7 9 0 1 0 -14 0' : sad ? 'M149 246 Q160 235 171 246' : s === 'smirk' || s === 'cheeky' ? 'M148 244 Q166 253 175 237' : happy ? 'M146 238 Q160 258 174 238' : 'M149 241 Q160 249 171 241');
    this.parts.blush.setAttribute('opacity', s === 'shy' || s === 'love' ? '.65' : '.12');
    this.parts.thought.setAttribute('opacity', thinking || s === 'working' ? '.65' : '0');
    this.parts.sleep.setAttribute('opacity', sleeping ? '1' : '0');
    this.zs.forEach((z, i) => {
      const p = reduced ? (i + .5) / 3 : ((t / 3.3 + i / 3) % 1);
      z.setAttribute('x', String(253 + p * 22)); z.setAttribute('y', String(128 - p * 64));
      z.setAttribute('font-size', String(11 + p * 7)); z.setAttribute('opacity', String(reduced ? .7 : Math.sin(p * Math.PI) * .8));
    });
    this.parts.snack.setAttribute('opacity', s === 'snacking' ? String(gesture) : '0');
    this.parts.cup.setAttribute('opacity', s === 'drinking' ? String(gesture) : '0');
  }
  destroy() { this.ready = false; cancelAnimationFrame(this.frame); this.widget.remove(); }
}

export async function initPalSVGAvatar({ container, onActionFinished }) {
  if (!container) throw new Error('Pal SVG avatar requires a container');
  activeAvatar?.destroy();
  activeAvatar = new PalSVGAvatar(container, { onActionFinished });
  window.PalSVGAvatar = {
    setState: state => activeAvatar?.setState(state),
    startMotion: state => activeAvatar?.setState(state),
    stopMotion: () => activeAvatar?.stopMotion(),
    motionReady: () => !!activeAvatar?.ready,
    destroy: () => { activeAvatar?.destroy(); activeAvatar = null; },
  };
  return activeAvatar;
}
