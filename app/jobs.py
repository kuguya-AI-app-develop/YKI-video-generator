from __future__ import annotations

import queue
import threading

from .pipeline import Pipeline
from .processes import Cancelled
from .providers.comfy import ComfyCancelled
from .storage import Store


class JobManager:
    def __init__(self, pipeline: Pipeline, store: Store):
        self.pipeline, self.store = pipeline, store
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.events = {}
        self.active_project = None
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True, name="video-queue")
        self.worker.start()

    def enqueue(self, project_id: str) -> dict:
        with self.lock:
            if project_id in self.events:
                raise ValueError("此项目已经在队列中")
            if self.stopping.is_set():
                raise ValueError("服务正在停止")
            with self.store.lock:
                project = self.store.get(project_id)
                if project["status"] == "completed" and project.get("output") and (self.store.folder(project_id) / project["output"]).is_file():
                    return project
                project.update(status="queued", stage="已加入生成队列", error=None, cancel_requested=False)
                self.store.save(project)
            self.events[project_id] = threading.Event()
            self.queue.put(project_id)
            return project

    def cancel(self, project_id: str) -> dict:
        with self.lock:
            event = self.events.get(project_id)
            if event:
                event.set()
                return self.store.update(project_id, lambda p: p.update(cancel_requested=True, stage="正在停止，已完成镜头会保留"))
            return self.store.get(project_id)

    def _work(self):
        while not self.stopping.is_set():
            try:
                project_id = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.lock:
                event = self.events[project_id]
                self.active_project = project_id
            try:
                if event.is_set():
                    raise Cancelled("任务已取消")
                self.pipeline.run(project_id, event)
            except (Cancelled, ComfyCancelled) as error:
                self.store.update(project_id, lambda p: p.update(status="cancelled", stage=str(error), error=None))
            except Exception as error:
                message = str(error)[:4000]
                cancelled = event.is_set()
                self.store.update(project_id, lambda p: p.update(status="cancelled" if cancelled else "failed",
                                  stage="任务已停止" if cancelled else "生成失败，可修复后继续", error=None if cancelled else message))
                self.store.event(project_id, message)
            finally:
                with self.lock:
                    self.events.pop(project_id, None)
                    self.active_project = None
                self.queue.task_done()

    def shutdown(self):
        self.stopping.set()
        with self.lock:
            for event in self.events.values():
                event.set()
        self.worker.join(timeout=20)
