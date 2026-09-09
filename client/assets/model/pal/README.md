# Pal character renderers

The optional `?skin=pal2d` uses the SVG robot in
`client/js/pal-svg-avatar.js`, inspired by the Pal repository logo: rounded
white shell, dark face screen, blue eyes, and antenna. No GLB is required.
Thinking and sleeping keep the feet still; expressions, two-stage winking,
and sleeping Z particles are animated directly in SVG. The renderer retains
the channel's state, gesture-completion, click, and display-mirroring interfaces.

Pal defaults to 3D: `?skin=pal` (also `?skin=pal3d`) is loaded by the local Three.js adapter in
`client/js/pal-webgl-avatar.js`. Three.js and `GLTFLoader` ship with the
desktop-avatar package; the larger GLB remains outside it.

Install a model with:

```bash
python install.py --runtime-root ~/.pal --component channel --force \
  --pal-model /path/to/pal.glb
```

The installer validates the animation contract and writes the model to
`~/.pal/data/desktop_avatar/skins/pal/<sha256>.glb`. The sidecar exposes a
small no-store manifest and serves the content-addressed model URL with an
immutable browser cache policy.

The adapter supports both the original nine-clip model and the newer named
robot model (`Robot_Wave_Pal`, `Robot_Idle_Pal`, etc.). The legacy mapping is:

| Semantic state | GLB clip |
| --- | --- |
| `happy` | `NlaTrack` |
| `laugh` | `NlaTrack.001` |
| `celebrate` | `NlaTrack.002` |
| `panic` | `NlaTrack.003` |
| `clap` | `NlaTrack.004` |
| `agree` | `NlaTrack.005` |
| `greeting` | `NlaTrack.006` |
| `complain` | `NlaTrack.007` |
| `dance` | `NlaTrack.008` |

The adapter keeps the existing sidecar state contract. The named robot model
uses semantic lookup keys throughout: greeting plays `Robot_Wave_Pal`, agree
plays `Robot_Yes_Pal`, and confused uses the quieter `curious` clip. Activity
clips loop except sleeping and thinking, which settle once and hold their last pose.
Repeated notifications for either state do not restart the transition. The robot's
thinking clip is a short (~0.42-second) transition with different start/end leg
poses, so repeating it would snap the lower body back on every loop.
One-shot gestures report completion once. Wave torso/head lean is
softened, with a 0.3-second transition and 0.85 playback speed. Horizontal
root/hip travel is anchored to idle while vertical movement is retained.

Pal no longer uses the CSS canvas transforms intended for Live2D. Orthographic camera
framing samples all selected clips once at load, with edge padding;
state changes do not move the camera, and forward lean does not magnify the model. This intentionally leaves room for
hands and larger poses. Bounds use per-part vertex samples to limit startup
cost; unusually different replacement models may need additional framing.

For the current `pal.glb`, `pal-expressions.js` projects new UVs onto the
separate curved face-screen mesh (`tripo_part_37`) in its rest pose and draws
expressions using a CanvasTexture. Skinning keeps the face attached to the
head. It supports natural blinking, smiles, curious/asymmetric brows, closed
sleeping eyes, winking and sad/surprised reactions. The original GLB and body
texture are unchanged. The feature is guarded by the robot clip signature and
screen dimensions; unrelated models retain their original material.

The named robot has no verified clap or stretching clip. Those states use a
quiet idle pose (clap also smiles); they do not substitute unrelated dancing.
They remain candidates for dedicated authored gestures. User/Pal events still preempt idle actions in
`client/js/main.js`; no animation state is stored in the browser.

The images under `reference/` remain art-direction references:

- `pal-neutral-front.png`: neutral full-body silhouette and materials.
- `pal-action-concept.png`: identity, cookie prop, and mischievous pose.
- `pal-expression-sheet.png`: face-screen expressions.
- `pal-idle-action-sheet.png`: idle and action poses.

The GLB is supplied separately as a project-local asset. Confirm the
applicable model-generation and redistribution terms before publishing it.

Sleeping also shows three reusable, softly fading Z sprites above the head.
They stop immediately on waking; reduced-motion preference shows static Zs.
Repeated sleeping notifications do not restart the settling motion.
