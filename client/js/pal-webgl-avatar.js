import * as THREE from "../vendor/three.module.min.js";

const FACE_SIZE = 512;
const SUPPORTED_STATES = new Set([
  "standby", "sleeping", "thinking", "working", "happy", "sad", "angry",
  "shock", "wink", "curious", "awkward", "smirk", "cheeky", "excited",
  "shy", "proud", "confused", "love", "panic", "bored", "greeting",
  "celebrate", "snacking", "drinking", "stretching",
]);

let activeAvatar = null;

function drawFace(context, state) {
  const cyan = "#43ddff";
  const cyanDim = "rgba(67, 221, 255, 0.55)";
  const pink = "#ff73bd";
  context.clearRect(0, 0, FACE_SIZE, FACE_SIZE);

  context.save();
  context.shadowColor = cyan;
  context.shadowBlur = 24;
  context.lineCap = "round";
  context.lineJoin = "round";

  const eye = (x, y, mode = "open") => {
    context.strokeStyle = cyan;
    context.fillStyle = cyan;
    context.lineWidth = 18;
    if (mode === "closed") {
      context.beginPath();
      context.arc(x, y + 12, 55, Math.PI * 1.08, Math.PI * 1.92);
      context.stroke();
    } else if (mode === "sad") {
      context.beginPath();
      context.arc(x, y - 12, 53, Math.PI * 0.14, Math.PI * 0.86);
      context.stroke();
    } else if (mode === "angry-left" || mode === "angry-right") {
      context.beginPath();
      const direction = mode.endsWith("left") ? 1 : -1;
      context.moveTo(x - 52, y - 24 * direction);
      context.quadraticCurveTo(x, y + 9, x + 52, y + 24 * direction);
      context.stroke();
    } else if (mode === "wide") {
      context.beginPath();
      context.ellipse(x, y, 52, 70, 0, 0, Math.PI * 2);
      context.stroke();
      context.beginPath();
      context.arc(x, y + 6, 17, 0, Math.PI * 2);
      context.fill();
    } else if (mode === "dot") {
      context.beginPath();
      context.arc(x, y, 20, 0, Math.PI * 2);
      context.fill();
    } else {
      context.beginPath();
      context.ellipse(x, y, 48, 59, 0, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = "#d9fbff";
      context.shadowBlur = 8;
      context.beginPath();
      context.arc(x - 13, y - 17, 11, 0, Math.PI * 2);
      context.fill();
      context.shadowBlur = 24;
      context.fillStyle = cyan;
    }
  };

  const mouth = (mode = "smile") => {
    context.strokeStyle = cyan;
    context.fillStyle = cyan;
    context.lineWidth = 14;
    if (mode === "smile") {
      context.beginPath();
      context.arc(256, 302, 48, 0.18 * Math.PI, 0.82 * Math.PI);
      context.stroke();
    } else if (mode === "grin") {
      context.beginPath();
      context.arc(256, 288, 73, 0.12 * Math.PI, 0.88 * Math.PI);
      context.stroke();
    } else if (mode === "sad") {
      context.beginPath();
      context.arc(256, 357, 44, 1.16 * Math.PI, 1.84 * Math.PI);
      context.stroke();
    } else if (mode === "o") {
      context.beginPath();
      context.ellipse(256, 318, 28, 38, 0, 0, Math.PI * 2);
      context.stroke();
    } else if (mode === "flat") {
      context.beginPath();
      context.moveTo(219, 319);
      context.lineTo(293, 319);
      context.stroke();
    } else if (mode === "smirk") {
      context.beginPath();
      context.moveTo(212, 318);
      context.quadraticCurveTo(265, 343, 314, 291);
      context.stroke();
    } else if (mode === "tongue") {
      context.beginPath();
      context.arc(256, 282, 62, 0.1 * Math.PI, 0.9 * Math.PI);
      context.stroke();
      context.fillStyle = pink;
      context.shadowColor = pink;
      context.beginPath();
      context.ellipse(280, 337, 20, 30, -0.2, 0, Math.PI * 2);
      context.fill();
    }
  };

  let left = "open";
  let right = "open";
  let mouthMode = "smile";
  if (["sleeping", "happy", "shy", "love", "snacking"].includes(state)) left = right = "closed";
  if (state === "wink" || state === "cheeky") right = "closed";
  if (state === "sad") left = right = "sad";
  if (state === "angry") { left = "angry-left"; right = "angry-right"; }
  if (["shock", "panic", "excited"].includes(state)) left = right = "wide";
  if (["bored", "awkward"].includes(state)) left = right = "dot";
  if (state === "sad") mouthMode = "sad";
  if (["shock", "panic", "confused", "drinking"].includes(state)) mouthMode = "o";
  if (["thinking", "working", "bored", "awkward"].includes(state)) mouthMode = "flat";
  if (["smirk", "proud"].includes(state)) mouthMode = "smirk";
  if (state === "cheeky") mouthMode = "tongue";
  if (["happy", "excited", "greeting", "celebrate", "love"].includes(state)) mouthMode = "grin";

  const eyeY = state === "bored" ? 220 : 205;
  eye(166, eyeY, left);
  eye(346, eyeY, right);
  mouth(mouthMode);

  if (["shy", "awkward", "love"].includes(state)) {
    context.shadowColor = pink;
    context.shadowBlur = 18;
    context.strokeStyle = pink;
    context.lineWidth = 9;
    for (const x of [104, 370]) {
      context.beginPath();
      context.moveTo(x, 296);
      context.lineTo(x + 18, 281);
      context.moveTo(x + 18, 300);
      context.lineTo(x + 36, 285);
      context.stroke();
    }
  }

  if (state === "love") {
    context.fillStyle = pink;
    context.font = "bold 58px system-ui";
    context.fillText("♥", 231, 392);
  } else if (state === "thinking" || state === "curious") {
    context.fillStyle = cyanDim;
    context.font = "bold 54px system-ui";
    context.fillText("?", 414, 127);
  } else if (state === "working") {
    context.fillStyle = cyanDim;
    for (let index = 0; index < 3; index += 1) {
      context.fillRect(203 + index * 41, 380, 25, 10 + index * 11);
    }
  }
  context.restore();
}

function roundedArmorGeometry(width, height, depth, radius) {
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  const shape = new THREE.Shape();
  shape.moveTo(-halfWidth + radius, -halfHeight);
  shape.lineTo(halfWidth - radius, -halfHeight);
  shape.quadraticCurveTo(halfWidth, -halfHeight, halfWidth, -halfHeight + radius);
  shape.lineTo(halfWidth, halfHeight - radius);
  shape.quadraticCurveTo(halfWidth, halfHeight, halfWidth - radius, halfHeight);
  shape.lineTo(-halfWidth + radius, halfHeight);
  shape.quadraticCurveTo(-halfWidth, halfHeight, -halfWidth, halfHeight - radius);
  shape.lineTo(-halfWidth, -halfHeight + radius);
  shape.quadraticCurveTo(-halfWidth, -halfHeight, -halfWidth + radius, -halfHeight);
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: true,
    bevelSegments: 4,
    bevelSize: 0.055,
    bevelThickness: 0.055,
    curveSegments: 8,
  });
  geometry.center();
  return geometry;
}

function createPalModel(scene) {
  const pearl = new THREE.MeshPhysicalMaterial({
    color: 0xeaf2f6,
    roughness: 0.43,
    metalness: 0.12,
    clearcoat: 0.42,
    clearcoatRoughness: 0.32,
  });
  const pearlDark = new THREE.MeshPhysicalMaterial({
    color: 0x9eadb8,
    roughness: 0.28,
    metalness: 0.58,
    clearcoat: 0.72,
  });
  const joint = new THREE.MeshStandardMaterial({ color: 0x101923, roughness: 0.38, metalness: 0.72 });
  const blackGlass = new THREE.MeshPhysicalMaterial({ color: 0x01060a, roughness: 0.08, metalness: 0.48, clearcoat: 1 });
  const cyan = new THREE.MeshStandardMaterial({ color: 0x39d9ff, emissive: 0x008fc4, emissiveIntensity: 3.3, roughness: 0.2 });
  const root = new THREE.Group();
  root.position.y = -0.35;
  scene.add(root);

  const sphere = (material, scale, position, parent = root, segments = 32) => {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, segments, Math.max(16, segments / 2)), material);
    mesh.scale.set(...scale);
    mesh.position.set(...position);
    parent.add(mesh);
    return mesh;
  };
  const capsule = (material, radius, length, position, parent) => {
    const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(radius, length, 8, 20), material);
    mesh.position.set(...position);
    parent.add(mesh);
    return mesh;
  };

  const torso = new THREE.Mesh(roundedArmorGeometry(0.96, 1.08, 0.52, 0.17), pearl);
  torso.position.set(0, 0.34, 0);
  root.add(torso);
  const chestPlate = new THREE.Mesh(roundedArmorGeometry(0.72, 0.72, 0.06, 0.13), pearlDark);
  chestPlate.position.set(0, 0.38, 0.32);
  root.add(chestPlate);
  sphere(joint, [0.39, 0.18, 0.3], [0, -0.34, 0]);
  const pelvis = new THREE.Mesh(roundedArmorGeometry(0.68, 0.34, 0.48, 0.12), pearl);
  pelvis.position.set(0, -0.57, 0);
  root.add(pelvis);

  const chestCore = new THREE.Group();
  chestCore.position.set(0, 0.38, 0.39);
  root.add(chestCore);
  const coreRing = new THREE.Mesh(new THREE.TorusGeometry(0.26, 0.075, 16, 48), pearlDark);
  chestCore.add(coreRing);
  sphere(cyan, [0.17, 0.17, 0.08], [0, 0, 0.035], chestCore, 24);

  const neck = sphere(joint, [0.29, 0.22, 0.27], [0, 1.11, 0]);
  const head = new THREE.Group();
  head.position.set(0, 2.09, 0);
  root.add(head);
  sphere(pearl, [1.55, 1.16, 1.04], [0, 0, 0], head);
  sphere(blackGlass, [1.25, 0.83, 0.94], [0, -0.05, 0.35], head);

  const faceCanvas = document.createElement("canvas");
  faceCanvas.width = FACE_SIZE;
  faceCanvas.height = FACE_SIZE;
  const faceContext = faceCanvas.getContext("2d");
  const faceTexture = new THREE.CanvasTexture(faceCanvas);
  faceTexture.colorSpace = THREE.SRGBColorSpace;
  const faceMaterial = new THREE.MeshBasicMaterial({ map: faceTexture, transparent: true, toneMapped: false });
  const faceGeometry = new THREE.PlaneGeometry(2.18, 1.58, 24, 18);
  const facePositions = faceGeometry.attributes.position;
  for (let index = 0; index < facePositions.count; index += 1) {
    const x = facePositions.getX(index) / 1.09;
    const y = facePositions.getY(index) / 0.79;
    facePositions.setZ(index, -0.14 * (x * x + y * y * 0.45));
  }
  faceGeometry.computeVertexNormals();
  const face = new THREE.Mesh(faceGeometry, faceMaterial);
  // Keep the animated face just in front of the curved glass shell. Placing
  // it inside the shell lets the glass surface occlude the mouth at center.
  face.position.set(0, -0.06, 1.3);
  head.add(face);

  for (const side of [-1, 1]) {
    const ear = new THREE.Group();
    ear.position.set(side * 1.5, 0.02, 0);
    head.add(ear);
    const shell = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.26, 32), pearl);
    shell.rotation.z = Math.PI / 2;
    ear.add(shell);
    const glow = new THREE.Mesh(new THREE.CylinderGeometry(0.31, 0.31, 0.285, 32), cyan);
    glow.rotation.z = Math.PI / 2;
    glow.position.x = side * 0.02;
    ear.add(glow);
  }

  const antenna = new THREE.Group();
  antenna.position.set(0.46, 1.08, 0);
  antenna.rotation.z = -0.17;
  head.add(antenna);
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.065, 0.7, 12), pearlDark);
  stem.position.y = 0.34;
  antenna.add(stem);
  sphere(cyan, [0.14, 0.14, 0.14], [0, 0.75, 0], antenna, 24);

  const armGroups = {};
  for (const [name, side] of [["left", -1], ["right", 1]]) {
    const shoulder = new THREE.Group();
    shoulder.position.set(side * 0.62, 0.71, 0);
    root.add(shoulder);
    sphere(joint, [0.29, 0.29, 0.31], [0, 0, 0], shoulder);
    sphere(pearl, [0.25, 0.25, 0.27], [0, -0.06, 0], shoulder);
    capsule(pearl, 0.22, 0.46, [0, -0.41, 0], shoulder);
    const elbow = new THREE.Group();
    elbow.position.set(0, -0.79, 0);
    shoulder.add(elbow);
    sphere(joint, [0.2, 0.2, 0.21], [0, 0, 0], elbow);
    capsule(pearl, 0.2, 0.43, [0, -0.38, 0], elbow);
    const hand = sphere(pearl, [0.27, 0.31, 0.23], [0, -0.75, 0.03], elbow);
    armGroups[name] = { shoulder, elbow, hand, side };
  }

  const legGroups = {};
  for (const [name, side] of [["left", -1], ["right", 1]]) {
    const hip = new THREE.Group();
    hip.position.set(side * 0.27, -0.75, 0);
    root.add(hip);
    sphere(joint, [0.23, 0.22, 0.23], [0, 0, 0], hip);
    capsule(pearl, 0.24, 0.58, [0, -0.51, 0], hip);
    const knee = new THREE.Group();
    knee.position.set(0, -0.96, 0);
    hip.add(knee);
    sphere(joint, [0.22, 0.21, 0.22], [0, 0, 0], knee);
    capsule(pearl, 0.23, 0.55, [0, -0.49, 0], knee);
    const foot = sphere(pearl, [0.34, 0.25, 0.5], [0, -0.91, 0.18], knee);
    legGroups[name] = { hip, knee, foot, side };
  }

  const cookie = new THREE.Group();
  cookie.visible = false;
  cookie.position.set(0.58, -0.12, 0.5);
  root.add(cookie);
  const cookieMaterial = new THREE.MeshStandardMaterial({ color: 0x9d5527, roughness: 0.82 });
  const cookieMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.1, 32), cookieMaterial);
  cookieMesh.rotation.x = Math.PI / 2;
  cookie.add(cookieMesh);
  for (const [x, y] of [[-0.12, 0.08], [0.12, 0.14], [0.06, -0.12], [-0.14, -0.11]]) {
    sphere(joint, [0.045, 0.045, 0.025], [x, y, 0.07], cookie, 12);
  }

  const cup = new THREE.Group();
  cup.visible = false;
  cup.position.set(0.66, -0.08, 0.48);
  root.add(cup);
  const cupMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.21, 0.58, 24), cyan);
  cup.add(cupMesh);
  const straw = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.72, 8), pearl);
  straw.position.set(0.08, 0.56, 0);
  straw.rotation.z = -0.13;
  cup.add(straw);

  drawFace(faceContext, "standby");
  faceTexture.needsUpdate = true;
  return { root, head, armGroups, legGroups, cookie, cup, faceContext, faceTexture, neck };
}

class PalWebGLAvatar {
  constructor(container) {
    this.container = container;
    this.state = "standby";
    this.stateStartedAt = performance.now();
    this.destroyed = false;

    this.widget = document.createElement("div");
    this.widget.id = "pal-webgl-widget";
    this.widget.setAttribute("aria-label", "Pal WebGL avatar");
    this.canvas = document.createElement("canvas");
    this.canvas.id = "pal-webgl-canvas";
    this.widget.appendChild(this.canvas);
    container.appendChild(this.widget);
    this.pointer = { x: 0, y: 0 };
    this.handlePointerMove = (event) => {
      const bounds = this.canvas.getBoundingClientRect();
      this.pointer.x = THREE.MathUtils.clamp(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -1, 1);
      this.pointer.y = THREE.MathUtils.clamp(((event.clientY - bounds.top) / bounds.height) * 2 - 1, -1, 1);
    };
    this.handlePointerLeave = () => { this.pointer.x = 0; this.pointer.y = 0; };
    this.canvas.addEventListener("pointermove", this.handlePointerMove);
    this.canvas.addEventListener("pointerleave", this.handlePointerLeave);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, alpha: true, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(28, 1, 0.1, 100);
    this.camera.position.set(0, 0.15, 16);
    this.camera.lookAt(0, 0.15, 0);
    this.scene.add(new THREE.HemisphereLight(0xc8efff, 0x111520, 2.4));
    const key = new THREE.DirectionalLight(0xffffff, 4.4);
    key.position.set(-4, 6, 7);
    this.scene.add(key);
    const rim = new THREE.PointLight(0x1acfff, 28, 16, 2);
    rim.position.set(3.2, 1.8, 3.8);
    this.scene.add(rim);
    const fill = new THREE.PointLight(0x4169d8, 12, 14, 2);
    fill.position.set(-3, -1.5, 2);
    this.scene.add(fill);

    this.model = createPalModel(this.scene);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.widget);
    this.resize();
    this.animate = this.animate.bind(this);
    this.animationFrame = requestAnimationFrame(this.animate);
  }

  setState(value) {
    const normalized = SUPPORTED_STATES.has(String(value)) ? String(value) : "standby";
    if (normalized !== this.state) this.stateStartedAt = performance.now();
    this.state = normalized;
    drawFace(this.model.faceContext, normalized);
    this.model.faceTexture.needsUpdate = true;
    this.model.cookie.visible = normalized === "snacking";
    this.model.cup.visible = normalized === "drinking";
  }

  resize() {
    const width = Math.max(1, this.widget.clientWidth);
    const height = Math.max(1, this.widget.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  animate(now) {
    if (this.destroyed) return;
    const t = now / 1000;
    const elapsed = (now - this.stateStartedAt) / 1000;
    const { root, head, armGroups, legGroups, cookie, cup } = this.model;
    const left = armGroups.left;
    const right = armGroups.right;
    const lerp = THREE.MathUtils.lerp;
    const rate = 0.12;
    const targets = {
      rootY: -0.35 + Math.sin(t * 2.1) * 0.025,
      rootX: 0,
      rootZ: 0,
      headX: -this.pointer.y * 0.06,
      headY: this.pointer.x * 0.13,
      headZ: 0,
      leftShoulderX: 0.04,
      leftShoulderZ: -0.08,
      leftElbowX: 0,
      leftElbowZ: 0,
      rightShoulderX: 0.04,
      rightShoulderZ: 0.08,
      rightElbowX: 0,
      rightElbowZ: 0,
    };

    if (this.state === "sleeping") { targets.headZ = -0.12; targets.headX = 0.1; targets.rootY -= 0.1; }
    if (this.state === "thinking" || this.state === "curious") { targets.headZ = -0.14; targets.headY = 0.16; targets.rightShoulderZ = 0.72; targets.rightElbowZ = 1.45; }
    if (this.state === "working") { targets.headX = 0.12; targets.leftShoulderZ = -0.3; targets.rightShoulderZ = 0.3; }
    if (this.state === "sad" || this.state === "bored") { targets.headX = 0.14; targets.headZ = -0.08; targets.rootY -= 0.1; }
    if (this.state === "angry" || this.state === "panic") { targets.rootZ = Math.sin(elapsed * 24) * 0.035; targets.leftShoulderZ = -0.55; targets.rightShoulderZ = 0.55; }
    if (this.state === "shock") { targets.rootY += Math.sin(Math.min(elapsed, 0.6) * Math.PI) * 0.22; }
    if (["happy", "excited", "celebrate"].includes(this.state)) { targets.rootY += Math.abs(Math.sin(elapsed * 5)) * 0.12; }
    if (["smirk", "cheeky", "proud"].includes(this.state)) { targets.headZ = 0.12; targets.headY = -0.16; targets.rootZ = 0.04; }
    if (this.state === "awkward" || this.state === "shy") { targets.headZ = -0.1; targets.rootX = -0.05; targets.leftShoulderZ = -0.35; targets.rightShoulderZ = 0.35; }
    if (this.state === "confused") { targets.headZ = Math.sin(elapsed * 3.4) * 0.15; }
    if (this.state === "love") { targets.leftShoulderZ = -0.65; targets.rightShoulderZ = 0.65; targets.leftElbowZ = -1.2; targets.rightElbowZ = 1.2; }
    if (this.state === "greeting") { targets.rightShoulderZ = 2.25; targets.rightElbowZ = 0.55 + Math.sin(elapsed * 8) * 0.35; }
    if (this.state === "celebrate") { targets.leftShoulderZ = -2.45; targets.rightShoulderZ = 2.45; targets.leftElbowZ = -0.25; targets.rightElbowZ = 0.25; }
    if (this.state === "stretching") { targets.leftShoulderZ = -2.7; targets.rightShoulderZ = 2.7; targets.headX = -0.08; }
    if (this.state === "snacking") { targets.rightShoulderZ = 0.78; targets.rightElbowZ = 1.35 + Math.sin(elapsed * 5) * 0.16; cookie.position.y = 0.55 + Math.sin(elapsed * 5) * 0.08; }
    if (this.state === "drinking") { targets.rightShoulderZ = 0.82; targets.rightElbowZ = 1.44; cup.position.y = 0.65; cup.rotation.z = -0.16; }

    root.position.y = lerp(root.position.y, targets.rootY, rate);
    root.rotation.x = lerp(root.rotation.x, targets.rootX, rate);
    root.rotation.z = lerp(root.rotation.z, targets.rootZ, rate);
    head.rotation.x = lerp(head.rotation.x, targets.headX, rate);
    head.rotation.y = lerp(head.rotation.y, targets.headY, rate);
    head.rotation.z = lerp(head.rotation.z, targets.headZ, rate);
    left.shoulder.rotation.x = lerp(left.shoulder.rotation.x, targets.leftShoulderX, rate);
    left.shoulder.rotation.z = lerp(left.shoulder.rotation.z, targets.leftShoulderZ, rate);
    left.elbow.rotation.z = lerp(left.elbow.rotation.z, targets.leftElbowZ, rate);
    right.shoulder.rotation.x = lerp(right.shoulder.rotation.x, targets.rightShoulderX, rate);
    right.shoulder.rotation.z = lerp(right.shoulder.rotation.z, targets.rightShoulderZ, rate);
    right.elbow.rotation.z = lerp(right.elbow.rotation.z, targets.rightElbowZ, rate);
    legGroups.left.hip.rotation.z = Math.sin(t * 1.4) * 0.012;
    legGroups.right.hip.rotation.z = -Math.sin(t * 1.4) * 0.012;
    this.renderer.render(this.scene, this.camera);
    this.animationFrame = requestAnimationFrame(this.animate);
  }

  destroy() {
    this.destroyed = true;
    cancelAnimationFrame(this.animationFrame);
    this.resizeObserver.disconnect();
    this.canvas.removeEventListener("pointermove", this.handlePointerMove);
    this.canvas.removeEventListener("pointerleave", this.handlePointerLeave);
    this.renderer.dispose();
    this.widget.remove();
  }
}

export function initPalWebGLAvatar({ container }) {
  if (!container) throw new Error("Pal WebGL avatar requires an avatar-stage container");
  if (activeAvatar) activeAvatar.destroy();
  activeAvatar = new PalWebGLAvatar(container);
  window.PalWebGLAvatar = {
    setState: (state) => activeAvatar?.setState(state),
    startMotion: (group) => activeAvatar?.setState(group),
    stopMotion: () => undefined,
    motionReady: () => !!activeAvatar,
    destroy: () => activeAvatar?.destroy(),
  };
  return activeAvatar;
}
