# Third-party notices

This package vendors browser dependencies so the ChromeOS client can run without an external CDN:

- `marked` 12.0.2 — MIT License. The bundled license is in
  `THIRD_PARTY_LICENSES/marked-12.0.2-MIT.md`.
- `DOMPurify` 3.1.6 — Apache License 2.0 or Mozilla Public License 2.0. The bundled license is in
  `THIRD_PARTY_LICENSES/DOMPurify-3.1.6.txt`.
- `three` 0.185.1 — MIT License. The bundled license is in
  `THIRD_PARTY_LICENSES/three-0.185.1-MIT.txt`.
- `KaTeX` 0.16.22 — MIT License. The bundled license is in
  `THIRD_PARTY_LICENSES/katex-0.16.22-MIT.md`. Only `dist/katex.min.js`, `dist/katex.min.css`
  and the `woff2` fonts are vendored under `client/vendor/katex/`.

The generated `client/assets/background/cozy-room.png` and `pal-night-room.png` are project-local artwork created for this client.

The optional Pal GLB character model is a project-local asset supplied separately by the project
owner. It isn't included in this source tree or package; the installer places it in the local runtime
skin cache. Confirm the applicable generation-service and redistribution terms before publishing it.
