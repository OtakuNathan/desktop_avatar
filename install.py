#!/usr/bin/env python3
"""Install the desktop-avatar channel and/or show_emotion plugin safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
IGNORED_NAMES = {"__pycache__", ".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
RECEIPT_NAME = ".desktop-avatar-install.json"
EXTERNAL_PAL_MODEL_PATH = "assets/model/pal/pal.glb"
PAL_REFERENCE_PATH_PREFIX = "assets/model/pal/reference/"
LEGACY_MANAGED_FILES: dict[str, tuple[str, ...]] = {
    "channel": (
        "client/assets/model/pal/pal.glb",
        "client/assets/model/pal/reference/pal-action-concept.png",
        "client/assets/model/pal/reference/pal-expression-sheet.png",
        "client/assets/model/pal/reference/pal-idle-action-sheet.png",
        "client/assets/model/pal/reference/pal-neutral-front.png",
    ),
    "emotion": ("desktop_avatar_runtime.py",),
}
PAL_CLIP_MAP: dict[str, str] = {
    "happy": "NlaTrack",
    "laugh": "NlaTrack.001",
    "celebrate": "NlaTrack.002",
    "panic": "NlaTrack.003",
    "clap": "NlaTrack.004",
    "agree": "NlaTrack.005",
    "greeting": "NlaTrack.006",
    "complain": "NlaTrack.007",
    "dance": "NlaTrack.008",
}

PAL_ROBOT_CLIP_MAP: dict[str, str] = {
    "standby": "Robot_Idle_Pal", "greeting": "Robot_Wave_Pal",
    "agree": "Robot_Yes_Pal", "dance": "Robot_Dance_Pal",
    "celebrate": "Robot_Dance_Pal", "happy": "NlaTrack",
    "laugh": "NlaTrack", "proud": "Robot_ThumbsUp_Pal",
    "sleeping": "sleepy", "thinking": "thinking", "working": "working",
    "curious": "curious", "confused": "curious", "sad": "bored",
    "bored": "bored", "angry": "angry", "awkward": "awkward",
    "shy": "awkward", "shock": "shock", "panic": "shock",
    "excited": "excited", "snacking": "snacking", "drinking": "drinking",
    "complain": "Idle_No_Loop",
}


def pal_clip_map(clip_names: tuple[str, ...]) -> dict[str, str]:
    if "Robot_Wave_Pal" in clip_names:
        return {state: clip for state, clip in PAL_ROBOT_CLIP_MAP.items() if clip in clip_names}
    return dict(PAL_CLIP_MAP)



@dataclass(frozen=True)
class InstallFile:
    source: Path
    destination: Path
    relative_destination: str


def package_version() -> str:
    return (PACKAGE_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def validate_package() -> str:
    version = package_version()
    required = (
        PACKAGE_ROOT / "server" / "provider.toml",
        PACKAGE_ROOT / "server" / "runtime.py",
        PACKAGE_ROOT / "server" / "sidecar.py",
        PACKAGE_ROOT / "client" / "index.html",
        PACKAGE_ROOT / "plugin" / "plugin.toml",
        PACKAGE_ROOT / "plugin" / "runtime.py",
        PACKAGE_ROOT / "plugin" / "desktop_avatar_emotion_introspection.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"package is incomplete; missing: {', '.join(missing)}")
    for relative in ("server/provider.toml", "plugin/plugin.toml"):
        path = PACKAGE_ROOT / relative
        with path.open("rb") as stream:
            manifest_version = str(tomllib.load(stream).get("version") or "")
        if manifest_version != version:
            raise ValueError(
                f"package version mismatch: {relative}={manifest_version!r}, VERSION={version!r}"
            )
    return version


def included_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and not any(part in IGNORED_NAMES for part in path.relative_to(root).parts)
            and path.suffix not in IGNORED_SUFFIXES
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def channel_files(runtime_root: Path) -> tuple[Path, list[InstallFile]]:
    destination_root = runtime_root / "channel" / "providers" / "desktop_avatar"
    files = [
        InstallFile(PACKAGE_ROOT / "server" / name, destination_root / name, name)
        for name in ("provider.toml", "runtime.py", "sidecar.py", "tool_activity.py")
    ]
    for source in included_files(PACKAGE_ROOT / "client"):
        relative = source.relative_to(PACKAGE_ROOT / "client")
        if (
            relative.as_posix() == EXTERNAL_PAL_MODEL_PATH
            or relative.as_posix().startswith(PAL_REFERENCE_PATH_PREFIX)
        ):
            continue
        files.append(
            InstallFile(source, destination_root / "client" / relative, f"client/{relative.as_posix()}")
        )
    return destination_root, files


def emotion_files(runtime_root: Path) -> tuple[Path, list[InstallFile]]:
    destination_root = runtime_root / "plugins" / "community" / "desktop_avatar_emotion"
    files = [
        InstallFile(
            source,
            destination_root / source.relative_to(PACKAGE_ROOT / "plugin"),
            source.relative_to(PACKAGE_ROOT / "plugin").as_posix(),
        )
        for source in included_files(PACKAGE_ROOT / "plugin")
    ]
    return destination_root, files


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pal_glb(path: Path) -> tuple[str, ...]:
    """Validate the external Pal skin before it enters the runtime cache."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Pal GLB model not found: {source}")
    with source.open("rb") as stream:
        if stream.read(4) != b"glTF":
            raise ValueError(f"Pal model is not a binary glTF file: {source}")
        version_data = stream.read(4)
        length_data = stream.read(4)
        if len(version_data) != 4 or len(length_data) != 4:
            raise ValueError(f"Pal GLB header is truncated: {source}")
        version = struct.unpack("<I", version_data)[0]
        total_length = struct.unpack("<I", length_data)[0]
        if version != 2 or total_length != source.stat().st_size:
            raise ValueError(
                f"Pal GLB header is invalid: version={version}, "
                f"declared_length={total_length}, actual_length={source.stat().st_size}"
            )
        document: dict[str, object] | None = None
        while stream.tell() < total_length:
            chunk_header = stream.read(8)
            if len(chunk_header) != 8:
                raise ValueError(f"Pal GLB chunk header is truncated: {source}")
            chunk_length, chunk_kind = struct.unpack("<II", chunk_header)
            chunk = stream.read(chunk_length)
            if len(chunk) != chunk_length:
                raise ValueError(f"Pal GLB chunk is truncated: {source}")
            if chunk_kind == 0x4E4F534A and document is None:
                parsed = json.loads(chunk.decode("utf-8").rstrip("\x00 \t\r\n"))
                if not isinstance(parsed, dict):
                    raise ValueError(f"Pal GLB JSON chunk is not an object: {source}")
                document = parsed
    if document is None:
        raise ValueError(f"Pal GLB has no JSON chunk: {source}")

    nodes = document.get("nodes")
    meshes = document.get("meshes")
    scenes = document.get("scenes")
    if not isinstance(nodes, list) or not isinstance(meshes, list) or not isinstance(scenes, list):
        raise ValueError(f"Pal GLB has no renderable scene: {source}")
    selected_scene = document.get("scene", 0)
    if not isinstance(selected_scene, int) or not 0 <= selected_scene < len(scenes):
        raise ValueError(f"Pal GLB has an invalid default scene: {source}")
    scene = scenes[selected_scene]
    if not isinstance(scene, dict) or not isinstance(scene.get("nodes"), list):
        raise ValueError(f"Pal GLB has no renderable scene: {source}")

    pending = list(scene["nodes"])
    visited: set[int] = set()
    renderable_mesh_found = False
    while pending:
        node_index = pending.pop()
        if not isinstance(node_index, int) or not 0 <= node_index < len(nodes):
            raise ValueError(f"Pal GLB scene references an invalid node: {source}")
        if node_index in visited:
            continue
        visited.add(node_index)
        node = nodes[node_index]
        if not isinstance(node, dict):
            raise ValueError(f"Pal GLB contains an invalid node: {source}")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError(f"Pal GLB node has invalid children: {source}")
        pending.extend(children)
        mesh_index = node.get("mesh")
        if mesh_index is None:
            continue
        if not isinstance(mesh_index, int) or not 0 <= mesh_index < len(meshes):
            raise ValueError(f"Pal GLB node references an invalid mesh: {source}")
        mesh = meshes[mesh_index]
        if isinstance(mesh, dict) and isinstance(mesh.get("primitives"), list) and mesh["primitives"]:
            renderable_mesh_found = True
    if not renderable_mesh_found:
        raise ValueError(f"Pal GLB default scene contains no renderable mesh: {source}")

    animations = document.get("animations")
    if not isinstance(animations, list):
        raise ValueError(f"Pal GLB has no animations: {source}")
    animations_by_name = {
        str(animation.get("name") or ""): animation
        for animation in animations
        if isinstance(animation, dict)
    }
    clip_names = tuple(animations_by_name)
    required = ("Robot_Idle_Pal", "Robot_Wave_Pal", "Robot_Yes_Pal", "Robot_Dance_Pal") if "Robot_Wave_Pal" in clip_names else tuple(PAL_CLIP_MAP.values())
    missing = [clip for clip in required if clip not in animations_by_name]
    if missing:
        raise ValueError("Pal GLB is missing required animation clips: " + ", ".join(missing))
    empty = [
        clip
        for clip in pal_clip_map(clip_names).values()
        if not isinstance(animations_by_name[clip].get("channels"), list)
        or not animations_by_name[clip]["channels"]
        or not isinstance(animations_by_name[clip].get("samplers"), list)
        or not animations_by_name[clip]["samplers"]
    ]
    if empty:
        raise ValueError("Pal GLB has empty required animation clips: " + ", ".join(empty))
    return clip_names


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(destination: Path, payload: dict[str, object]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def pal_skin_cache_root(runtime_root: Path) -> Path:
    return Path(runtime_root) / "data" / "desktop_avatar" / "skins" / "pal"


def install_pal_model(runtime_root: Path, source: Path, *, dry_run: bool) -> Path:
    """Install one validated GLB under a content-addressed runtime-local name."""
    source = Path(source).expanduser().resolve()
    clip_names = validate_pal_glb(source)
    digest = file_sha256(source)
    cache_root = pal_skin_cache_root(runtime_root)
    destination = cache_root / f"{digest}.glb"
    if dry_run:
        print(f"would install Pal skin cache: {destination}")
        return destination

    atomic_copy(source, destination)
    if file_sha256(destination) != digest:
        raise RuntimeError(f"Pal skin cache verification failed: {destination}")
    manifest = {
        "schema_version": 1,
        "skin": "pal",
        "sha256": digest,
        "filename": destination.name,
        "clips": pal_clip_map(clip_names),
    }
    atomic_write_json(cache_root / "manifest.json", manifest)
    for stale in cache_root.glob("*.glb"):
        if stale != destination and stale.is_file():
            stale.unlink()
    print(f"installed and verified Pal skin cache: {destination}")
    return destination


def install_component(
    name: str,
    destination_root: Path,
    files: list[InstallFile],
    *,
    version: str,
    dry_run: bool,
) -> Path:
    if dry_run:
        print(f"would install {name}: {destination_root} ({len(files)} files)")
        return destination_root
    for item in files:
        atomic_copy(item.source, item.destination)
    for relative in LEGACY_MANAGED_FILES.get(name, ()):
        legacy_path = destination_root / relative
        if legacy_path.is_file() or legacy_path.is_symlink():
            legacy_path.unlink()
    receipt = {
        "component": name,
        "package": "pal-desktop-avatar",
        "version": version,
        "files": {
            item.relative_destination: file_sha256(item.destination)
            for item in files
        },
    }
    atomic_write_json(destination_root / RECEIPT_NAME, receipt)
    verify_component(destination_root, files)
    return destination_root


def verify_component(destination_root: Path, files: list[InstallFile]) -> None:
    mismatches = []
    for item in files:
        if not item.destination.is_file():
            mismatches.append(f"missing:{item.relative_destination}")
        elif file_sha256(item.source) != file_sha256(item.destination):
            mismatches.append(f"changed:{item.relative_destination}")
    if mismatches:
        raise RuntimeError(
            f"installation verification failed for {destination_root}: {', '.join(mismatches)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the Pal desktop-avatar channel and independent show_emotion plugin."
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / ".pal",
        help="Pal runtime root (default: ~/.pal)",
    )
    parser.add_argument(
        "--component",
        choices=("all", "channel", "emotion"),
        default="all",
        help="Install both modules or only one independently.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Update an existing installation; unrelated target files are preserved.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print destinations without writing files.",
    )
    parser.add_argument(
        "--pal-model",
        type=Path,
        default=None,
        help=(
            "Validate and install a local Pal GLB into the runtime skin cache. "
            "The model remains outside the provider package."
        ),
    )
    args = parser.parse_args()
    version = validate_package()
    runtime_root = args.runtime_root.expanduser().resolve()
    if args.pal_model is not None and args.component == "emotion":
        raise ValueError("--pal-model requires --component channel or all")
    if args.pal_model is not None:
        validate_pal_glb(args.pal_model.expanduser().resolve())
    selections: list[tuple[str, Path, list[InstallFile]]] = []
    if args.component in {"all", "channel"}:
        destination, files = channel_files(runtime_root)
        selections.append(("channel", destination, files))
    if args.component in {"all", "emotion"}:
        destination, files = emotion_files(runtime_root)
        selections.append(("emotion", destination, files))

    existing = [str(destination) for _, destination, _ in selections if destination.exists()]
    if existing and not args.force:
        raise FileExistsError(
            "destination already exists (pass --force to update): " + ", ".join(existing)
        )

    installed = [
        install_component(
            name,
            destination,
            files,
            version=version,
            dry_run=args.dry_run,
        )
        for name, destination, files in selections
    ]
    if args.component in {"all", "channel"}:
        if args.pal_model is not None:
            install_pal_model(runtime_root, args.pal_model, dry_run=args.dry_run)
        elif not (pal_skin_cache_root(runtime_root) / "manifest.json").is_file():
            print(
                "warning: Pal skin has no local model cache; rerun with "
                "--pal-model /path/to/pal.glb",
                file=sys.stderr,
            )
    if not args.dry_run:
        for path in installed:
            print(f"installed and verified: {path}")
        print(f"version: {version}")
        print("The installer did not restart Pal or rescan providers.")
        print("New install: discover/attach the channel and plugin through Pal lifecycle tools.")
        print("Update: restart only the desktop-avatar endpoint, then refresh desktop_avatar_emotion.")
    return 0


def cli() -> int:
    try:
        return main()
    except (FileExistsError, FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"install error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
