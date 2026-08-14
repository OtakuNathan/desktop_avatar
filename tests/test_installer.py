from __future__ import annotations

import json
from pathlib import Path

from install import RECEIPT_NAME, emotion_files, install_component, validate_package


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
