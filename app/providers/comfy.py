"""Local ComfyUI v0.35.0 H3 integration; no custom nodes or cloud endpoints.

The API graph is adapted from Comfy-Org/workflow_templates commit
66abae5205f7c5105281146fa109f7c12801d268, templates/video_minimax_h3_t2v.json.
Its optional Turbo/LoRA and UI-only nodes are removed. Node inputs were checked
against ComfyUI commit 40c4fcdf513a4523e39d54a9d391908af8df8171.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path, PurePosixPath
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid


WORKFLOW_PATH = Path(__file__).resolve().parents[2] / "workflows" / "h3_t2v_api.json"
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}


class ComfyError(RuntimeError):
    """A local ComfyUI request or model execution failed."""


class ComfyCancelled(ComfyError):
    """The caller cancelled this specific prompt."""


class ComfyTimeout(ComfyError):
    """The generation deadline was reached."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ComfyError("ComfyUI 返回了重定向；请检查本地服务地址。")


def build_workflow(
    prompt: str,
    width: int,
    height: int,
    seconds: float,
    seed: int,
    steps: int = 20,
    filename_prefix: str = "aigc",
) -> dict:
    """Build the native H3 T2V/audio graph for one 5–15 second clip.

    H3 snaps upward to 17k+5 frames at 24 fps: 5 s becomes 124 frames.
    The caller should trim to its desired editing duration after generation.
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32_000:
        raise ValueError("视频提示词不能为空，且不能超过 32000 个字符。")
    for name, value in (("width", width), ("height", height)):
        if type(value) is not int or value < 32 or value > 1344 or value % 32:
            raise ValueError(f"{name} 必须为 32–1344 范围内的 32 的倍数。")
    if width * height > 768 * 1344:
        raise ValueError("画面面积不能超过 H3 原生的 768×1344。")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 5 <= seconds <= 15:
        raise ValueError("每个 H3 镜头应为 5–15 秒。")
    if type(seed) is not int or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("seed 必须为无符号 64 位整数。")
    if type(steps) is not int or not 1 <= steps <= 100:
        raise ValueError("steps 必须为 1–100 的整数。")
    _validate_subpath(filename_prefix, "filename_prefix", allow_empty=False)
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    target_frames = max(5, math.ceil(seconds * 24))
    length = target_frames + (5 - target_frames) % 17
    workflow["5"]["inputs"].update(prompt=prompt.strip(), width=width, height=height, length=length)
    workflow["6"]["inputs"]["noise_seed"] = seed
    workflow["9"]["inputs"]["steps"] = steps
    workflow["14"]["inputs"]["filename_prefix"] = filename_prefix
    return workflow


def _validate_subpath(value: str, label: str, *, allow_empty: bool = True) -> None:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ValueError(f"{label} 不是有效的相对路径。")
    if "\\" in value or ":" in value or "\x00" in value or value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise ValueError(f"{label} 必须位于 ComfyUI 输出目录内。")


def _prompt_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("prompt_id 必须为有效的 UUID。") from exc
    return str(parsed)


def _error_summary(payload: object) -> str:
    if not isinstance(payload, dict):
        return "未知错误"
    pieces = []
    error = payload.get("error")
    if isinstance(error, dict):
        pieces.append(str(error.get("message", error.get("type", "请求被拒绝"))))
    elif error:
        pieces.append(str(error))
    for node_id, detail in payload.get("node_errors", {}).items():
        if isinstance(detail, dict):
            for item in detail.get("errors", []):
                if isinstance(item, dict):
                    pieces.append(f"节点 {node_id}: {item.get('message', '输入无效')} {item.get('details', '')}")
    return "; ".join(pieces)[:2000] or "未知错误"


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: float = 30):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("ComfyUI 地址必须为不带认证或路径的 HTTP 服务地址。")
        if timeout <= 0:
            raise ValueError("HTTP timeout 必须大于 0。")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        # Local inference must not pass through proxy environment settings.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, path: str, data: dict | None = None) -> dict:
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        request = Request(self.base_url + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ComfyError("ComfyUI 返回的数据超过安全读取上限。")
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                raise ComfyError("ComfyUI 返回的 JSON 不是对象。")
            return payload
        except HTTPError as exc:
            raw = exc.read(32_768)
            try:
                detail = _error_summary(json.loads(raw))
            except (ValueError, UnicodeError):
                detail = "请检查 ComfyUI 日志。"
            raise ComfyError(f"ComfyUI HTTP {exc.code}: {detail}") from exc
        except (URLError, OSError) as exc:
            raise ComfyError(f"无法连接本地 ComfyUI：{exc}") from exc
        except (ValueError, UnicodeError) as exc:
            raise ComfyError("ComfyUI 返回了无效 JSON。") from exc

    def check_health(self) -> dict:
        return self._request("/system_stats")

    def validate_workflow(self, workflow: dict) -> None:
        """Check available native nodes and model loader names before queuing."""
        info = self._request("/object_info")
        for node_id, node in workflow.items():
            class_type = node.get("class_type")
            if class_type not in info:
                raise ComfyError(f"ComfyUI 缺少节点 {class_type}；请安装项目固定的 v0.35.0。")
            required = info[class_type].get("input", {}).get("required", {})
            inputs = node.get("inputs", {})
            for key in required:
                if key not in inputs:
                    raise ComfyError(f"节点 {node_id} ({class_type}) 缺少必需输入 {key}。")
            for key in ("unet_name", "clip_name", "vae_name"):
                if key in inputs and key in required:
                    choices = required[key][0]
                    if isinstance(choices, list) and inputs[key] not in choices:
                        raise ComfyError(f"ComfyUI 未找到模型 {inputs[key]}；请重新运行模型安装。")

    def submit(self, workflow: dict) -> str:
        response = self._request("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if response.get("error") or not response.get("prompt_id"):
            raise ComfyError(f"H3 工作流提交失败：{_error_summary(response)}")
        return _prompt_id(response["prompt_id"])

    def wait(
        self,
        prompt_id: str,
        timeout: float = 7200,
        poll_interval: float = 2,
        on_progress: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict:
        prompt_id = _prompt_id(prompt_id)
        if timeout <= 0 or poll_interval <= 0:
            raise ValueError("等待时间和轮询间隔必须大于 0。")
        started = time.monotonic()
        next_update = started
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self.cancel(prompt_id)
                raise ComfyCancelled("已请求取消当前 H3 镜头。")
            history = self._request("/history/" + prompt_id)
            entry = history.get(prompt_id)
            if isinstance(entry, dict):
                status = entry.get("status", {})
                for item in status.get("messages", []):
                    if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] in {"execution_error", "execution_interrupted"}:
                        detail = item[1] if isinstance(item[1], dict) else {}
                        if item[0] == "execution_interrupted":
                            raise ComfyCancelled("ComfyUI 已中断当前镜头。")
                        raise ComfyError(f"H3 节点 {detail.get('node_id', '?')} ({detail.get('node_type', 'unknown')}) 失败：{str(detail.get('exception_message', '请查看 ComfyUI 日志。'))[:2000]}")
                if status.get("status_str") == "error":
                    raise ComfyError("H3 生成失败，请查看 ComfyUI 日志。")
                if status.get("completed"):
                    if not entry.get("outputs"):
                        raise ComfyError("H3 任务结束但没有输出。")
                    if on_progress:
                        on_progress("H3 镜头生成完成。")
                    return entry
            now = time.monotonic()
            if now - started >= timeout:
                try:
                    self.cancel(prompt_id)
                except ComfyError as exc:
                    raise ComfyTimeout(f"H3 生成超时，取消请求也失败：{exc}") from exc
                raise ComfyTimeout(f"H3 等待超过 {timeout:g} 秒，已请求取消此镜头。")
            if on_progress and now >= next_update:
                on_progress(f"H3 正在排队或生成，已等待 {int(now - started)} 秒。")
                next_update = now + 30
            delay = min(poll_interval, max(0.001, timeout - (now - started)))
            if cancel_event is not None:
                cancel_event.wait(delay)
            else:
                time.sleep(delay)

    def download_video(self, history_entry: dict, destination: Path) -> Path:
        """Fetch SaveVideo's `images` result using /view, preserving any old file."""
        result = None
        outputs = history_entry.get("outputs", {})
        for node_output in outputs.values():
            for key in ("images", "videos", "gifs"):
                for item in node_output.get(key, []):
                    if isinstance(item, dict) and Path(str(item.get("filename", ""))).suffix.lower() in VIDEO_EXTENSIONS and item.get("type", "output") == "output":
                        result = item
                        break
                if result:
                    break
            if result:
                break
        if result is None:
            raise ComfyError("ComfyUI 历史记录中没有可下载的视频文件。")
        filename = result["filename"]
        subfolder = result.get("subfolder", "")
        _validate_subpath(filename, "filename", allow_empty=False)
        _validate_subpath(subfolder, "subfolder")
        if "/" in filename:
            raise ComfyError("ComfyUI 返回的文件名包含目录。")
        query = urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
        try:
            with self._opener.open(self.base_url + "/view?" + query, timeout=self.timeout) as response, temporary.open("xb") as output:
                content_type = response.headers.get("Content-Type", "").lower()
                if "json" in content_type or "text/" in content_type:
                    raise ComfyError("ComfyUI 视频下载返回了非视频内容。")
                expected = response.headers.get("Content-Length")
                size = 0
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    size += len(chunk)
                if not size or (expected is not None and size != int(expected)):
                    raise ComfyError("ComfyUI 视频下载为空或不完整。")
            os.replace(temporary, destination)
        except (URLError, OSError, ValueError) as exc:
            raise ComfyError(f"下载 H3 视频失败：{exc}") from exc
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination

    def cancel(self, prompt_id: str) -> None:
        """Cancel only this pending/running UUID; never clear the global queue."""
        prompt_id = _prompt_id(prompt_id)
        self._request("/queue", {"delete": [prompt_id]})
        self._request("/interrupt", {"prompt_id": prompt_id})

    def free(self) -> None:
        """Request asynchronous unload; process exit provides a hard GPU release."""
        self._request("/free", {"unload_models": True, "free_memory": True})
