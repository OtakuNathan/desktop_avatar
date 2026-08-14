# Pal WebGL model

Pal's `?skin=pal` character is a procedural full-body Three.js model implemented
in `client/js/pal-webgl-avatar.js`. It is rendered locally with WebGL and does not
depend on Live2D, Cubism, a CDN, voice assets, or a remote model service.

The images under `reference/` are generated art direction references:

- `pal-neutral-front.png`: neutral full-body silhouette and materials.
- `pal-action-concept.png`: identity, cookie prop, and mischievous pose.
- `pal-expression-sheet.png`: face-screen expressions.
- `pal-idle-action-sheet.png`: idle and action poses.

The current model builds its helmet, face screen, antenna, torso, articulated
arms and legs, chest core, cookie, and drink from Three.js geometry. A dynamic
canvas texture renders Pal's cyan face. The same semantic state names used by
the sidecar drive both face expressions and articulated body poses:

```text
standby sleeping thinking working happy sad angry shock wink curious awkward
smirk cheeky excited shy proud confused love panic bored greeting celebrate
snacking drinking stretching
```

This directory remains the stable location for model references. A future GLB
artist model can replace the procedural mesh behind the same WebGL adapter and
state contract without changing the sidecar, history, checklist, chat protocol,
interaction handling, or notification beep.
