import { artwork } from './pal-raster-art.js';
import { createPalAnimation } from './pal-raster-animation.js';

// Keep wire state identity even when an expression shares another state's art.
const aliases = {
  sleepy: 'sleeping', crying: 'sad', error: 'shock',
  laugh: 'happy', celebrate: 'happy', clap: 'happy', dance: 'happy',
  excited: 'happy', proud: 'happy', agree: 'happy',
  panic: 'shock', awkward: 'sad', shy: 'love', smirk: 'cheeky',
  bored: 'sad', complain: 'angry', drinking: 'snacking', stretching: 'greeting',
};
const states = new Set(['standby', 'thinking', 'working', 'sleeping', 'greeting',
  'curious', 'love', 'wink', 'shock', 'happy', 'cheeky', 'snacking', 'sad', 'confused', 'angry']);
let active = null;
export async function initPalRasterAvatar({ container, onActionFinished }) {
  active?.destroy();
  const widget = document.createElement('div');
  widget.id = 'pal-raster-widget';
  widget.innerHTML = `<div id="pal-raster-canvas" class="raster-stage" role="img" aria-label="Pal robot companion"><div class="robot">${artwork}</div></div>`;
  const paths = [...widget.querySelectorAll('image')].map(node => node.getAttribute('href'));
  await Promise.all([...new Set(paths)].map(async path => {
    const image = new Image(); image.src = path; await image.decode();
  }));
  container.appendChild(widget);
  let current = 'standby', ready = true;
  const animation = createPalAnimation(widget, { onActionFinished() {
    const completed = current;
    onActionFinished?.(completed);
  }});
  const controller = {
    setState(state) {
      if (!ready) return;
      current = String(state || 'standby').trim().toLowerCase();
      const visual = aliases[current] || current;
      animation.setState(states.has(visual) ? visual : 'standby');
    },
    startMotion(state) { this.setState(state); },
    stopMotion() { animation.stopMotion(); },
    motionReady: () => ready,
    destroy() { ready = false; animation.destroy(); widget.remove(); },
  };
  active = controller;
  window.PalRasterAvatar = controller;
  return controller;
}
