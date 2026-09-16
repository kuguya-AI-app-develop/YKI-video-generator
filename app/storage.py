from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def folder(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", project_id):
            raise ValueError("无效的项目编号")
        return self.directory / project_id

    def get(self, project_id: str) -> dict:
        with self.lock:
            return json.loads((self.folder(project_id) / "project.json").read_text(encoding="utf-8"))

    def save(self, project: dict) -> None:
        with self.lock:
            project["updated_at"] = now()
            atomic_json(self.folder(project["id"]) / "project.json", project)

    def update(self, project_id: str, function) -> dict:
        with self.lock:
            project = self.get(project_id)
            function(project)
            self.save(project)
            return copy.deepcopy(project)

    def create(self, prompt: str, mode: str, shot_count: int = 6) -> dict:
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
            raise ValueError("请输入 1–4000 字的故事梗概")
        if mode not in {"real", "demo"} or shot_count not in {3, 6}:
            raise ValueError("无效的生成模式或镜头数量")
        project = {"schema_version": 1, "id": uuid.uuid4().hex[:12], "prompt": prompt.strip(),
                   "mode": mode, "shot_count": shot_count, "title": prompt.strip()[:30],
                   "created_at": now(), "status": "draft", "stage": "等待生成", "progress": 0,
                   "shots": [], "events": [], "output": None, "error": None,
                   "character": "", "style": "", "cancel_requested": False}
        self.save(project)
        return project

    def list(self) -> list[dict]:
        projects = []
        for path in self.directory.glob("*/project.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                projects.append({k: data.get(k) for k in ("id", "title", "mode", "status", "progress", "updated_at")})
            except (OSError, ValueError):
                continue
        return sorted(projects, key=lambda p: p.get("updated_at") or "", reverse=True)

    def recover(self) -> None:
        for item in self.list():
            if item["status"] in {"running", "queued"}:
                self.update(item["id"], lambda p: p.update(status="interrupted", stage="上次运行中断，可继续", cancel_requested=False))

    def event(self, project_id: str, message: str) -> None:
        def add(project):
            project["events"] = (project["events"] + [{"at": now(), "message": message}])[-200:]
        self.update(project_id, add)

    def edit_shot(self, project_id: str, shot_id: str, changes: dict) -> dict:
        allowed = {"prompt", "narration", "locked"}
        if not changes or set(changes) - allowed:
            raise ValueError("仅支持修改镜头提示词、旁白或锁定状态")
        def edit(project):
            if project["status"] in {"running", "queued"}:
                raise ValueError("请先停止生成，再编辑镜头")
            shot = next((s for s in project["shots"] if s["id"] == shot_id), None)
            if shot is None:
                raise ValueError("镜头不存在")
            if shot.get("locked") and any(key != "locked" for key in changes):
                raise ValueError("请先解锁此镜头")
            for key in ("prompt", "narration"):
                if key in changes and (not isinstance(changes[key], str) or not changes[key].strip() or len(changes[key]) > (3000 if key == "prompt" else 100)):
                    raise ValueError("镜头提示词或旁白长度不合适")
            if "locked" in changes and type(changes["locked"]) is not bool:
                raise ValueError("锁定状态必须是布尔值")
            dirty = any(key in changes and changes[key] != shot.get(key) for key in ("prompt", "narration"))
            shot.update(changes)
            if dirty:
                shot.update(status="pending", audio=None, error=None)
                project.update(output=None, status="draft", stage="镜头已修改，可继续生成", progress=0)
        return self.update(project_id, edit)
