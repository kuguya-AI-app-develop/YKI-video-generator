from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .storage import atomic_json


def manifest(root: Path) -> dict:
    data = json.loads((root / "config/models.lock.json").read_text(encoding="utf-8"))
    seen = set()
    for asset in data["assets"]:
        if asset["id"] in seen or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
            raise ValueError("模型清单存在重复编号或无效校验值")
        seen.add(asset["id"])
        safe_path(root, asset["path"])
        if not asset["url"].startswith("https://"):
            raise ValueError("模型下载地址必须使用 HTTPS")
    return data


def safe_path(root: Path, relative: str) -> Path:
    destination = (root / relative).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError("路径超出项目目录")
    return destination


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def download(asset: dict, root: Path, *, report=print, retries: int = 4) -> Path:
    path = safe_path(root, asset["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size == asset["size"]:
        report(f"校验 {asset['id']} …")
        if digest(path) == asset["sha256"]:
            report(f"已就绪: {asset['id']}")
            return path
    partial = path.with_name(path.name + ".part")
    last_error = None
    for attempt in range(retries):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > asset["size"]:
            with partial.open("wb"):
                pass
            offset = 0
        if offset == asset["size"]:
            if digest(partial) == asset["sha256"]:
                os.replace(partial, path)
                return path
            with partial.open("wb"):
                pass
            offset = 0
        remaining = asset["size"] - offset
        if shutil.disk_usage(path.parent).free < remaining + 512 * 1024 * 1024:
            raise RuntimeError(f"磁盘空间不足，{asset['id']} 还需要 {remaining / 1024**3:.1f} GiB")
        headers = {"User-Agent": "YKI-video-generator/0.1", "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(asset["url"], headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                status = response.status
                if status == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or int(match[1]) != offset or int(match[3]) != asset["size"]:
                        raise RuntimeError("服务器返回的断点范围不正确")
                elif status == 200:
                    offset = 0
                else:
                    raise RuntimeError(f"下载服务器返回 HTTP {status}")
                downloaded = offset
                last_report = 0.0
                with partial.open("ab" if offset else "wb") as output:
                    while chunk := response.read(4 * 1024 * 1024):
                        downloaded += len(chunk)
                        if downloaded > asset["size"]:
                            raise RuntimeError("下载内容超过固定清单长度")
                        output.write(chunk)
                        if time.monotonic() - last_report > 3:
                            report(f"{asset['id']}: {downloaded / asset['size']:.1%} ({downloaded / 1024**3:.2f} GiB)")
                            last_report = time.monotonic()
                    output.flush()
                    os.fsync(output.fileno())
            if partial.stat().st_size != asset["size"]:
                raise RuntimeError("下载未完成，将从已有数据继续")
            report(f"校验 SHA256: {asset['id']} …")
            if digest(partial) != asset["sha256"]:
                # Preserve the original final file; only reset the untrusted partial.
                with partial.open("wb"):
                    pass
                raise RuntimeError("SHA256 校验失败，将重新下载此文件")
            os.replace(partial, path)
            report(f"完成: {asset['id']}")
            return path
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            last_error = error
            report(f"{asset['id']} 第 {attempt + 1} 次下载未完成: {error}")
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"无法下载 {asset['id']}。检查网络后再次启动，已有进度会保留。{last_error}")


def download_group(root: Path, group: str, only_id: str | None = None) -> None:
    selected = [a for a in manifest(root)["assets"] if (group == "all" or a["group"] == group) and (not only_id or a["id"] == only_id)]
    if not selected:
        raise ValueError("下载清单中没有匹配项目")
    for asset in selected:
        download(asset, root)


def extract(root: Path, asset_id: str) -> Path:
    asset = next((a for a in manifest(root)["assets"] if a["id"] == asset_id), None)
    if not asset or not asset.get("extract_to"):
        raise ValueError("此项目没有配置解压目录")
    archive = safe_path(root, asset["path"])
    if not archive.is_file() or archive.stat().st_size != asset["size"] or digest(archive) != asset["sha256"]:
        raise ValueError("请先完整下载并校验模型归档")
    destination = safe_path(root, asset["extract_to"])
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            safe_path(destination, member.name)
            if not member.isfile() and not member.isdir():
                raise ValueError("模型归档含不支持的链接或特殊文件")
        stream.extractall(destination, filter="data")
    atomic_json(destination / f".{asset_id}.installed.json", {"sha256": asset["sha256"]})
    return destination
