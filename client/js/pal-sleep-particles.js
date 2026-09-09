import * as THREE from "../vendor/three.module.min.js";

export function createPalSleepParticles(model) {
  const head = model.getObjectByName("Head");
  if (!head) return null;
  model.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(model);
  const height = bounds.max.y - bounds.min.y;
  const screen = model.getObjectByName("tripo_part_37");
  const headBounds = screen ? new THREE.Box3().setFromObject(screen) : bounds;
  const anchor = new THREE.Vector3(headBounds.max.x, headBounds.max.y, headBounds.max.z);
  anchor.x += height * 0.025;
  const group = new THREE.Group();
  group.name = "PalSleepParticles";
  group.position.copy(head.worldToLocal(anchor));
  // Use the upright model axes for drift, then follow the head as it settles.
  group.quaternion.copy(head.getWorldQuaternion(new THREE.Quaternion()).invert());
  group.scale.setScalar(height).divide(head.getWorldScale(new THREE.Vector3()));
  head.add(group);
  group.visible = false;

  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext("2d");
  ctx.font = "bold 88px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#b7efff";
  ctx.shadowColor = "#65ceff";
  ctx.shadowBlur = 8;
  ctx.fillText("Z", 64, 68);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprites = Array.from({ length: 3 }, () => {
    const material = new THREE.SpriteMaterial({
      map: texture, transparent: true, opacity: 0, depthWrite: false,
      depthTest: false, toneMapped: false,
    });
    const sprite = new THREE.Sprite(material);
    sprite.renderOrder = 10;
    group.add(sprite);
    return sprite;
  });
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let elapsed = 0;
  return {
    setSleeping(sleeping) {
      if (group.visible === sleeping) return;
      group.visible = sleeping;
      elapsed = 0;
      sprites.forEach((sprite) => { sprite.material.opacity = 0; });
    },
    update(delta) {
      if (!group.visible) return;
      elapsed += delta;
      sprites.forEach((sprite, i) => {
        // Stagger three reusable particles; no accumulating DOM nodes/timers.
        const age = elapsed - i * 1.1;
        const progress = reducedMotion?.matches ? (i + 0.5) / 3 : (Math.max(0, age) % 3.3) / 3.3;
        sprite.position.set(0.045 * progress, 0.14 * progress, 0);
        sprite.scale.setScalar(0.032 + 0.024 * progress);
        sprite.material.opacity = reducedMotion?.matches ? 0.7 : age < 0 ? 0 : Math.sin(Math.PI * progress) * 0.85;
      });
    },
    destroy() {
      group.removeFromParent();
      sprites.forEach((sprite) => sprite.material.dispose());
      texture.dispose();
    },
  };
}
