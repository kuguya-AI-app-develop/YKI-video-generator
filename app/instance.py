"""Cross-platform process lock protecting projects and installed runtimes."""
from __future__ import annotations

import os
from pathlib import Path


class InstanceLock:
    def __init__(self, path: Path, message: str = "此项目目录已有启动器运行，请使用已打开的创作页面。"):
        self.path, self.stream = path, None
        self.message = message

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.stat().st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
                self.stream.seek(0)
        except OSError as error:
            self.stream.close()
            raise RuntimeError(self.message) from error
        return self

    def __exit__(self, *_):
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
