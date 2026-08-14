#!/usr/bin/env python3
"""Install the desktop-avatar channel and/or show_emotion plugin safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
IGNORED_NAMES = {"__pycache__", ".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
RECEIPT_NAME = ".desktop-avatar-install.json"


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
        for name in ("provider.toml", "runtime.py", "sidecar.py")
    ]
    for source in included_files(PACKAGE_ROOT / "client"):
        relative = source.relative_to(PACKAGE_ROOT / "client")
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
    args = parser.parse_args()
    version = validate_package()
    runtime_root = args.runtime_root.expanduser().resolve()
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
