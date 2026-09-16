from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def merge(base: dict, changes: dict) -> dict:
    result = dict(base)
    for key, value in changes.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def load(root: Path = ROOT) -> dict:
    config = json.loads((root / "config/defaults.json").read_text(encoding="utf-8"))
    local = root / "settings.local.json"
    if local.exists():
        config = merge(config, json.loads(local.read_text(encoding="utf-8")))
    return config


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def executable(root: Path, config: dict, name: str) -> str:
    configured = config.get(name)
    if configured:
        path = resolve(root, configured)
        if path.is_file():
            return str(path)
        raise FileNotFoundError(f"找不到配置的 {name}: {path}")
    bundled = sorted((root / "runtime/ffmpeg").glob(f"**/{name}.exe"))
    if bundled:
        return str(bundled[0])
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"找不到 {name}。Windows 请先运行 Install-Windows.bat；Mac 请安装 FFmpeg。")
