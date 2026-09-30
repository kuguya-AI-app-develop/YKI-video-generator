from pathlib import Path
import tempfile
import threading
import unittest

from app.jobs import JobManager
from app.storage import Store


class QueueCancellationTests(unittest.TestCase):
    def test_cancel_queued_project_allows_edit_and_requeue_before_active_job_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            first = store.create("正在生成的项目", "demo", 3)["id"]
            second = store.create("排队的项目", "demo", 3)["id"]
            store.update(second, lambda p: p.update(shots=[{
                "id": "S01", "prompt": "old", "narration": "旧旁白", "locked": False,
                "status": "pending", "versions": [],
            }]))
            started, release = threading.Event(), threading.Event()
            seen = []

            class FakePipeline:
                def run(self, project_id, cancel):
                    seen.append(project_id)
                    if project_id == first:
                        started.set()
                        release.wait(5)
                    store.update(project_id, lambda p: p.update(status="completed"))

            manager = JobManager(FakePipeline(), store)
            try:
                manager.enqueue(first)
                self.assertTrue(started.wait(2))
                manager.enqueue(second)
                cancelled = manager.cancel(second)
                self.assertEqual("cancelled", cancelled["status"])
                self.assertNotIn(second, manager.events)
                self.assertEqual(first, manager.active_project)
                self.assertFalse(manager.events[first].is_set())
                store.edit_shot(second, "S01", {"narration": "修改后的旁白"})
                manager.enqueue(second)
                release.set()
                manager.queue.join()
                self.assertEqual([first, second], seen)
                self.assertEqual("completed", store.get(second)["status"])
                self.assertEqual("修改后的旁白", store.get(second)["shots"][0]["narration"])
            finally:
                release.set()
                manager.shutdown()

    def test_active_cancellation_stays_registered_until_pipeline_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            project_id = store.create("运行中的项目", "demo", 3)["id"]
            started, release = threading.Event(), threading.Event()

            class FakePipeline:
                def run(self, project_id, cancel):
                    started.set()
                    release.wait(5)

            manager = JobManager(FakePipeline(), store)
            try:
                manager.enqueue(project_id)
                self.assertTrue(started.wait(2))
                manager.cancel(project_id)
                self.assertTrue(manager.events[project_id].is_set())
                with self.assertRaisesRegex(ValueError, "已经在队列"):
                    manager.enqueue(project_id)
            finally:
                release.set()
                manager.shutdown()
