import { artwork } from '../../js/pal-raster-art.js';
import { createPalAnimation } from '../../js/pal-raster-animation.js';
document.querySelector('.robot').innerHTML = artwork;
createPalAnimation(document.body);
