from __future__ import annotations

import json
import mimetypes
import re
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .config import resolve
from .diagnostics import doctor
from .jobs import JobManager
from .instance import InstanceLock
from .pipeline import Pipeline
from .storage import Store


class Application:
    def __init__(self, root: Path, config: dict):
        self.root, self.config = root, config
        self.store = Store(resolve(root, config["projects_dir"]))
        self.store.recover()
        self.jobs = JobManager(Pipeline(root, config, self.store), self.store)
        self.diagnostics = doctor(root, config, config["mode"])

    def action(self, method: str, parts: list[str], body: dict):
        if parts == ["api", "status"] and method == "GET":
            return {"mode": self.config["mode"], "version": __version__, "diagnostics": self.diagnostics,
                    "busy": bool(self.jobs.events), "active_project": self.jobs.active_project}
        if parts == ["api", "diagnostics"] and method == "POST":
            self.diagnostics = doctor(self.root, self.config, self.config["mode"])
            return self.diagnostics
        if parts == ["api", "projects"]:
            if method == "GET":
                return {"projects": self.store.list()}
            if method == "POST":
                project = self.store.create(body.get("prompt", ""), body.get("mode", self.config["mode"]), body.get("shot_count", 6))
                return self.jobs.enqueue(project["id"])
        if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
            project_id = parts[2]
            if len(parts) == 3 and method == "GET":
                return self.store.get(project_id)
            if len(parts) == 4 and method == "POST":
                if parts[3] == "run":
                    with self.jobs.lock:
                        current = self.store.get(project_id)
                        if current["status"] == "completed" and project_id not in self.jobs.events:
                            self.store.update(project_id, lambda p: p.update(status="draft", output=None))
                        return self.jobs.enqueue(project_id)
                if parts[3] == "cancel":
                    return self.jobs.cancel(project_id)
            if len(parts) >= 5 and parts[3] == "shots":
                shot_id = parts[4]
                if len(parts) == 5 and method == "PATCH":
                    with self.jobs.lock:
                        if project_id in self.jobs.events:
                            raise ValueError("请先停止当前项目，再编辑镜头")
                        return self.store.edit_shot(project_id, shot_id, body)
                if len(parts) == 6 and method == "POST" and parts[5] in {"retry", "select"}:
                    with self.jobs.lock:
                        if project_id in self.jobs.events:
                            raise ValueError("请先停止当前项目，再修改版本")
                        def change(project):
                            shot = next((s for s in project["shots"] if s["id"] == shot_id), None)
                            if shot is None:
                                raise ValueError("镜头不存在")
                            if parts[5] == "retry":
                                if shot.get("locked"):
                                    raise ValueError("请先解锁，再重做此镜头")
                                shot.update(status="pending", audio=None, seed=(shot["seed"] + 1) % (2**32))
                            else:
                                selected = next((v for v in shot["versions"] if v["id"] == body.get("version")), None)
                                if not selected:
                                    raise ValueError("所选版本不存在")
                                for key in ("audio", "video", "prompt", "narration", "seed"):
                                    shot[key] = selected[key]
                                shot.update(selected_version=selected["id"], status="completed")
                            project.update(output=None, status="draft", progress=0, error=None)
                        self.store.update(project_id, change)
                        return self.jobs.enqueue(project_id)
        raise FileNotFoundError("接口不存在")


def make_handler(app: Application):
    class Handler(BaseHTTPRequestHandler):
        server_version = "YKI-video-generator/0.1"

        def log_message(self, format, *args):
            # Request bodies/story prompts are never included in the access log.
            pass

        def _local_request(self, mutation: bool = False) -> bool:
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in allowed:
                self._json({"error": "仅允许本机访问"}, 403)
                return False
            if mutation:
                origin = self.headers.get("Origin")
                if origin and origin not in {"http://" + h for h in allowed}:
                    self._json({"error": "拒绝跨站请求"}, 403)
                    return False
                if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                    self._json({"error": "请求必须为 application/json"}, 415)
                    return False
            return True

        def _json(self, data: dict, status: int = 200):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _file(self, path: Path, *, downloadable: bool = False):
            if not path.is_file():
                raise FileNotFoundError("文件不存在")
            size = path.stat().st_size
            start, end = 0, size - 1
            partial = False
            byte_range = self.headers.get("Range")
            if byte_range:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
                if not match or not any(match.groups()) or not size:
                    self._json({"error": "不支持此范围请求"}, 416)
                    return
                if match[1]:
                    start = int(match[1])
                    end = min(int(match[2]), size - 1) if match[2] else size - 1
                else:
                    start = max(0, size - int(match[2]))
                if start >= size or end < start:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if downloadable:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(path.name))
            if path.suffix in {".html", ".js", ".css"}:
                self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
                self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command == "HEAD":
                return
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = max(0, end - start + 1)
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

        def _handle(self):
            mutation = self.command in {"POST", "PATCH"}
            if not self._local_request(mutation):
                return
            try:
                url = urllib.parse.urlsplit(self.path)
                parts = [urllib.parse.unquote(p) for p in url.path.split("/") if p]
                if parts and parts[0] == "api":
                    body = {}
                    if mutation:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 65536:
                            raise ValueError("请求长度必须在 1–65536 字节之间")
                        body = json.loads(self.rfile.read(length))
                        if not isinstance(body, dict):
                            raise ValueError("请求必须是 JSON 对象")
                    self._json(app.action(self.command, parts, body))
                elif self.command in {"GET", "HEAD"}:
                    if len(parts) >= 3 and parts[0] == "files":
                        base = app.store.folder(parts[1]).resolve()
                        path = base.joinpath(*parts[2:]).resolve()
                        if not path.is_relative_to(base) or path.suffix.lower() not in {".mp4", ".wav", ".srt", ".png", ".jpg"}:
                            raise ValueError("无效的素材路径")
                        self._file(path, downloadable=urllib.parse.parse_qs(url.query).get("download") == ["1"])
                    else:
                        base = (app.root / "web").resolve()
                        path = base.joinpath(*(parts or ["index.html"])).resolve()
                        if not path.is_relative_to(base):
                            raise ValueError("无效的页面路径")
                        self._file(path)
                else:
                    raise FileNotFoundError("接口不存在")
            except FileNotFoundError as error:
                self._json({"error": str(error)}, 404)
            except (ValueError, TypeError, KeyError) as error:
                self._json({"error": str(error)}, 400)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                self._json({"error": str(error)[:2000]}, 500)

        do_GET = do_POST = do_PATCH = do_HEAD = _handle
    return Handler


def serve(root: Path, config: dict, *, open_browser: bool = False):
    with (
        InstanceLock(root / "runtime/.studio-runtime.lock", "安装器或创作台正在使用此运行环境，请等待安装完成或关闭已运行的启动窗口。"),
        InstanceLock(resolve(root, config["projects_dir"]) / ".studio.lock"),
    ):
        # Bind before recovery: a failed second launch must not mutate live jobs.
        server = ThreadingHTTPServer(("127.0.0.1", int(config["port"])), BaseHTTPRequestHandler)
        app = None
        try:
            app = Application(root, config)
            server.RequestHandlerClass = make_handler(app)
            url = f"http://127.0.0.1:{server.server_port}"
            print(f"YKI-video-generator: {url}\n模式: {config['mode']}\n按 Ctrl+C 停止，完成的项目保留。", flush=True)
            if open_browser:
                threading.Timer(0.7, webbrowser.open, args=(url,)).start()
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            if app:
                app.jobs.shutdown()
