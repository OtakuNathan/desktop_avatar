/* Shared expression rig for the desktop renderer and standalone preview. */
export function createPalAnimation(root, { onActionFinished } = {}) {
  const $ = id => root.querySelector(`#${id}`);
  const overlay = root.querySelector('.eye-overlay');
  const lids = [...root.querySelectorAll('.lid')];
  const irises = [...root.querySelectorAll('.iris-eye')];
  const pupils = [...root.querySelectorAll('.pupil')];
  const lifecycle = new AbortController();
  let destroyed = false;
  const listen = (target, event, handler) => target.addEventListener(event, handler, { signal: lifecycle.signal });
  const controls = !!$('expressions');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const baseStates = new Set(['standby', 'thinking', 'working', 'sleeping']);
  const presets = {
    greeting: ['打招呼 · 挥手', 'happy', 'smile'],
    standby: ['待机', 'round', 'smile'], thinking: ['思考', 'round', 'flat'],
    working: ['工作', 'round', 'smile'], sleeping: ['睡觉', 'closed', 'flat'],
    curious: ['好奇 · 星星眼', 'star', 'small'], love: ['喜欢 · 爱心眼', 'heart', 'smile'],
    wink: ['Wink · 0_<', 'wink', 'smirk'], shock: ['惊醒', 'wide', 'o'],
    happy: ['开心', 'happy', 'grin'], cheeky: ['耍贱 · 吐舌', 'playful', 'tongue'],
    smirk: ['坏笑', 'sly', 'smirk'],
    snacking: ['赛博零食', 'happy', 'chew'], sad: ['难过', 'pleading', 'pout'],
    drinking: ['赛博可乐', 'round', 'small'],
    error: ['故障 · 崩溃脸', 'cross', 'open'], shy: ['害羞 · 脸红', 'happy', 'small'],
    awkward: ['尴尬 · 偷吃被发现', 'cookie', 'small'], crying: ['哭 · 眼泪', 'round', 'sad'],
    bored: ['无聊 · 挠头', 'heavy', 'flat'], gloomy: ['阴郁 · 小乌云', 'heavy', 'sad'], celebrate: ['庆祝 · 烟花', 'happy', 'grin'],
    agree: ['同意 · OK 手势', 'happy', 'smile'],
    confused: ['疑惑 · 问号眼', 'question', 'small'], panic: ['懵圈 · 大头螺旋眼', 'spiral', 'o'], angry: ['生气', 'round', 'sad'],
  };
  const mouths = {
    open: 'M 281 316 Q 296 305 311 316 L 309 333 Q 296 343 283 333 Z',
    smile: 'M 281 315 Q 296 329 311 315', flat: 'M 287 318 Q 296 318 305 318',
    small: 'M 290 316 Q 296 321 302 316', smirk: 'M 281 318 Q 301 327 312 312',
    sad: 'M 283 323 Q 296 312 309 323',
    o: 'M 296 310 C 306 310 306 328 296 328 C 286 328 286 310 296 310',
    chew: 'M 285 316 Q 296 332 307 316 Q 296 311 285 316',
    grin: 'M 279 316 Q 296 320 313 316 C 312 334 281 334 279 316 Z',
    pout: 'M 290 322 Q 296 313 302 322',
    tongue: 'M 292 319 Q 303 320 315 314 L 313 330 C 309 340 296 337 295 330 Z',
  };
  let base = 'standby', state = base, age = 0, paused = reduce.matches, slow = false;
  let caption = '';
  let raf = 0, timer = 0, previous = 0, blinkAge = null;
  const animated = () => !baseStates.has(state) || blinkAge !== null || state === 'sleeping' || state === 'thinking';
  const ease = t => t * t * (3 - 2 * t);
  const duration = () => state === 'drinking' ? 5200 : ['greeting', 'agree', 'confused', 'bored', 'gloomy'].includes(state) ? 4200 : ['snacking', 'celebrate'].includes(state) ? 3600 : state === 'shock' ? 1100 : 2600;
  function cancel() { clearTimeout(timer); cancelAnimationFrame(raf); timer = raf = 0; previous = 0; }
  function star(cx) {
    const points = Array.from({length: 10}, (_, i) => {
      const a = -Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 13 : 30;
      return `${cx + Math.cos(a) * r},${279 + Math.sin(a) * r}`;
    }).join(' ');
    return `<g class="eye-symbol" data-cx="${cx}"><polygon points="${points}" fill="#7cffff" stroke="#20bdff" stroke-width="2"/></g>`;
  }
  function heart(cx) {
    return `<g class="eye-symbol" data-cx="${cx}"><path transform="translate(${cx} 278)" d="M 0 24 C -48 -5 -24 -39 0 -16 C 24 -39 48 -5 0 24 Z" fill="#ff78d4" stroke="#ffb1ea" stroke-width="2"/></g>`;
  }
  function question(cx, y) {
    return `<g class="question-eye" transform="translate(${cx} ${y})"><path d="M -16 -13 C -17 -34 20 -35 19 -14 C 18 -2 1 -3 1 10"/><circle cx="1" cy="23" r="3.5" fill="#31e6ff" stroke="none"/></g>`;
  }
  function spiral(cx) {
    const points = Array.from({length: 85}, (_, i) => {
      const angle = i / 84 * Math.PI * 4.6, radius = 2 + i / 84 * 25;
      return `${i ? 'L' : 'M'} ${(Math.cos(angle) * radius).toFixed(2)} ${(Math.sin(angle) * radius).toFixed(2)}`;
    }).join(' ');
    return `<g class="spiral-eye" data-cx="${cx}" transform="translate(${cx} 279)"><path d="${points}" stroke-width="4"/></g>`;
  }
  // Cut the luminous eye silhouette with an upper lid instead of flattening
  // the whole iris. The pupil keeps its round shape, as in the concept sheet.
  function conceptEye(cx, shape, lookX = 0, lookY = 0, className = '') {
    const id = `expression-lid-${cx}`;
    return `<g class="concept-eye ${className}" transform="translate(${cx} 279)">
      <defs><clipPath id="${id}"><path d="${shape}"/></clipPath></defs>
      <g clip-path="url(#${id})" stroke="none">
        <circle r="30" fill="url(#iris)"/>
        <g transform="translate(${lookX} ${lookY})">
          <circle r="14" fill="url(#pupil)"/>
          <circle cx="5" cy="-8" r="4" fill="#e8ffff"/>
          <circle cx="-5" cy="7" r="1.8" fill="#68dcff" opacity=".65"/>
        </g>
      </g></g>`;
  }
  const roundEye = 'M -29 0 C -29 -39 29 -39 29 0 C 29 36 -29 36 -29 0 Z';
  function face() {
    const [, kind, mouth] = presets[state];
    irises.forEach((eye, i) => { eye.style.opacity = ['round', 'wide'].includes(kind) || kind === 'wink' && i === 0 ? '1' : '0'; });
    const art = {
      cross: () => '<path class="crash-eye" d="M 218 260 L 254 296 M 254 260 L 218 296 M 338 260 L 374 296 M 374 260 L 338 296"/>',
      cookie: () => [236, 356].map(cx => conceptEye(cx, 'M -27 -16 Q 0 -26 26 -15 Q 32 -2 27 17 Q 0 20 -27 12 Q -32 0 -27 -16 Z', 18, 1, 'cookie-eye')).join(''),
      pleading: () => [236, 356].map(cx => conceptEye(cx, roundEye, cx === 236 ? 9 : -9, -16)).join(''),
      heavy: () => [236, 356].map(cx => conceptEye(cx, 'M -29 0 L 29 0 C 29 35 -29 35 -29 0 Z', 5, 0)).join(''),
      sly: () => conceptEye(236, 'M -28 -17 L 28 -4 C 28 34 -31 34 -28 -17 Z', 9, -6)
        + conceptEye(356, 'M -28 -4 L 28 -17 C 31 34 -28 34 -28 -4 Z', -9, -6),
      playful: () => conceptEye(236, roundEye, 9, -2)
        + '<path d="M 329 284 Q 352 255 379 271 Q 358 268 337 281 Q 354 277 366 284" stroke-width="5"/>',
      question: () => question(236, 276) + question(356, 282),
      spiral: () => spiral(236) + spiral(356),
      star: () => star(236) + star(356), heart: () => heart(236) + heart(356),
      happy: () => '<path d="M 209 284 C 218 257 248 257 263 284 C 247 267 224 267 209 284 Z M 329 284 C 338 257 368 257 383 284 C 367 267 344 267 329 284 Z" fill="url(#iris)" stroke-width="2"/>',
      closed: () => '<path d="M 211 279 Q 236 285 261 279 M 331 279 Q 356 285 381 279"/>',
      wink: () => '<path id="wink-mark" d="M 371 263 L 345 279 L 371 292"/>',
    };
    $('expressive-eyes').innerHTML = `<g fill="none" stroke="#31e6ff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">${art[kind]?.() || ''}</g>`;
    $('mouth').setAttribute('d', mouths[mouth]);
    const brows = ['angry', 'smirk'].includes(state) ? ['M 216 229 Q 235 232 254 241', 'M 338 241 Q 357 232 376 229']
      : ['curious', 'confused', 'wink', 'cheeky'].includes(state) ? ['M 215 227 Q 232 217 250 223', 'M 342 235 Q 360 232 376 238']
      : ['sad', 'crying', 'awkward', 'gloomy'].includes(state) ? ['M 218 240 Q 238 237 250 228', 'M 342 228 Q 354 237 374 240']
      : state === 'bored' ? ['M 218 244 Q 233 238 249 243', 'M 343 243 Q 359 238 374 244']
      : state === 'shock' ? ['M 218 224 Q 234 214 250 220', 'M 342 220 Q 358 214 374 224']
      : ['M 218 235 Q 234 226 250 230', 'M 342 230 Q 358 226 374 235'];
    $('brow-left').setAttribute('d', brows[0]); $('brow-right').setAttribute('d', brows[1]);
    $('cheeks').setAttribute('opacity', ['bored', 'gloomy', 'shock', 'smirk'].includes(state) ? '0' : '.6');
    $('cheeks').setAttribute('stroke', state === 'love' ? '#ff78d4' : '#25dfff');
    $('caption').textContent = state === 'working' ? '· · ·' : '';
    if ($('state-label')) $('state-label').textContent = `${presets[state][0]} · ${state}`;
    overlay.dataset.state = state;
    root.querySelectorAll('[data-expression]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.expression === state)));
    pupils.forEach(p => { p.style.transform = ''; });
    draw();
  }
  function openness(open) {
    const kind = presets[state][1];
    const resting = state === 'bored' ? .40 : ['thinking', 'sad', 'crying'].includes(state) ? .72 : 1;
    lids.forEach(lid => lid.setAttribute('ry', Math.max(.001, 30 * open * resting)));
    $('closed-eyes').setAttribute('opacity', ['round', 'wide'].includes(kind) ? Math.pow(1 - open, 10) : 0);
    overlay.dataset.openness = open.toFixed(4);
  }
  function draw() {
    const t = blinkAge;
    openness(t === null ? 1 : t < 100 ? 1 - ease(t / 100) : t < 135 ? 0 : t < 315 ? ease((t - 135) / 180) : 1);
    $('snack').setAttribute('opacity', '0');
    $('cyber-cola').setAttribute('opacity', '0');
    $('mouth').setAttribute('transform', '');
    $('particles').replaceChildren(); $('head-effect').replaceChildren();
    $('caption').setAttribute('y', '100');
    // Scale the shell and facial overlay together around the neck; arms/body stay put.
    const bigHead = state === 'panic';
    const ramp = ease(Math.min(1, age / 340));
    const settle = 1 - ease(Math.max(0, Math.min(1, (age - 2050) / 550)));
    const amount = bigHead ? (reduce.matches ? 1 : ramp * settle) : 0;
    const scale = 1 + amount * (.20 + (reduce.matches ? 0 : .035 * Math.sin(age / 110) * Math.exp(-age / 900)));
    const scaleY = 1 + (scale - 1) * .45;
    const tilt = bigHead && !reduce.matches ? amount * 3 * Math.sin(age / 180) : 0;
    $('head-rig').setAttribute('transform', `translate(296 377) rotate(${tilt}) scale(${scale} ${scaleY}) translate(-296 -377)`);
    overlay.style.transformOrigin = '50.055% 42.503%';
    overlay.style.transform = `rotate(${tilt}deg) scale(${scale}, ${scaleY})`;
    overlay.dataset.headScale = String(scale);
    animateExpression();
    animateArms();
    if (caption) $('caption').textContent = caption;
    if (state === 'drinking') {
      const t = reduce.matches ? 2300 : age;
      const sipping = t >= 1650 && t <= 3300;
      $('mouth').setAttribute('d', sipping ? 'M 292 318 Q 296 322 300 318' : mouths.small);
      if (t > 3750) $('caption').textContent = 'Ahh… ⚡';
    }
    if (state === 'snacking') {
      const swallowed = Math.max(0, Math.min(1, (age - 1400) / 350));
      const matrix = overlay.getScreenCTM().inverse().multiply($('pinch-hand').getScreenCTM());
      // The chip follows the pinch point through the exact same joint transforms.
      const tip = new DOMPoint(1420, 330).matrixTransform(matrix);
      $('snack').setAttribute('transform', `translate(${tip.x} ${tip.y}) scale(${.4 * (1 - swallowed)})`);
      $('snack').setAttribute('opacity', age < 1750 ? 1 - swallowed : 0);
      const chew = age > 1450 ? .7 + .3 * Math.cos((age - 1450) / 90) : 1;
      $('mouth').setAttribute('transform', `translate(296 319) scale(1 ${chew}) translate(-296 -319)`);
      $('caption').textContent = age > 2700 ? 'ENERGY +1 ⚡' : '';
      $('caption').setAttribute('y', 100 - Math.max(0, age - 2700) / 60);
    }
  }
  function sparkles(progress, color, originX = 296, originY = 175) {
    return Array.from({length: 7}, (_, i) => {
      const phase = (progress + i / 7) % 1;
      const angle = i * 2.39996;
      const radius = 70 + phase * 60;
      const x = originX + Math.cos(angle) * radius;
      const y = originY + Math.sin(angle) * radius * .6 - phase * 28;
      const scale = Math.sin(phase * Math.PI) * .9;
      return `<path transform="translate(${x} ${y}) scale(${scale})" d="M 0 -8 L 2 -2 L 8 0 L 2 2 L 0 8 L -2 2 L -8 0 L -2 -2 Z" fill="${color}" opacity="${Math.sin(phase * Math.PI)}"/>`;
    }).join('');
  }
  function animateExpression() {
    if (state === 'curious' || state === 'love') {
      root.querySelectorAll('.eye-symbol').forEach((eye, i) => {
        const cx = eye.dataset.cx;
        const pulse = 1 + .09 * Math.sin(age / (state === 'love' ? 180 : 240) + i * .35);
        eye.setAttribute('transform', `translate(${cx} 279) scale(${pulse}) translate(${-cx} -279)`);
      });
      if (state === 'curious') $('particles').innerHTML = sparkles(age / 1700, '#8affff');
    }
    if (state === 'wink') {
      const closure = age < 320 ? ease(age / 320) : age < 1400 ? 1 : 1 - ease(Math.min(1, (age - 1400) / 480));
      lids[1].setAttribute('ry', Math.max(.001, 30 * (1 - closure)));
      irises[1].style.opacity = String(1 - closure);
      $('wink-mark').setAttribute('opacity', closure);
      $('wink-mark').setAttribute('transform', `translate(356 279) scale(1 ${.45 + .55 * closure}) translate(-356 -279)`);
    }
    if (state === 'thinking' || state === 'bored') {
      const look = ease(Math.min(1, age / 700));
      pupils.forEach(p => { p.style.transform = `translate(${7 * Math.sin(age / 650) * look}px, ${-10 * look}px)`; });
      if (state === 'thinking' && age > 1800 && age < 3200) {
        const phase = (age - 1800) / 1400;
        const glow = Math.sin(phase * Math.PI);
        $('head-effect').innerHTML = `<g transform="translate(374 86) scale(${.8 + glow * .25})" opacity="${glow}" stroke="#ffe583" stroke-width="3" fill="none" stroke-linecap="round"><path d="M -9 12 C -9 4 -17 1 -17 -10 A 17 17 0 1 1 17 -10 C 17 1 9 4 9 12 Z" fill="#ffe583" fill-opacity=".3"/><path d="M -8 18 H 8 M -5 24 H 5 M 0 -37 V -44 M -29 -27 L -35 -33 M 29 -27 L 35 -33 M -28 -7 H -36 M 28 -7 H 36"/></g>`;
        $('particles').innerHTML = sparkles(phase, '#ffe583', 374, 95);
      }
    }
    if (state === 'sleeping') {
      $('particles').innerHTML = Array.from({length: 3}, (_, i) => {
        const phase = (age / 3200 + i / 3) % 1;
        const x = 373 + 14 * Math.sin(phase * Math.PI) + phase * 22;
        const y = 144 - phase * 102;
        return `<text x="${x}" y="${y}" fill="#9adfff" font-family="monospace" font-weight="700" font-size="${27 + phase * 17}" opacity="${Math.sin(phase * Math.PI) * .85}">${i === 0 ? 'Z' : 'z'}</text>`;
      }).join('');
    }
    if (state === 'error') {
      $('mouth').setAttribute('fill', '#08273a');
    } else if (['grin', 'tongue'].includes(presets[state][2])) {
      $('mouth').setAttribute('fill', 'url(#iris)');
    } else $('mouth').setAttribute('fill', 'none');
    if (state === 'cheeky') {
      $('particles').innerHTML = '<path d="M 303 322 L 305 329" fill="none" stroke="#0876ad" stroke-width="2" stroke-linecap="round"/>';
    }
    if (state === 'shy') {
      const opacity = reduce.matches ? .7 : .55 + .2 * Math.sin(age / 330);
      $('particles').innerHTML = [225, 368].map(x => `<g class="blush" opacity="${opacity}"><ellipse cx="${x}" cy="311" rx="24" ry="10" fill="#ff739b"/><path d="M ${x-12} 307 l -3 7 M ${x} 307 l -3 7 M ${x+12} 307 l -3 7" stroke="#ffc0d3" stroke-width="2"/></g>`).join('');
    }
    if (state === 'crying') {
      $('particles').innerHTML = [213, 379].map((x, i) => {
        const phase = reduce.matches ? .45 : (age / 1150 + i * .35) % 1;
        return `<path class="tear" transform="translate(${x} ${294 + phase * 43})" d="M 0 -8 C -2 -3 -9 3 -7 8 C -5 16 6 16 8 8 C 10 3 3 -4 0 -8 Z" fill="#52cfff" stroke="#b6f4ff" stroke-width="1.5" opacity="${.9 - phase * .45}"/>`;
      }).join('');
    }
    if (state === 'gloomy') {
      $('head-effect').innerHTML = `<g class="gloom" fill="none" stroke="#929ed5" stroke-width="4" stroke-linecap="round"><path d="M 345 123 Q 331 108 341 98 Q 349 91 361 96 Q 370 80 386 91 Q 400 83 409 99 Q 428 100 421 115 Q 412 128 394 122 Z" fill="#363b66"/>${[349,365,381,397,413].map((x,i)=>`<path d="M ${x} 139 v ${18 + (reduce.matches ? 0 : 5 * Math.sin(age/250+i))}"/>`).join('')}</g>`;
    }
    if (state === 'celebrate') {
      const t = reduce.matches ? 850 : age;
      $('particles').innerHTML = [185, 403, 296].map((cx, j) => {
        const phase = (t / 1350 + j / 3) % 1;
        const cy = j === 2 ? 80 : 155, radius = 10 + phase * 75;
        const color = ['#ff9edb', '#8cfff1', '#ffe897'][j];
        return `<g class="firework" stroke="${color}" stroke-width="3.5" stroke-linecap="round" opacity="${Math.sin(phase * Math.PI)}">${Array.from({length:10},(_,i)=>{const a=i*Math.PI/5;return `<path d="M ${cx+Math.cos(a)*radius*.7} ${cy+Math.sin(a)*radius*.7} L ${cx+Math.cos(a)*radius} ${cy+Math.sin(a)*radius}"/>`;}).join('')}</g>`;
      }).join('');
    }
    if (state === 'panic') {
      root.querySelectorAll('.spiral-eye').forEach((eye, i) => {
        const turn = reduce.matches ? 0 : age / 7 * (i ? -1 : 1);
        eye.setAttribute('transform', `translate(${eye.dataset.cx} 279) rotate(${turn})`);
      });
    }
    if (state === 'confused') {
      $('head-effect').innerHTML = `<text x="390" y="110" text-anchor="middle" fill="#a4eaff" font-family="system-ui" font-weight="700" font-size="34" transform="rotate(${5 * Math.sin(age / 240)} 390 110)">???</text>`;
    }
    if (state === 'angry') {
      const scale = .9 + .12 * Math.sin(age / 120);
      $('head-effect').innerHTML = `<g transform="translate(393 150) scale(${scale})" fill="none" stroke="#ff6f87" stroke-width="5" stroke-linecap="round"><path d="M -17 -5 Q -5 -5 -5 -17 M 5 -17 Q 5 -5 17 -5 M 17 5 Q 5 5 5 17 M -5 17 Q -5 5 -17 5"/></g>`;
    }
  }
  function animateArms() {
    let shoulder = 0, elbow = 0, wrist = 0;
    const wave = state === 'greeting' || state === 'agree';
    const okay = state === 'agree';
    const eating = state === 'snacking';
    const drinking = state === 'drinking';
    const scratch = ['thinking', 'confused', 'bored'].includes(state) && age < 4200;
    if (wave) {
      const envelope = ease(Math.min(1, age / 750)) * (1 - ease(Math.max(0, Math.min(1, (age - 3350) / 850))));
      const oscillation = Math.sin(Math.max(0, age - 750) / 150);
      shoulder = 65 * envelope;
      elbow = (100 + 5 * oscillation) * envelope;
      wrist = (15 + 7 * oscillation) * envelope;
    }
    if (scratch) {
      const ramp = (start, end) => ease(Math.max(0, Math.min(1, (age - start) / (end - start))));
      // Fold the forearm before lifting the upper arm, then reverse the order
      // on return. This keeps the hand close instead of sweeping a long arc.
      const fold = ramp(0, 600) * (1 - ramp(3650, 4200));
      const lift = ramp(250, 950) * (1 - ramp(3100, 3750));
      const contact = ramp(950, 1150) * (1 - ramp(2850, 3100));
      const stroke = 5 * Math.sin(Math.max(0, age - 1150) * Math.PI / 360) * contact;
      shoulder = 65 * lift;
      elbow = 120 * fold + stroke;
      // The wrist stays neutral during scratching; only the elbow strokes.
      wrist = -10 * fold;
    }
    if (eating) {
      const t = age;
      const lift = ease(Math.min(1, t / 1250));
      const lower = 1 - ease(Math.max(0, Math.min(1, (t - 1850) / 1000)));
      const envelope = lift * lower;
      shoulder = -50 * envelope;
      elbow = -125 * envelope;
      wrist = 45 * envelope;
    }
    let colaOpacity = 0;
    if (drinking) {
      const t = reduce.matches ? 2300 : age;
      const ramp = (start, end) => ease(Math.max(0, Math.min(1, (t - start) / (end - start))));
      const hold = ramp(0, 450) * (1 - ramp(4700, 5150));
      const sip = ramp(500, 1650) * (1 - ramp(3300, 4350));
      // The hand and straw are one rigid sprite. Solve the arm for a wrist
      // target derived from its straw tip (1068,133), so no prop slides or stretches.
      const scale = .1, anchor = { x: 250, y: 1020 }, angle = -10 * Math.PI / 180;
      const tipX = (1068 - anchor.x) * scale, tipY = (133 - anchor.y) * scale;
      const sipWrist = {
        x: 296 - (tipX * Math.cos(angle) - tipY * Math.sin(angle)),
        y: 318 - (tipX * Math.sin(angle) + tipY * Math.cos(angle)),
      };
      const x = 155 + (185 - 155) * hold + (sipWrist.x - 185) * sip;
      const y = 575 + (555 - 575) * hold + (sipWrist.y - 555) * sip;
      const dx = x - 199, dy = y - 415;
      const upper = Math.hypot(-22, 68), forearm = Math.hypot(-22, 92);
      const bend = -Math.acos(Math.max(-1, Math.min(1, (dx * dx + dy * dy - upper * upper - forearm * forearm) / (2 * upper * forearm))));
      const heading = Math.atan2(dy, dx) - Math.atan2(forearm * Math.sin(bend), upper + forearm * Math.cos(bend));
      shoulder = (heading - Math.atan2(68, -22)) * 180 / Math.PI;
      elbow = (bend - Math.atan2(92, -22) + Math.atan2(68, -22)) * 180 / Math.PI;
      // Keep the painted side grip aligned with the raised forearm and straw.
      wrist = -10 * hold - shoulder - elbow;
      colaOpacity = ramp(0, 450) * (1 - ramp(4400, 4700));
    }
    $('cyber-cola').setAttribute('opacity', colaOpacity);
    $('shoulder-joint').setAttribute('transform', `rotate(${shoulder} 199 415)`);
    $('elbow-joint').setAttribute('transform', `rotate(${elbow} 177 483)`);
    $('wrist-joint').setAttribute('transform', `rotate(${wrist} 155 575)`);
    $('wave-hand').setAttribute('opacity', wave && !okay ? 1 : 0);
    $('ok-hand').setAttribute('opacity', okay ? 1 : 0);
    $('scratch-hand').setAttribute('opacity', scratch ? 1 : 0);
    $('pinch-hand').setAttribute('opacity', eating ? 1 : 0);
    $('rest-hand').setAttribute('opacity', drinking ? 1 - colaOpacity : wave || scratch || eating ? 0 : 1);
  }
  function schedule() {
    if (destroyed || document.hidden) return;
    if (paused) {
      if (onActionFinished && !baseStates.has(state)) timer = setTimeout(finish, duration());
      return;
    }
    if (animated()) { raf = requestAnimationFrame(tick); return; }
    if (state !== 'sleeping') timer = setTimeout(blink, 3200 + Math.random() * 2400);
  }
  function tick(now) {
    const delta = previous ? Math.min(50, now - previous) / (slow ? 5 : 1) : 0;
    previous = now; age += delta;
    if (blinkAge !== null) { blinkAge += delta; if (blinkAge >= 315) blinkAge = null; }
    draw();
    if (!baseStates.has(state) && age >= duration()) { finish(); return; }
    raf = 0;
    if (animated()) raf = requestAnimationFrame(tick);
    else { previous = 0; schedule(); }
  }
  function finish() {
    const completed = state;
    select(base);
    onActionFinished?.(completed);
  }
  function select(next) {
    if (!presets[next]) return;
    cancel(); state = next; age = 0; blinkAge = null;
    if (baseStates.has(next)) base = next;
    face(); schedule();
  }
  function blink() {
    cancel();
    if (document.hidden || paused || !['round', 'wide'].includes(presets[state][1])) { schedule(); return; }
    blinkAge = 0; schedule();
  }
  function sync() {
    cancel(); root.classList.toggle('paused', paused || document.hidden);
    if ($('pause')) { $('pause').textContent = paused ? '播放' : '暂停'; $('pause').setAttribute('aria-pressed', String(paused)); }
    draw(); schedule();
  }
  if (controls) {
  Object.entries(presets).forEach(([value, [label]]) => {
    const button = document.createElement('button'); button.textContent = label; button.dataset.expression = value;
    button.onclick = () => select(value); $('expressions').append(button);
  });
  $('message').onclick = () => { const asleep = base === 'sleeping'; base = 'thinking'; select(asleep ? 'shock' : base); };
  $('framing').onclick = () => {
    const full = root.classList.toggle('full-body');
    $('framing').textContent = full ? '只看上半身' : '显示全身';
    $('framing').setAttribute('aria-pressed', String(full));
  };
  $('blink').onclick = blink;
  $('pause').onclick = () => { paused = !paused; sync(); };
  $('slow').onclick = () => { slow = !slow; $('slow').setAttribute('aria-pressed', String(slow)); $('slow').textContent = slow ? '正常速度' : '慢动作'; };
  }
  listen(document, 'pointermove', event => {
    if (paused || reduce.matches || document.hidden || state !== 'standby' || blinkAge !== null) return;
    const box = overlay.getBoundingClientRect();
    const x = Math.max(-5, Math.min(5, (event.clientX - box.left - box.width * .5) / box.width * 10));
    const y = Math.max(-3, Math.min(3, (event.clientY - box.top - box.height * .315) / box.height * 8));
    pupils.forEach(p => { p.style.transform = `translate(${x}px, ${y}px)`; });
  });
  listen(document.documentElement, 'pointerleave', () => { if (state === 'standby') pupils.forEach(p => { p.style.transform = ''; }); });
  listen(document, 'visibilitychange', sync);
  listen(reduce, 'change', () => { paused = reduce.matches; pupils.forEach(p => { p.style.transform = ''; }); sync(); });
  face(); sync();
  return {
    setCaption(text) { caption = String(text || '').slice(0, 48); if (!destroyed) face(); },
    setState(next) { if (!destroyed && !(next === state && baseStates.has(next))) select(next); },
    stopMotion() { if (!destroyed) select(base); },
    destroy() { destroyed = true; cancel(); lifecycle.abort(); },
  };
}
