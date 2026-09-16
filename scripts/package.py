"""Build a reproducible, source-only Windows transfer ZIP and SHA256 sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = {"app", "config", "workflows", "web", "scripts", "tests", "docs"}
ROOT_FILES = {"pyproject.toml", "README.md", "AGENTS.md", "CONTEXT.md", ".gitignore", ".gitattributes", "THIRD_PARTY_NOTICES.md"}
EXCLUDED = {"runtime", "models", "projects", "logs", ".venv", ".git", ".codegraph",
            "__pycache__", ".pytest_cache", ".DS_Store", "dist", "settings.local.json"}
REQUIRED = {"app/__main__.py", "app/pipeline.py", "web/index.html", "web/app.js", "web/style.css",
            "config/defaults.json", "config/models.lock.json", "requirements.txt", "requirements-windows.lock",
            "Start-Windows.bat", "Install-Windows.bat", "Start-Mac-Demo.command",
            "scripts/bootstrap.ps1", "scripts/start.ps1", "README.md", "THIRD_PARTY_NOTICES.md"}


def source_files(root: Path) -> list[Path]:
    files = [path for path in root.iterdir() if path.is_file() and not path.is_symlink() and (
        path.name in ROOT_FILES or path.suffix.lower() in {".bat", ".command"} or (
            path.name.startswith("requirements") and path.suffix in {".txt", ".lock"}))]
    # Walk only source roots; never even scan model/cache/project trees.
    for directory in sorted(DIRECTORIES):
        base = root / directory
        if not base.is_dir() or base.is_symlink():
            continue
        for current, directories, names in os.walk(base, followlinks=False):
            directories[:] = [name for name in directories if name not in EXCLUDED
                              and not name.startswith(".") and not (Path(current) / name).is_symlink()]
            for name in names:
                path = Path(current) / name
                if (name not in EXCLUDED and not name.startswith(".") and not path.is_symlink()
                        and path.is_file() and path.suffix not in {".pyc", ".pyo"}):
                    files.append(path)
    present = {path.relative_to(root).as_posix() for path in files}
    missing = sorted(REQUIRED - present)
    if missing:
        raise RuntimeError("Refusing incomplete source package; missing: " + ", ".join(missing))
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def write_entry(archive: zipfile.ZipFile, name: str, data: bytes, *, executable: bool = False) -> None:
    entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = (0o100755 if executable else 0o100644) << 16
    entry.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(entry, data, compresslevel=9)


def package(root: Path = ROOT, output_directory: Path | None = None) -> tuple[Path, str, int]:
    root = root.resolve()
    version_match = re.search(r'__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                              (root / "app/__init__.py").read_text(encoding="utf-8"))
    if not version_match:
        raise RuntimeError("Cannot determine application version")
    version = version_match.group(1)
    prefix = f"YKI-video-generator-{version}"
    output_directory = (output_directory or root / "dist").resolve()
    files = source_files(root)
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"{prefix}-windows.zip"
    manifest = {"application": "YKI-video-generator", "version": version,
                "package_kind": "source-only", "files": []}
    with tempfile.TemporaryDirectory(prefix="aigc-package-", dir=output_directory) as temporary:
        staged = Path(temporary) / destination.name
        with zipfile.ZipFile(staged, "w") as archive:
            for path in files:
                relative = path.relative_to(root).as_posix()
                data = path.read_bytes()
                manifest["files"].append({"path": relative, "size": len(data),
                                          "sha256": hashlib.sha256(data).hexdigest()})
                write_entry(archive, f"{prefix}/{relative}", data, executable=path.suffix == ".command")
            write_entry(archive, f"{prefix}/PACKAGE_MANIFEST.json",
                        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        with zipfile.ZipFile(staged) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"ZIP integrity check failed: {bad}")
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        staged.replace(destination)
    checksum = destination.with_suffix(destination.suffix + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    return destination, digest, len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="Destination directory (default: dist)")
    args = parser.parse_args()
    destination, digest, count = package(output_directory=args.output_dir)
    print(f"Packaged {count} source files: {destination}")
    print(f"SHA256: {digest}")
    print(f"Size: {destination.stat().st_size:,} bytes; models and user projects excluded")


if __name__ == "__main__":
    main()
