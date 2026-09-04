# Pal GLB model

Pal's `?skin=pal` character is loaded by the local Three.js adapter in
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

The model exposes nine animation clips:

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

The adapter keeps the existing sidecar state contract. States without an
exact native clip either map to the nearest expressive animation or retain
the shared CSS activity motion. User/Pal events still preempt idle actions in
`client/js/main.js`; no animation state is stored in the browser.

The images under `reference/` remain art-direction references:

- `pal-neutral-front.png`: neutral full-body silhouette and materials.
- `pal-action-concept.png`: identity, cookie prop, and mischievous pose.
- `pal-expression-sheet.png`: face-screen expressions.
- `pal-idle-action-sheet.png`: idle and action poses.

The GLB is supplied separately as a project-local asset. Confirm the
applicable model-generation and redistribution terms before publishing it.
