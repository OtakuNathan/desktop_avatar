#!/usr/bin/env python3
"""Build a deterministic, self-verifying desktop-avatar source package."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_DIST_DIR = PACKAGE_ROOT / "dist"
PACKAGE_NAME = "pal-desktop-avatar"
ROOT_FILES = (
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "VERSION",
    "install.py",
    "package.py",
)
SOURCE_DIRS = ("server", "plugin", "client", "THIRD_PARTY_LICENSES")
IGNORED_NAMES = {"__pycache__", ".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_PACKAGE_PATHS = {"client/assets/model/pal/pal.glb"}
EXCLUDED_PACKAGE_DIRS = {"client/assets/model/pal/reference"}
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def package_version() -> str:
    version = (PACKAGE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"invalid VERSION: {version!r}")
    return version


def validate_manifest_versions(version: str) -> None:
    manifests = (
        (PACKAGE_ROOT / "server" / "provider.toml", "version"),
        (PACKAGE_ROOT / "plugin" / "plugin.toml", "version"),
    )
    for path, key in manifests:
        with path.open("rb") as stream:
            actual = str(tomllib.load(stream).get(key) or "")
        if actual != version:
            raise ValueError(f"{path.relative_to(PACKAGE_ROOT)} has {key}={actual!r}; expected {version!r}")


def should_include(path: Path) -> bool:
    relative = path.relative_to(PACKAGE_ROOT)
    relative_path = relative.as_posix()
    return not (
        any(part in IGNORED_NAMES for part in relative.parts)
        or path.suffix in IGNORED_SUFFIXES
        or relative_path in EXCLUDED_PACKAGE_PATHS
        or any(
            relative_path == directory or relative_path.startswith(directory + "/")
            for directory in EXCLUDED_PACKAGE_DIRS
        )
    )


def package_paths() -> list[Path]:
    paths: list[Path] = []
    for name in ROOT_FILES:
        path = PACKAGE_ROOT / name
        if not path.is_file():
            raise FileNotFoundError(f"required package file is missing: {path}")
        paths.append(path)
    for name in SOURCE_DIRS:
        root = PACKAGE_ROOT / name
        if not root.is_dir():
            raise FileNotFoundError(f"required package directory is missing: {root}")
        paths.append(root)
        paths.extend(path for path in root.rglob("*") if should_include(path))
    return sorted(set(paths), key=lambda path: path.relative_to(PACKAGE_ROOT).as_posix())


def normalized_tar_info(path: Path, archive_name: str, *, epoch: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(archive_name)
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = epoch
    if path.is_dir():
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.size = 0
    elif path.is_file():
        info.type = tarfile.REGTYPE
        info.mode = 0o755 if path.name in {"install.py", "package.py"} else 0o644
        info.size = path.stat().st_size
    else:
        raise ValueError(f"unsupported package entry (only files/directories are allowed): {path}")
    return info


def build_archive(destination: Path, *, version: str, epoch: int) -> None:
    archive_root = f"{PACKAGE_NAME}-{version}"
    paths = package_paths()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary:
            with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=epoch) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    root_info = tarfile.TarInfo(archive_root)
                    root_info.type = tarfile.DIRTYPE
                    root_info.mode = 0o755
                    root_info.uid = root_info.gid = 0
                    root_info.uname = root_info.gname = "root"
                    root_info.mtime = epoch
                    archive.addfile(root_info)
                    for path in paths:
                        relative = path.relative_to(PACKAGE_ROOT).as_posix()
                        info = normalized_tar_info(path, f"{archive_root}/{relative}", epoch=epoch)
                        if path.is_file():
                            with path.open("rb") as stream:
                                archive.addfile(info, stream)
                        else:
                            archive.addfile(info)
        os.replace(temporary_path, destination)
        destination.chmod(0o644)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def verify_archive(archive_path: Path, *, version: str) -> int:
    archive_root = PurePosixPath(f"{PACKAGE_NAME}-{version}")
    expected_files = {
        (archive_root / path.relative_to(PACKAGE_ROOT).as_posix()).as_posix()
        for path in package_paths()
        if path.is_file()
    }
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        actual_files: set[str] = set()
        for member in members:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"unsafe archive member: {member.name}")
            if member_path != archive_root and archive_root not in member_path.parents:
                raise ValueError(f"archive member escaped package root: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"unsupported archive member type: {member.name}")
            if member.isfile():
                actual_files.add(member.name)
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        if missing or unexpected:
            raise ValueError(f"archive file mismatch; missing={missing}, unexpected={unexpected}")
    return len(expected_files)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum(archive_path: Path, digest: str) -> Path:
    checksum_path = archive_path.with_name(archive_path.name + ".sha256")
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    checksum_path.chmod(0o644)
    return checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the standalone desktop-avatar tarball.")
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=DEFAULT_DIST_DIR,
        help="Output directory (default: ./dist).",
    )
    parser.add_argument(
        "--source-date-epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", "0")),
        help="Normalized archive timestamp for reproducible builds (default: SOURCE_DATE_EPOCH or 0).",
    )
    args = parser.parse_args()
    if args.source_date_epoch < 0:
        parser.error("--source-date-epoch must be non-negative")

    version = package_version()
    validate_manifest_versions(version)
    dist_dir = args.dist_dir.expanduser().resolve()
    archive_path = dist_dir / f"{PACKAGE_NAME}-{version}.tar.gz"
    build_archive(archive_path, version=version, epoch=args.source_date_epoch)
    file_count = verify_archive(archive_path, version=version)
    digest = sha256(archive_path)
    checksum_path = write_checksum(archive_path, digest)
    print(f"built: {archive_path}")
    print(f"files: {file_count}")
    print(f"sha256: {digest}")
    print(f"checksum: {checksum_path}")
    return 0


def cli() -> int:
    try:
        return main()
    except (FileNotFoundError, OSError, tarfile.TarError, ValueError) as exc:
        print(f"package error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
