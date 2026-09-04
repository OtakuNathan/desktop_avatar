from __future__ import annotations

import hashlib
import json
from pathlib import Path

from websockets.datastructures import Headers
from websockets.http11 import Request

from server.sidecar import serve_client_asset


def _install_cached_model(cache_root: Path, body: bytes = b"glTF-local-model") -> str:
    digest = hashlib.sha256(body).hexdigest()
    pal_root = cache_root / "pal"
    pal_root.mkdir(parents=True)
    filename = f"{digest}.glb"
    (pal_root / filename).write_bytes(body)
    (pal_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "skin": "pal",
                "sha256": digest,
                "filename": filename,
                "clips": {"happy": "NlaTrack"},
            }
        ),
        encoding="utf-8",
    )
    return digest


def test_skin_manifest_projects_a_content_addressed_model_url(tmp_path: Path) -> None:
    digest = _install_cached_model(tmp_path)
    response = serve_client_asset(
        object(),
        Request("/desktop-avatar-skin-manifest.json", Headers()),
        skin_cache_root=tmp_path,
    )

    assert response is not None
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = json.loads(response.body)
    assert payload["sha256"] == digest
    assert payload["model_url"] == f"/desktop-avatar-skins/pal/{digest}.glb"


def test_hashed_model_response_is_immutable_and_exact(tmp_path: Path) -> None:
    body = b"glTF-local-model"
    digest = _install_cached_model(tmp_path, body)
    response = serve_client_asset(
        object(),
        Request(f"/desktop-avatar-skins/pal/{digest}.glb", Headers()),
        skin_cache_root=tmp_path,
    )

    assert response is not None
    assert response.status_code == 200
    assert response.body == body
    assert response.headers["Content-Type"] == "model/gltf-binary"
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert response.headers["ETag"] == f'"sha256-{digest}"'


def test_missing_or_stale_skin_cache_fails_closed(tmp_path: Path) -> None:
    missing = serve_client_asset(
        object(),
        Request("/desktop-avatar-skin-manifest.json", Headers()),
        skin_cache_root=tmp_path,
    )
    assert missing is not None
    assert missing.status_code == 404
    assert json.loads(missing.body)["error"] == "pal_skin_not_installed"

    digest = _install_cached_model(tmp_path)
    stale = serve_client_asset(
        object(),
        Request(f"/desktop-avatar-skins/pal/{'f' * 64}.glb", Headers()),
        skin_cache_root=tmp_path,
    )
    assert stale is not None
    assert stale.status_code == 404
    assert digest.encode() not in stale.body


def test_corrupted_cached_model_fails_digest_validation(tmp_path: Path) -> None:
    digest = _install_cached_model(tmp_path)
    (tmp_path / "pal" / f"{digest}.glb").write_bytes(b"corrupted")

    manifest = serve_client_asset(
        object(),
        Request("/desktop-avatar-skin-manifest.json", Headers()),
        skin_cache_root=tmp_path,
    )
    model = serve_client_asset(
        object(),
        Request(f"/desktop-avatar-skins/pal/{digest}.glb", Headers()),
        skin_cache_root=tmp_path,
    )

    assert manifest is not None and manifest.status_code == 200
    assert model is not None and model.status_code == 404


def test_malformed_manifest_fails_closed_without_leaking_paths(tmp_path: Path) -> None:
    digest = _install_cached_model(tmp_path)
    manifest_path = tmp_path / "pal" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["clips"] = ["not", "a", "mapping"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    response = serve_client_asset(
        object(),
        Request("/desktop-avatar-skin-manifest.json", Headers()),
        skin_cache_root=tmp_path,
    )

    assert response is not None
    assert response.status_code == 404
    error = json.loads(response.body)
    assert error["error"] == "pal_skin_not_installed"
    assert str(tmp_path) not in error["detail"]
