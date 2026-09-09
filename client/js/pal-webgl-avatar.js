import * as THREE from "../vendor/three.module.min.js";
import { GLTFLoader } from "../vendor/three-addons/loaders/GLTFLoader.js";

import { createPalExpressions } from "./pal-expressions.js";
import { createPalSleepParticles } from "./pal-sleep-particles.js";

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

const LEGACY_STATE_ALIASES = Object.freeze({
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

// Named clips in the current robot model. Keep the legacy nine-clip model
// supported, but use one semantic key consistently throughout the adapter.
const ROBOT_CLIPS = Object.freeze({
  standby: "Robot_Idle_Pal", sleeping: "sleepy",
  thinking: "thinking", working: "working",
  happy: "NlaTrack", laugh: "NlaTrack", celebrate: "Robot_Dance_Pal",
  greeting: "Robot_Wave_Pal", agree: "Robot_Yes_Pal", proud: "Robot_ThumbsUp_Pal",
  dance: "Robot_Dance_Pal", excited: "excited", angry: "angry",
  bored: "bored", awkward: "awkward", curious: "curious",
  shock: "shock", panic: "shock", complain: "Idle_No_Loop",
  snacking: "snacking", drinking: "drinking",
  sad: "bored", confused: "curious", shy: "awkward",
  love: "Robot_Idle_Pal", wink: "Robot_Idle_Pal",
  smirk: "Robot_Idle_Pal", cheeky: "Robot_Idle_Pal",
  stretching: "Robot_Idle_Pal", clap: "Robot_Idle_Pal",
});
const PERSISTENT_STATES = new Set(["standby", "sleeping", "thinking", "working"]);
// These clips are pose transitions, not seamless activity loops. In the
// robot GLB, thinking is only ~0.42s and its leg poses differ at each end.
const HOLD_POSE_STATES = new Set(["sleeping", "thinking"]);
const SUPPORTED_STATES = new Set(Object.keys(ROBOT_CLIPS));
const EXPRESSIVE_STATES = new Set([...SUPPORTED_STATES].filter((state) => !PERSISTENT_STATES.has(state)));
let activeAvatar = null;

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
    this.modelRoot = new THREE.Group();
    this.modelSize = new THREE.Vector3(2.4, 5, 2.4);
    this.pointer = { x: 0, y: 0 };
    this.lastFrameAt = 0;
    this.stateElapsed = 0;
    this.completionSent = false;

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
    this.camera = new THREE.OrthographicCamera(-3, 3, 3, -3, 0.01, 100);
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

    this.expressions = createPalExpressions(gltf.scene, gltf.animations);
    gltf.scene.position.copy(center).multiplyScalar(-1);
    const normalizedHeight = 5;
    const scale = normalizedHeight / size.y;
    this.modelRoot.scale.setScalar(scale);
    this.modelSize.copy(size).multiplyScalar(scale);
    this.modelRoot.add(gltf.scene);
    this.mixer = new THREE.AnimationMixer(gltf.scene);
    this.mixer.addEventListener("finished", ({ action }) => {
      if (action !== this.activeAction || !EXPRESSIVE_STATES.has(this.state)) return;
      this.finishAction();
    });
    const clips = new Map(gltf.animations.map((clip) => [clip.name, clip]));
    const isRobot = clips.has("Robot_Wave_Pal");
    const mapping = isRobot ? ROBOT_CLIPS : {
      ...CLIP_MAP,
      ...Object.fromEntries(Object.entries(LEGACY_STATE_ALIASES)
        .map(([state, target]) => [state, CLIP_MAP[target]])),
    };
    for (const [state, clipName] of Object.entries(mapping)) {
      const original = clips.get(clipName);
      if (!original) continue;
      const clip = original.clone();
      const idle = clips.get("Robot_Idle_Pal");
      // Desktop gestures stay in place. Preserve vertical hip movement and
      // joint rotations, but remove travel toward/away from the viewer.
      if (isRobot) {
        for (const track of clip.tracks) {
          if (track.name === "Root.position" || track.name === "Hip.position") {
            // Root/Hip local coordinates in this rig use Z for height.
            const anchor = idle?.tracks.find((item) => item.name === track.name)?.values || track.values;
            for (let i = 0; i < track.values.length; i += 3) {
              track.values[i] = anchor[0];
              track.values[i + 1] = anchor[1];
            }
          }
          // Keep the wave in the arm; soften the imported torso/head lean.
          if (clipName === "Robot_Wave_Pal" && /^(Head|NeckTwist01|NeckTwist02|Spine02)\.quaternion$/.test(track.name)) {
            const rest = idle?.tracks.find((item) => item.name === track.name);
            if (!rest) continue;
            const base = new THREE.Quaternion().fromArray(rest.values);
            const pose = new THREE.Quaternion();
            for (let i = 0; i < track.values.length; i += 4) {
              pose.fromArray(track.values, i);
              pose.slerpQuaternions(base, pose, 0.65).toArray(track.values, i);
            }
          }
        }
      }
      this.clips.set(state, clip);
    }
    if (!this.clips.size) throw new Error("Pal GLB has no supported animation clips");
    this.isRobot = isRobot;
    this.fitAnimationBounds(gltf.scene);
    this.sleepParticles = createPalSleepParticles(gltf.scene);

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
    // Repeated state notifications must not replay a settling transition.
    if (HOLD_POSE_STATES.has(requested) && this.state === requested && this.ready && this.activeAction) return true;
    this.state = SUPPORTED_STATES.has(requested) ? requested : "standby";
    if (!this.ready) return false;
    this.stateElapsed = 0;
    this.completionSent = false;
    this.expressions?.setState(this.state);
    this.sleepParticles?.setSleeping(this.state === "sleeping");
    const nextAction = this.actionFor(this.state);

    if (this.activeAction && this.activeAction !== nextAction) {
      this.activeAction.fadeOut(0.3);
    }
    if (!nextAction) {
      this.activeAction = null;
      return false;
    }
    nextAction.reset();
    nextAction.enabled = true;
    nextAction.setEffectiveTimeScale(this.state === "greeting" ? 0.85 : 1);
    nextAction.setEffectiveWeight(1);
    nextAction.fadeIn(0.3).play();
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
    // Pose transitions remain persistent states after settling once.
    const repeat = PERSISTENT_STATES.has(animationState) && !HOLD_POSE_STATES.has(animationState);
    action.setLoop(repeat ? THREE.LoopRepeat : THREE.LoopOnce, repeat ? Infinity : 1);
    action.clampWhenFinished = true;
    this.actions.set(animationState, action);
    return action;
  }

  finishAction() {
    if (this.completionSent) return;
    this.completionSent = true;
    this.onActionFinished?.(this.state);
  }

  stopMotion() {
    this.setState("standby");
  }

  fitAnimationBounds(model) {
    // Fit once to the union of supported poses, never zoom during a gesture.
    const bounds = new THREE.Box3().setFromObject(this.modelRoot, true);
    const point = new THREE.Vector3();
    const meshes = [];
    model.traverse((mesh) => {
      if (!mesh.isMesh) return;
      // Sampling each individual part includes small features (antenna/hands)
      // without reskinning every vertex of the GLB hundreds of times at load.
      const count = mesh.geometry.attributes.position.count;
      const indices = new Set([0, count - 1]);
      const stride = Math.max(1, Math.floor(count / 64));
      for (let i = 0; i < count; i += stride) indices.add(i);
      meshes.push({ mesh, indices });
    });
    const sampled = new Set();
    for (const clip of this.clips.values()) {
      if (sampled.has(clip.name)) continue;
      sampled.add(clip.name);
      const action = this.mixer.clipAction(clip).play();
      for (let frame = 0; frame <= 16; frame++) {
        action.time = clip.duration * frame / 16;
        this.mixer.update(0);
        model.updateMatrixWorld(true);
        for (const { mesh, indices } of meshes) {
          for (const index of indices) {
            mesh.getVertexPosition(index, point).applyMatrix4(mesh.matrixWorld);
            bounds.expandByPoint(point);
          }
        }
      }
      action.stop();
      this.mixer.uncacheAction(clip);
    }
    model.updateMatrixWorld(true);
    bounds.expandByScalar(0.12);
    this.frameCenter = bounds.getCenter(new THREE.Vector3());
    this.modelSize.copy(bounds.getSize(new THREE.Vector3()));
  }

  resize() {
    const width = Math.max(1, this.widget.clientWidth);
    const height = Math.max(1, this.widget.clientHeight);
    this.renderer.setSize(width, height, false);
    // Orthographic projection keeps the desktop companion's apparent size
    // stable when an authored gesture leans toward the viewer.
    const aspect = width / height;
    const halfHeight = Math.max(this.modelSize.y / 2, this.modelSize.x / (2 * aspect)) * 1.08;
    this.camera.left = -halfHeight * aspect;
    this.camera.right = halfHeight * aspect;
    this.camera.top = halfHeight;
    this.camera.bottom = -halfHeight;
    const distance = Math.max(10, this.modelSize.z * 2);
    const center = this.frameCenter || new THREE.Vector3();
    this.camera.position.set(center.x, center.y, center.z + distance);
    this.camera.near = 0.01;
    this.camera.far = Math.max(100, distance * 4);
    this.camera.lookAt(center);
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
    this.stateElapsed += delta;
    this.expressions?.update(delta);
    this.sleepParticles?.update(delta);
    // Face-only reactions and missing optional clips still acknowledge completion.
    if (EXPRESSIVE_STATES.has(this.state) && !this.activeAction && this.stateElapsed >= 1.8) this.finishAction();
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
    this.sleepParticles?.destroy();
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
