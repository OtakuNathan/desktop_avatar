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


def test_default_skin_preserves_sister_model_and_silences_beep() -> None:
    loaded = _load_config("http://127.0.0.1:8765/")
    config = loaded["config"]
    assert loaded["dataset"] == {"avatarSkin": "umaru"}
    assert config["renderer"] == "live2d"
    assert config["modelPath"] == "./assets/model/umaru/model.json"
    assert config["messageBeepEnabled"] is False


def test_pal_skin_selects_dark_full_body_slot_and_notification_beep() -> None:
    loaded = _load_config("http://127.0.0.1:8765/?skin=pal")
    config = loaded["config"]
    assert loaded["dataset"] == {"avatarSkin": "pal"}
    assert loaded["lang"] == "en"
    assert config["renderer"] == "webgl"
    assert "modelPath" not in config
    assert config["messageBeepEnabled"] is True
    assert config["nativeMotions"]["smirk"] == ["smirk", 0]


def test_pal_webgl_renderer_and_vendored_runtime_are_packaged() -> None:
    renderer = ROOT / "client/js/pal-webgl-avatar.js"
    source = renderer.read_text(encoding="utf-8")
    assert 'from "../vendor/three.module.min.js"' in source
    assert "window.PalWebGLAvatar" in source
    assert "greeting" in source
    assert (ROOT / "client/vendor/three.module.min.js").is_file()
    assert (ROOT / "client/vendor/three.core.min.js").is_file()
    assert (ROOT / "THIRD_PARTY_LICENSES/three-0.185.1-MIT.txt").is_file()
    stylesheet = (ROOT / "client/css/style.css").read_text(encoding="utf-8")
    assert "height: min(52%, 420px) !important" in stylesheet
    assert ".chat-input::-webkit-scrollbar" in stylesheet
    assert "scrollbar-width: none" in stylesheet


def test_unknown_skin_falls_back_to_sister() -> None:
    loaded = _load_config("http://127.0.0.1:8765/?skin=unknown")
    assert loaded["config"]["skin"] == "umaru"
