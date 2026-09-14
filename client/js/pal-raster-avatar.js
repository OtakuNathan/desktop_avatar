import { artwork } from './pal-raster-art.js';
import { createPalAnimation } from './pal-raster-animation.js';

// Keep wire state identity even when an expression shares another state's art.
const aliases = {
  sleepy: 'sleeping', err: 'error', laugh: 'happy', clap: 'happy',
  excited: 'happy', proud: 'smirk',
  complain: 'angry', stretching: 'greeting',
};
const states = new Set(['standby', 'thinking', 'working', 'sleeping', 'greeting',
  'curious', 'love', 'wink', 'shock', 'happy', 'cheeky', 'smirk', 'snacking', 'sad',
  'confused', 'panic', 'angry', 'error', 'shy', 'awkward', 'crying', 'bored', 'gloomy', 'drinking', 'celebrate', 'agree']);
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
  let current = 'standby', ready = true, localMotion = false;
  const animation = createPalAnimation(widget, { onActionFinished() {
    const completed = current;
    if (!localMotion) onActionFinished?.(completed);
  }});
  const controller = {
    setState(state) {
      if (!ready) return;
      localMotion = false;
      current = String(state || 'standby').trim().toLowerCase();
      const visual = aliases[current] || current;
      animation.setState(states.has(visual) ? visual : 'standby');
    },
    setCaption(text) { animation.setCaption(text); },
    startMotion(state) { this.setState(state); localMotion = true; },
    stopMotion() { localMotion = false; animation.stopMotion(); },
    motionReady: () => ready,
    destroy() { ready = false; animation.destroy(); widget.remove(); },
  };
  active = controller;
  window.PalRasterAvatar = controller;
  return controller;
}
