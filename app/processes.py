from __future__ import annotations

import socket
import subprocess
import threading
import time
from pathlib import Path

from .http_client import request_json


class Cancelled(RuntimeError):
    pass


def check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled("任务已停止；完成的镜头已保存")


class ManagedProcess:
    """Own and stop only this application's child, never an existing server."""

    def __init__(self, command: list[str], cwd: Path, log: Path, port: int, health_path: str, timeout: int, cancel: threading.Event):
        self.command, self.cwd, self.log, self.port = command, cwd, log, port
        self.health_path, self.timeout, self.cancel = health_path, timeout, cancel
        self.process = None
        self.stream = None
        self.finished = threading.Event()

    def __enter__(self):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                raise RuntimeError(f"本地端口 {self.port} 已被占用。请关闭对应服务或调整 settings.local.json；不会终止其他程序。")
        check_cancel(self.cancel)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.log.open("ab")
        try:
            self.process = subprocess.Popen(self.command, cwd=self.cwd, stdout=self.stream, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL)
            threading.Thread(target=self._watch_cancel, daemon=True).start()
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                check_cancel(self.cancel)
                if self.process.poll() is not None:
                    raise RuntimeError(f"模型进程提前退出（{self.process.returncode}），请查看 {self.log.name}")
                try:
                    request_json(f"http://127.0.0.1:{self.port}{self.health_path}", timeout=2)
                    return self
                except (OSError, RuntimeError):
                    self.cancel.wait(1)
            raise RuntimeError(f"模型启动超时，请查看 {self.log.name}")
        except BaseException:
            self.stop()
            raise

    def _watch_cancel(self):
        while not self.finished.wait(0.5):
            if self.cancel.is_set():
                if self.process and self.process.poll() is None:
                    try:
                        self.process.terminate()
                    except OSError:
                        pass
                return

    def stop(self):
        self.finished.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
        if self.stream:
            self.stream.close()

    def __exit__(self, *_):
        self.stop()
