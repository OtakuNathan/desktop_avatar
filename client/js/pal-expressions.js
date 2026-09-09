import * as THREE from "../vendor/three.module.min.js";

// This GLB has a separate curved face screen. Project UVs in the rest pose;
// skinning then carries the screen and its expression with the head.
export function createPalExpressions(scene, animations) {
  const face = scene.getObjectByName("tripo_part_37");
  if (!face?.isSkinnedMesh || !animations.some((clip) => clip.name === "Robot_Wave_Pal")) return null;
  scene.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(face);
  const size = bounds.getSize(new THREE.Vector3());
  // Do not apply model-specific UVs to an unrelated replacement mesh.
  if (size.x / size.y < 1.3 || size.x / size.y > 1.7 || size.z / size.x > 0.35) return null;
  face.geometry = face.geometry.clone();
  const count = face.geometry.attributes.position.count;
  const uv = new Float32Array(count * 2);
  const point = new THREE.Vector3();
  for (let i = 0; i < count; i++) {
    face.getVertexPosition(i, point).applyMatrix4(face.matrixWorld);
    uv[i * 2] = (point.x - bounds.min.x) / size.x;
    uv[i * 2 + 1] = (point.y - bounds.min.y) / size.y;
  }
  face.geometry.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 384;
  const ctx = canvas.getContext("2d");
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  face.material = new THREE.MeshStandardMaterial({
    map: texture, emissiveMap: texture, emissive: 0xffffff,
    emissiveIntensity: 0.65, roughness: 0.42, metalness: 0,
  });
  let state = "standby";
  let elapsed = 0;
  let stateElapsed = 0;
  let nextBlink = 2.8;
  let blinkAt = -10;
  let openness = 1;
  let smile = 0.3;
  let tilt = 0;
  const happy = new Set(["happy", "greeting", "love", "laugh", "celebrate", "excited", "clap", "agree", "proud", "dance", "cheeky", "smirk"]);
  const sad = new Set(["sad", "bored", "awkward", "complain"]);
  function update(delta) {
    elapsed += delta;
    stateElapsed += delta;
    if (elapsed >= nextBlink) {
      blinkAt = elapsed;
      nextBlink = elapsed + 3 + Math.random() * 3;
    }
    const blinkTime = elapsed - blinkAt;
    const blink = blinkTime < 0.18 ? Math.sin(Math.PI * blinkTime / 0.18) : 0;
    // Two deliberate right-eye winks, with an open-eye pause between them.
    // Afterwards both eyes stay open until the reaction finishes.
    const wink = state === "wink";
    const winkClosed = wink
      ? 1 - THREE.MathUtils.smoothstep(stateElapsed, 0.22, 0.4)
        + THREE.MathUtils.smoothstep(stateElapsed, 0.85, 1.0)
          * (1 - THREE.MathUtils.smoothstep(stateElapsed, 1.22, 1.4))
      : 0;
    const sleeping = state === "sleeping";
    const curious = state === "curious" || state === "confused" || state === "thinking";
    const surprised = state === "shock" || state === "panic";
    const blend = 1 - Math.exp(-delta * 9);
    openness += ((sleeping ? 0.04 : sad.has(state) ? 0.65 : 1) - openness) * blend;
    smile += ((happy.has(state) ? 1 : sad.has(state) ? -0.5 : surprised ? 0 : 0.3) - smile) * blend;
    tilt += ((curious ? 1 : state === "angry" ? -1 : 0) - tilt) * blend;
    ctx.fillStyle = "#09131b";
    ctx.fillRect(0, 0, 512, 384);
    ctx.strokeStyle = ctx.fillStyle = "#8eeeff";
    ctx.lineCap = "round";
    ctx.lineWidth = 10;
    ctx.shadowColor = "#40dfff";
    ctx.shadowBlur = 12;
    for (let i = 0; i < 2; i++) {
      const x = i === 0 ? 145 : 367;
      const open = wink ? 1 : Math.max(0.025, openness * (1 - blink));
      const y = 180 + (i === 0 ? -1 : 1) * tilt * 10;
      ctx.beginPath();
      if (happy.has(state) && state !== "greeting" && state !== "agree") {
        ctx.moveTo(x - 30, y + 8);
        ctx.quadraticCurveTo(x, y - 35 * open, x + 30, y + 8);
        ctx.stroke();
      } else if (wink && i === 1) {
        ctx.globalAlpha = 1 - winkClosed;
        ctx.ellipse(x, y, 26, Math.max(2, 36 * (1 - winkClosed)), 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = winkClosed;
        ctx.beginPath();
        ctx.moveTo(x + 20, y - 18);
        ctx.lineTo(x - 15, y);
        ctx.lineTo(x + 20, y + 18);
        ctx.stroke();
        ctx.globalAlpha = 1;
      } else {
        ctx.ellipse(x, y, surprised ? 31 : 26, Math.max(2, (surprised ? 46 : 36) * open), 0, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.beginPath();
      ctx.moveTo(x - 24, y - 65 + tilt * (i === 0 ? -8 : 8));
      ctx.quadraticCurveTo(x, y - 74, x + 24, y - 65 + tilt * (i === 0 ? 8 : -8));
      ctx.stroke();
    }
    ctx.beginPath();
    if (surprised) {
      ctx.ellipse(256, 258, 15, 22, 0, 0, Math.PI * 2);
    } else {
      ctx.moveTo(229, 257);
      ctx.quadraticCurveTo(256, 257 + smile * 38, 283, 257);
    }
    ctx.stroke();
    texture.needsUpdate = true;
  }
  update(0);
  return { setState(value) { state = value; stateElapsed = 0; }, update };
}
