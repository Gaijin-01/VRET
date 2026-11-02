"""A minimal, dependency-free PEP 517 build backend.

The reference package must be installable on a machine with no network and
no ``setuptools``. Rather than depend on a build backend that may not be
present, this module implements the small subset of PEP 517 that ``pip``
actually calls, using only the standard library.

It builds a pure-Python wheel directly:

* ``vret_cli/`` (including the immutable ``checkpoint/`` tree) is copied
  into the wheel;
* ``vret/py.typed`` is included as package data;
* ``vret-*.dist-info/{METADATA,WHEEL,RECORD,entry_points.txt}`` is written;
* the console script ``vret`` is declared in ``entry_points.txt``.
* ``vret_cli/checkpoint/`` is shipped as package data, so the wheel is
  self-contained and needs no external checkpoint download.

The backend is intentionally small and auditable: it does no code generation,
no network access and no compilation.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path, PurePosixPath

NAME = "vret-cli"
DIST = "vret_cli"
VERSION = "0.2.0"
SUMMARY = (
    "VRET CLI: stdlib front end for the immutable, verified VRET "
    "CUDA/GPU checkpoint"
)
REQUIRES_PYTHON = ">=3.10"

ENTRY_POINTS = "[console_scripts]\nvret = vret_cli.cli:main\nvret-cli = vret_cli.cli:main\n"
REPOSITORY_URL = "https://github.com/Gaijin-01/VRET"

ROOT = Path(__file__).resolve().parent.parent


def _readme() -> str:
    path = ROOT / "README.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _metadata() -> str:
    readme = _readme()
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {NAME}",
        f"Version: {VERSION}",
        f"Summary: {SUMMARY}",
        f"Requires-Python: {REQUIRES_PYTHON}",
        "Author: VRET contributors",
        "Keywords: vret,cli,cuda,gpu,checkpoint,reproducibility",
        "License: MIT",
        f"Project-URL: Homepage, {REPOSITORY_URL}",
        f"Project-URL: Repository, {REPOSITORY_URL}",
        "Description-Content-Type: text/markdown",
    ]
    body = "\n".join(lines) + "\n"
    if readme:
        body += "\n" + readme
    return body


def _wheel_metadata() -> str:
    return (
        "Wheel-Version: 1.0\n"
        f"Generator: vret-build-backend {VERSION}\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    )


def _manifest_files() -> list[Path]:
    """Read explicit source membership; reject aliases, links and missing files."""
    files: dict[str, Path] = {}
    for entry in (ROOT / "SOURCE_FILES.txt").read_text(encoding="utf-8").splitlines():
        relative = PurePosixPath(entry)
        path = ROOT / entry
        if (not entry or relative.is_absolute() or ".." in relative.parts
                or relative.as_posix() != entry or entry in files
                or path.resolve() != path or not path.is_file()):
            raise ValueError(f"invalid source manifest entry: {entry!r}")
        files[entry] = path
    return [files[key] for key in sorted(files)]


def _source_files() -> list[Path]:
    """Wheel contents are the manifest's runtime package files."""
    return [path for path in _manifest_files()
            if path.relative_to(ROOT).parts[0] == "vret_cli"]


def _record_hash(data: bytes) -> tuple[str, int]:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}", len(data)


def build_wheel(
    wheel_directory: str,
    config_settings: dict | None = None,
    metadata_directory: str | None = None,
) -> str:
    """Build a pure-Python wheel and return its filename."""
    out_dir = Path(wheel_directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    wheel_name = f"{DIST}-{VERSION}-py3-none-any.whl"
    wheel_path = out_dir / wheel_name
    dist_info = f"{DIST}-{VERSION}.dist-info"

    records: list[tuple[str, str, int]] = []

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:

        def write(arcname: str, data: bytes) -> None:
            archive.writestr(arcname, data)
            digest, size = _record_hash(data)
            records.append((arcname, digest, size))

        for path in _source_files():
            arcname = path.relative_to(ROOT).as_posix()
            write(arcname, path.read_bytes())

        if metadata_directory is None:
            metadata_files = {
                "METADATA": _metadata().encode("utf-8"),
                "WHEEL": _wheel_metadata().encode("utf-8"),
                "entry_points.txt": ENTRY_POINTS.encode("utf-8"),
                "top_level.txt": b"vret_cli\n",
            }
        else:
            prepared = Path(metadata_directory)
            metadata_files = {
                path.relative_to(prepared).as_posix(): path.read_bytes()
                for path in sorted(prepared.rglob("*")) if path.is_file()
            }
            if not {"METADATA", "WHEEL"}.issubset(metadata_files):
                raise ValueError("prepared metadata must contain METADATA and WHEEL")
        metadata_files.setdefault("LICENSE", (ROOT / "LICENSE").read_bytes())
        for relative, data in sorted(metadata_files.items()):
            if relative != "RECORD":
                write(f"{dist_info}/{relative}", data)

        record_buffer = io.StringIO()
        writer = csv.writer(record_buffer, lineterminator="\n")
        for arcname, digest, size in records:
            writer.writerow([arcname, digest, size])
        writer.writerow([f"{dist_info}/RECORD", "", ""])
        archive.writestr(f"{dist_info}/RECORD", record_buffer.getvalue())

    return wheel_name


def build_sdist(
    sdist_directory: str,
    config_settings: dict | None = None,
) -> str:
    """Build a source distribution and return its filename."""
    import tarfile

    out_dir = Path(sdist_directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    sdist_name = f"{DIST}-{VERSION}.tar.gz"
    sdist_path = out_dir / sdist_name
    prefix = f"{DIST}-{VERSION}"

    with tarfile.open(sdist_path, "w:gz") as archive:
        for path in _manifest_files():
            archive.add(path, arcname=f"{prefix}/{path.relative_to(ROOT).as_posix()}")
        metadata = _metadata().encode("utf-8")
        pkg_info = tarfile.TarInfo(f"{prefix}/PKG-INFO")
        pkg_info.size = len(metadata)
        archive.addfile(pkg_info, io.BytesIO(metadata))

    return sdist_name


def get_requires_for_build_wheel(config_settings: dict | None = None) -> list[str]:
    return []


def get_requires_for_build_sdist(config_settings: dict | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str, config_settings: dict | None = None
) -> str:
    dist_info = Path(metadata_directory) / f"{DIST}-{VERSION}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(_metadata(), encoding="utf-8")
    (dist_info / "WHEEL").write_text(_wheel_metadata(), encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(ENTRY_POINTS, encoding="utf-8")
    (dist_info / "top_level.txt").write_text("vret_cli\n", encoding="utf-8")
    return dist_info.name
