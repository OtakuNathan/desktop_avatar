from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_config(url: str) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = r"""
const fs = require('fs');
global.window = { location: { href: process.argv[1] } };
global.document = { documentElement: { dataset: {}, lang: '' } };
eval(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify({
  config: window.AVATAR_CONFIG,
  dataset: document.documentElement.dataset,
  lang: document.documentElement.lang,
}));
"""
    result = subprocess.run(
        [node, "-e", script, url, str(ROOT / "client/js/config.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_default_skin_selects_pal_webgl() -> None:
    loaded = _load_config("http://127.0.0.1:8765/")
    config = loaded["config"]
    assert loaded["dataset"] == {"avatarSkin": "pal"}
    assert config["renderer"] == "webgl"
    assert config["messageBeepEnabled"] is True


def test_pal_skin_selects_dark_full_body_slot_and_notification_beep() -> None:
    loaded = _load_config("http://127.0.0.1:8765/?skin=pal")
    config = loaded["config"]
    assert loaded["dataset"] == {"avatarSkin": "pal"}
    assert loaded["lang"] == "en"
    assert config["renderer"] == "webgl"
    assert config["skinManifestPath"] == "./desktop-avatar-skin-manifest.json"
    assert config["messageBeepEnabled"] is True


def test_pal_webgl_renderer_and_vendored_runtime_are_packaged() -> None:
    renderer = ROOT / "client/js/pal-webgl-avatar.js"
    source = renderer.read_text(encoding="utf-8")
    assert 'from "../vendor/three.module.min.js"' in source
    assert 'from "../vendor/three-addons/loaders/GLTFLoader.js"' in source
    assert "window.PalWebGLAvatar" in source
    assert 'dance: "NlaTrack.008"' in source
    assert 'addEventListener("finished"' in source
    assert "action.clampWhenFinished = true" in source
    assert 'this.loadingStatus.textContent = "Loading Pal…"' in source
    assert not (ROOT / "client/assets/model/pal/pal.glb").exists()
    assert (ROOT / "client/vendor/three-addons/loaders/GLTFLoader.js").is_file()
    assert (ROOT / "client/vendor/three-addons/utils/BufferGeometryUtils.js").is_file()
    assert (ROOT / "client/vendor/three-addons/utils/SkeletonUtils.js").is_file()
    assert (ROOT / "client/vendor/three.module.min.js").is_file()
    assert (ROOT / "client/vendor/three.core.min.js").is_file()
    assert (ROOT / "THIRD_PARTY_LICENSES/three-0.185.1-MIT.txt").is_file()
    stylesheet = (ROOT / "client/css/style.css").read_text(encoding="utf-8")
    assert "height: min(52%, 420px) !important" in stylesheet
    assert ".pal-webgl-loading" in stylesheet
    assert ".chat-input::-webkit-scrollbar" in stylesheet
    assert "scrollbar-width: none" in stylesheet


def test_new_pal_actions_are_supported_end_to_end() -> None:
    states = {"laugh", "clap", "agree", "complain", "dance"}
    sidecar = (ROOT / "server/sidecar.py").read_text(encoding="utf-8")
    runtime = (ROOT / "server/runtime.py").read_text(encoding="utf-8")
    emotion = (ROOT / "plugin/desktop_avatar_emotion_introspection.py").read_text(
        encoding="utf-8"
    )
    client = (ROOT / "client/js/main.js").read_text(encoding="utf-8")
    assert "pal-webgl-bootstrap-loading" in client
    assert 'type: "avatar_action_finished"' in client
    for state in states:
        quoted = f'"{state}"'
        assert quoted in sidecar
        assert quoted in runtime
        assert quoted in emotion
        assert f"{state}:" in client


def test_unknown_skin_falls_back_to_pal() -> None:
    loaded = _load_config("http://127.0.0.1:8765/?skin=unknown")
    assert loaded["config"]["skin"] == "pal"


def test_pal_2d_selects_svg_with_existing_pal_theme():
    loaded = _load_config("http://127.0.0.1:8765/?skin=pal2d")
    assert loaded["config"]["renderer"] == "svg"
    assert loaded["dataset"] == {"avatarSkin": "pal"}
    assert loaded["config"]["displayName"] == "Pal"


def test_pal_3d_remains_available():
    loaded = _load_config("http://127.0.0.1:8765/?skin=pal3d")
    assert loaded["config"]["renderer"] == "webgl"
    assert loaded["dataset"] == {"avatarSkin": "pal"}
