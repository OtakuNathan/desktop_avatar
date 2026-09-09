from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from install import (
    PAL_CLIP_MAP,
    RECEIPT_NAME,
    channel_files,
    emotion_files,
    install_component,
    install_pal_model,
    pal_skin_cache_root,
    validate_package,
    validate_pal_glb,
)


def _write_glb(path: Path, clip_names: list[str]) -> None:
    document = json.dumps(
        {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {}}]}],
            "animations": [
                {
                    "name": name,
                    "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
                    "samplers": [{"input": 0, "output": 1}],
                }
                for name in clip_names
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    document += b" " * ((-len(document)) % 4)
    total_length = 12 + 8 + len(document)
    path.write_bytes(
        b"glTF"
        + struct.pack("<II", 2, total_length)
        + struct.pack("<II", len(document), 0x4E4F534A)
        + document
    )


def test_emotion_update_removes_retired_managed_entrypoint(tmp_path: Path) -> None:
    version = validate_package()
    destination, files = emotion_files(tmp_path)
    destination.mkdir(parents=True)
    retired = destination / "desktop_avatar_runtime.py"
    retired.write_text("legacy = True\n", encoding="utf-8")
    unrelated = destination / "local-note.txt"
    unrelated.write_text("keep\n", encoding="utf-8")

    install_component(
        "emotion",
        destination,
        files,
        version=version,
        dry_run=False,
    )

    assert not retired.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep\n"
    assert (destination / "runtime.py").is_file()
    receipt = json.loads((destination / RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["version"] == version
    assert "runtime.py" in receipt["files"]


def test_pal_model_installs_into_content_addressed_runtime_cache(tmp_path: Path) -> None:
    source = tmp_path / "pal.glb"
    _write_glb(source, list(PAL_CLIP_MAP.values()))
    cache_root = pal_skin_cache_root(tmp_path)
    cache_root.mkdir(parents=True)
    stale = cache_root / ("0" * 64 + ".glb")
    stale.write_bytes(b"stale")

    destination = install_pal_model(tmp_path, source, dry_run=False)

    manifest = json.loads((cache_root / "manifest.json").read_text(encoding="utf-8"))
    assert destination == cache_root / manifest["filename"]
    assert destination.read_bytes() == source.read_bytes()
    assert manifest["clips"] == PAL_CLIP_MAP
    assert manifest["filename"] == f'{manifest["sha256"]}.glb'
    assert not stale.exists()


def test_pal_model_rejects_missing_required_clip(tmp_path: Path) -> None:
    source = tmp_path / "bad.glb"
    _write_glb(source, ["NlaTrack"])

    with pytest.raises(ValueError, match="missing required animation clips"):
        validate_pal_glb(source)


def test_pal_model_rejects_a_named_but_empty_animation(tmp_path: Path) -> None:
    source = tmp_path / "empty-animation.glb"
    _write_glb(source, list(PAL_CLIP_MAP.values()))
    payload = source.read_bytes()
    _magic, _version, _length, json_length, _json_kind = struct.unpack("<4sIIII", payload[:20])
    document = json.loads(payload[20:20 + json_length].decode("utf-8").rstrip())
    document["animations"][0]["channels"] = []
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((-len(encoded)) % 4)
    source.write_bytes(
        b"glTF"
        + struct.pack("<II", 2, 12 + 8 + len(encoded))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
    )

    with pytest.raises(ValueError, match="empty required animation clips"):
        validate_pal_glb(source)


def test_pal_model_rejects_a_scene_without_a_renderable_mesh(tmp_path: Path) -> None:
    source = tmp_path / "empty-scene.glb"
    _write_glb(source, list(PAL_CLIP_MAP.values()))
    payload = source.read_bytes()
    _magic, _version, _length, json_length, _json_kind = struct.unpack("<4sIIII", payload[:20])
    document = json.loads(payload[20:20 + json_length].decode("utf-8").rstrip())
    document["nodes"] = [{}]
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((-len(encoded)) % 4)
    source.write_bytes(
        b"glTF"
        + struct.pack("<II", 2, 12 + 8 + len(encoded))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
    )

    with pytest.raises(ValueError, match="no renderable mesh"):
        validate_pal_glb(source)


def test_channel_package_does_not_embed_the_pal_model(tmp_path: Path) -> None:
    _destination, files = channel_files(tmp_path)
    assert all(item.source.name != "pal.glb" for item in files)
    assert all("assets/model/pal/reference/" not in item.relative_destination for item in files)


def test_named_robot_model_installs_with_named_manifest(tmp_path: Path) -> None:
    source = tmp_path / "robot.glb"
    _write_glb(source, ["Robot_Idle_Pal", "Robot_Wave_Pal", "Robot_Yes_Pal", "Robot_Dance_Pal", "curious"])
    install_pal_model(tmp_path / "runtime", source, dry_run=False)
    manifest = json.loads((pal_skin_cache_root(tmp_path / "runtime") / "manifest.json").read_text())
    assert manifest["clips"]["greeting"] == "Robot_Wave_Pal"
    assert manifest["clips"]["confused"] == "curious"
    assert "NlaTrack.006" not in manifest["clips"].values()


def test_named_robot_model_requires_core_clips(tmp_path: Path) -> None:
    source = tmp_path / "partial-robot.glb"
    _write_glb(source, ["Robot_Wave_Pal"])
    with pytest.raises(ValueError, match="missing required animation clips"):
        validate_pal_glb(source)


def test_channel_update_removes_retired_renderer_and_preserves_local_files(tmp_path: Path) -> None:
    destination, files = channel_files(tmp_path)
    retired = ["client/vendor/L2Dwidget.min.js", "client/vendor/L2Dwidget.0.min.js",
               "client/js/live2d-motion-control.js", "client/assets/model/umaru/model.moc"]
    for relative in retired:
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("retired")
    local = destination / "local-note.txt"
    local.write_text("keep")
    install_component("channel", destination, files, version=validate_package(), dry_run=False)
    assert all(not (destination / relative).exists() for relative in retired)
    assert not (destination / "client/assets/model/umaru").exists()
    assert local.read_text() == "keep"
