import * as THREE from "../vendor/three.module.min.js";
import { GLTFLoader } from "../vendor/three-addons/loaders/GLTFLoader.js";

const PAL_STATE_TO_CLIP = Object.freeze({
  happy: "happy",
  laugh: "laugh",
  celebrate: "celebrate",
  panic: "panic",
  clap: "clap",
  agree: "agree",
  greeting: "greeting",
  complain: "complain",
  dance: "dance",
});

const CLIP_MAP = Object.freeze({
  happy: "NlaTrack",
  laugh: "NlaTrack.001",
  celebrate: "NlaTrack.002",
  panic: "NlaTrack.003",
  clap: "NlaTrack.004",
  agree: "NlaTrack.005",
  greeting: "NlaTrack.006",
  complain: "NlaTrack.007",
  dance: "NlaTrack.008",
});

// The sidecar has a richer semantic state vocabulary than this particular
// model. Keep that public vocabulary stable and route only expressive states
// to their nearest native clip; ordinary activity states continue to use the
// shared wrapper animation in style.css.
const PAL_STATE_ALIASES = Object.freeze({
  sad: "complain",
  angry: "complain",
  shock: "panic",
  wink: "greeting",
  curious: "agree",
  awkward: "complain",
  smirk: "laugh",
  cheeky: "laugh",
  excited: "celebrate",
  shy: "happy",
  proud: "celebrate",
  confused: "panic",
  love: "happy",
  bored: "complain",
  snacking: "happy",
  drinking: "agree",
  stretching: "dance",
});

const SUPPORTED_STATES = new Set([
  "standby", "sleeping", "thinking", "working",
  ...Object.keys(PAL_STATE_TO_CLIP),
  ...Object.keys(PAL_STATE_ALIASES),
]);

const EXPRESSIVE_STATES = new Set([
  ...Object.keys(PAL_STATE_TO_CLIP),
  ...Object.keys(PAL_STATE_ALIASES),
]);

let activeAvatar = null;

function animationStateFor(state) {
  if (Object.hasOwn(PAL_STATE_TO_CLIP, state)) return PAL_STATE_TO_CLIP[state];
  return PAL_STATE_ALIASES[state] || "";
}

function disposeMaterial(material) {
  if (!material) return;
  for (const value of Object.values(material)) {
    if (value && value.isTexture && typeof value.dispose === "function") value.dispose();
  }
  material.dispose?.();
}

class PalWebGLAvatar {
  constructor(container, { onActionFinished } = {}) {
    this.container = container;
    this.onActionFinished = onActionFinished;
    this.state = "standby";
    this.destroyed = false;
    this.ready = false;
    this.mixer = null;
    this.activeAction = null;
    this.clips = new Map();
    this.actions = new Map();
    this.actionStates = new Map();
    this.modelRoot = new THREE.Group();
    this.modelSize = new THREE.Vector3(2.4, 5, 2.4);
    this.pointer = { x: 0, y: 0 };
    this.lastFrameAt = 0;

    this.widget = document.createElement("div");
    this.widget.id = "pal-webgl-widget";
    this.widget.setAttribute("aria-label", "Pal WebGL avatar");
    this.widget.setAttribute("aria-busy", "true");
    this.canvas = document.createElement("canvas");
    this.canvas.id = "pal-webgl-canvas";
    this.loadingStatus = document.createElement("div");
    this.loadingStatus.className = "pal-webgl-loading";
    this.loadingStatus.setAttribute("role", "status");
    this.loadingStatus.setAttribute("aria-live", "polite");
    this.loadingStatus.textContent = "Loading Pal…";
    this.widget.append(this.canvas, this.loadingStatus);
    container.appendChild(this.widget);

    this.handlePointerMove = (event) => {
      const bounds = this.canvas.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      this.pointer.x = THREE.MathUtils.clamp(
        ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
        -1,
        1,
      );
      this.pointer.y = THREE.MathUtils.clamp(
        ((event.clientY - bounds.top) / bounds.height) * 2 - 1,
        -1,
        1,
      );
    };
    this.handlePointerLeave = () => {
      this.pointer.x = 0;
      this.pointer.y = 0;
    };
    this.canvas.addEventListener("pointermove", this.handlePointerMove);
    this.canvas.addEventListener("pointerleave", this.handlePointerLeave);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;

    this.scene = new THREE.Scene();
    this.scene.add(this.modelRoot);
    this.camera = new THREE.PerspectiveCamera(28, 1, 0.01, 100);
    this.scene.add(new THREE.HemisphereLight(0xd9f5ff, 0x111827, 2.8));
    const key = new THREE.DirectionalLight(0xffffff, 4.6);
    key.position.set(-4, 7, 8);
    this.scene.add(key);
    const rim = new THREE.PointLight(0x1acfff, 32, 18, 2);
    rim.position.set(4, 2.5, 5);
    this.scene.add(rim);
    const fill = new THREE.PointLight(0x4169d8, 14, 16, 2);
    fill.position.set(-4, -1.5, 3);
    this.scene.add(fill);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.widget);
    this.resize();
    this.animate = this.animate.bind(this);
    this.animationFrame = requestAnimationFrame(this.animate);
  }

  async load(modelPath) {
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(modelPath, (event) => {
      if (this.destroyed || !this.loadingStatus) return;
      const loaded = Number(event.loaded || 0);
      const total = Number(event.total || 0);
      if (total > 0 && loaded >= 0) {
        const percent = Math.min(100, Math.round((loaded / total) * 100));
        this.loadingStatus.textContent = `Loading Pal… ${percent}%`;
      }
    });
    if (this.destroyed) return this;

    const bounds = new THREE.Box3().setFromObject(gltf.scene);
    if (bounds.isEmpty()) throw new Error("Pal GLB contains no renderable model");
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    if (!Number.isFinite(size.y) || size.y <= 0) {
      throw new Error("Pal GLB has invalid model bounds");
    }

    gltf.scene.position.copy(center).multiplyScalar(-1);
    const normalizedHeight = 5;
    const scale = normalizedHeight / size.y;
    this.modelRoot.scale.setScalar(scale);
    this.modelSize.copy(size).multiplyScalar(scale);
    this.modelRoot.add(gltf.scene);
    this.mixer = new THREE.AnimationMixer(gltf.scene);
    this.mixer.addEventListener("finished", ({ action }) => {
      const state = this.actionStates.get(action);
      if (!state || !EXPRESSIVE_STATES.has(state) || action !== this.activeAction) return;
      this.onActionFinished?.(state);
    });

    const clips = new Map(gltf.animations.map((clip) => [clip.name, clip]));
    for (const [state, clipName] of Object.entries(CLIP_MAP)) {
      const clip = clips.get(clipName);
      if (!clip) throw new Error(`Pal GLB is missing animation clip ${clipName} for ${state}`);
      this.clips.set(state, clip);
    }

    gltf.scene.traverse((object) => {
      if (!object.isMesh) return;
      if (object.material) {
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        materials.forEach((material) => {
          if (material.map) material.map.colorSpace = THREE.SRGBColorSpace;
        });
      }
    });

    this.ready = true;
    this.widget.setAttribute("aria-busy", "false");
    this.loadingStatus.remove();
    this.loadingStatus = null;
    this.resize();
    this.setState(this.state);
    return this;
  }

  setState(value) {
    const requested = String(value || "standby").toLowerCase();
    this.state = SUPPORTED_STATES.has(requested) ? requested : "standby";
    if (!this.ready) return false;
    const animationState = animationStateFor(this.state);
    const nextAction = this.actionFor(animationState);

    if (this.activeAction && this.activeAction !== nextAction) {
      this.activeAction.fadeOut(0.16);
    }
    if (!nextAction) {
      this.activeAction = null;
      return false;
    }
    nextAction.reset();
    nextAction.enabled = true;
    nextAction.setEffectiveTimeScale(1);
    nextAction.setEffectiveWeight(1);
    this.actionStates.set(nextAction, this.state);
    nextAction.fadeIn(0.12).play();
    this.activeAction = nextAction;
    return true;
  }

  actionFor(animationState) {
    if (!animationState || !this.mixer) return null;
    const existing = this.actions.get(animationState);
    if (existing) return existing;
    const clip = this.clips.get(animationState);
    if (!clip) return null;
    const action = this.mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    this.actions.set(animationState, action);
    return action;
  }

  stopMotion() {
    if (!this.activeAction) return;
    this.activeAction.fadeOut(0.12);
    this.activeAction = null;
  }

  resize() {
    const width = Math.max(1, this.widget.clientWidth);
    const height = Math.max(1, this.widget.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;

    const verticalFov = THREE.MathUtils.degToRad(this.camera.fov);
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * this.camera.aspect);
    const heightDistance = this.modelSize.y / (2 * Math.tan(verticalFov / 2));
    const widthDistance = this.modelSize.x / (2 * Math.tan(horizontalFov / 2));
    const distance = Math.max(heightDistance, widthDistance) * 1.12;
    this.camera.position.set(0, 0, distance);
    this.camera.near = Math.max(0.01, distance / 100);
    this.camera.far = Math.max(100, distance * 10);
    this.camera.lookAt(0, 0, 0);
    this.camera.updateProjectionMatrix();
  }

  animate(now) {
    if (this.destroyed) return;
    this.animationFrame = requestAnimationFrame(this.animate);
    const elapsedMs = this.lastFrameAt ? now - this.lastFrameAt : 1000 / 30;
    if (elapsedMs < 1000 / 30) return;
    this.lastFrameAt = now;
    const delta = Math.min(elapsedMs / 1000, 0.1);
    this.mixer?.update(delta);
    this.modelRoot.rotation.x = THREE.MathUtils.lerp(
      this.modelRoot.rotation.x,
      -this.pointer.y * 0.025,
      0.08,
    );
    this.modelRoot.rotation.y = THREE.MathUtils.lerp(
      this.modelRoot.rotation.y,
      this.pointer.x * 0.07,
      0.08,
    );
    this.renderer.render(this.scene, this.camera);
  }

  destroy() {
    this.destroyed = true;
    this.ready = false;
    cancelAnimationFrame(this.animationFrame);
    this.resizeObserver.disconnect();
    this.canvas.removeEventListener("pointermove", this.handlePointerMove);
    this.canvas.removeEventListener("pointerleave", this.handlePointerLeave);
    this.mixer?.stopAllAction();
    this.modelRoot.traverse((object) => {
      object.geometry?.dispose?.();
      if (Array.isArray(object.material)) object.material.forEach(disposeMaterial);
      else disposeMaterial(object.material);
    });
    this.renderer.dispose();
    this.widget.remove();
  }
}

export async function initPalWebGLAvatar({ container, modelPath, onActionFinished }) {
  if (!container) throw new Error("Pal WebGL avatar requires an avatar-stage container");
  if (!modelPath) throw new Error("Pal WebGL avatar requires a GLB model path");
  if (activeAvatar) activeAvatar.destroy();
  const avatar = new PalWebGLAvatar(container, { onActionFinished });
  activeAvatar = avatar;
  window.PalWebGLAvatar = {
    setState: (state) => activeAvatar?.setState(state),
    startMotion: (group) => activeAvatar?.setState(group),
    stopMotion: () => activeAvatar?.stopMotion(),
    motionReady: () => !!activeAvatar?.ready,
    destroy: () => {
      const current = activeAvatar;
      activeAvatar = null;
      current?.destroy();
    },
  };
  try {
    await avatar.load(modelPath);
  } catch (error) {
    avatar.destroy();
    if (activeAvatar === avatar) activeAvatar = null;
    throw error;
  }
  return avatar;
}
