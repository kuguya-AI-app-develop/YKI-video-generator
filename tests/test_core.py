from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app.assets import download
from app.config import ROOT, load
from app.instance import InstanceLock
from app.jobs import JobManager
from app.pipeline import Pipeline
from app.providers.llama import validate_plan
from app.server import Application, make_handler, serve
from app.storage import Store


class CoreStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))

    def test_recovery_preserves_finished_shots_and_locked_edits_fail(self):
        project = self.store.create("雨夜里的一封信", "demo", 3)
        project.update(status="running", shots=[{"id": "S01", "prompt": "old", "narration": "旧旁白", "locked": True, "status": "completed", "versions": ["v001"]}])
        self.store.save(project)
        self.store.recover()
        recovered = self.store.get(project["id"])
        self.assertEqual("interrupted", recovered["status"])
        self.assertEqual(["v001"], recovered["shots"][0]["versions"])
        with self.assertRaisesRegex(ValueError, "解锁"):
            self.store.edit_shot(project["id"], "S01", {"narration": "新旁白"})
        self.store.edit_shot(project["id"], "S01", {"locked": False})
        changed = self.store.edit_shot(project["id"], "S01", {"narration": "新旁白"})
        self.assertEqual("pending", changed["shots"][0]["status"])
        self.assertEqual(["v001"], changed["shots"][0]["versions"])

    def test_model_plan_rejects_wrong_shot_count_and_long_narration(self):
        data = {"title": "雨夜", "character": "one person", "style": "film", "shots": [{"prompt": "night", "narration": "一封信"}] * 3}
        self.assertIs(data, validate_plan(data, 3))
        with self.assertRaises(ValueError):
            validate_plan(data, 6)
        data["shots"][0]["narration"] = "长" * 100
        with self.assertRaises(ValueError):
            validate_plan(data, 3)

    def test_instance_lock_excludes_second_process_context(self):
        path = Path(self.temp.name) / "instance.lock"
        with InstanceLock(path):
            with self.assertRaisesRegex(RuntimeError, "已有"):
                with InstanceLock(path):
                    self.fail("second lock acquired")
        with InstanceLock(path):
            pass

    def test_installer_runtime_lock_blocks_app_before_recovery(self):
        root = Path(self.temp.name)
        with InstanceLock(root / "runtime/.studio-runtime.lock"):
            with patch("app.server.Application") as application:
                with self.assertRaisesRegex(RuntimeError, "安装器"):
                    serve(root, {"projects_dir": "custom-projects", "port": 0})
                application.assert_not_called()
        self.assertFalse((root / "custom-projects").exists())

    def test_single_worker_and_missing_final_can_be_reassembled(self):
        store = self.store
        seen, concurrency = [], []
        first_started, release = threading.Event(), threading.Event()
        class FakePipeline:
            active = 0
            def run(self, project_id, cancel):
                self.active += 1
                concurrency.append(self.active)
                seen.append(project_id)
                first_started.set()
                release.wait(3)
                store.update(project_id, lambda p: p.update(status="completed", output="output/missing.mp4"))
                self.active -= 1
        manager = JobManager(FakePipeline(), store)
        self.addCleanup(manager.shutdown)
        one = store.create("第一个", "demo", 3)["id"]
        two = store.create("第二个", "demo", 3)["id"]
        manager.enqueue(one)
        self.assertTrue(first_started.wait(2))
        with self.assertRaises(ValueError):
            manager.enqueue(one)
        manager.enqueue(two)
        release.set()
        manager.queue.join()
        self.assertEqual([one, two], seen)
        self.assertEqual([1, 1], concurrency)
        manager.enqueue(one)
        manager.queue.join()
        self.assertEqual([one, two, one], seen)


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = b"verified model data" * 500

    def start_server(self, *, bad=False, ignore_range=False):
        content = self.content
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                start = int(self.headers.get("Range", "bytes=0-")[6:-1])
                seen.append(start)
                if ignore_range:
                    start = 0
                self.send_response(206 if start else 200)
                if start:
                    self.send_header("Content-Range", f"bytes {start}-{len(content)-1}/{len(content)}")
                self.end_headers()
                self.wfile.write((b"X" * len(content) if bad else content)[start:])
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return {"id": "fixture", "url": f"http://127.0.0.1:{server.server_port}/model", "path": "model.bin",
                "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}, seen

    def test_resume_verifies_complete_file(self):
        asset, seen = self.start_server()
        (self.root / "model.bin.part").write_bytes(self.content[:123])
        destination = download(asset, self.root, report=lambda _: None, retries=1)
        self.assertEqual([123], seen)
        self.assertEqual(self.content, destination.read_bytes())

    def test_server_ignoring_range_restarts_without_duplicating_bytes(self):
        asset, _ = self.start_server(ignore_range=True)
        (self.root / "model.bin.part").write_bytes(self.content[:200])
        self.assertEqual(self.content, download(asset, self.root, report=lambda _: None, retries=1).read_bytes())

    def test_bad_download_does_not_replace_existing_file(self):
        asset, _ = self.start_server(bad=True)
        destination = self.root / "model.bin"
        destination.write_bytes(b"previous file")
        with self.assertRaises(RuntimeError):
            download(asset, self.root, report=lambda _: None, retries=1)
        self.assertEqual(b"previous file", destination.read_bytes())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = load()
        config.update(mode="demo", projects_dir=self.temp.name)
        self.app = Application(ROOT, config)
        self.addCleanup(self.app.jobs.shutdown)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def test_cross_site_mutation_and_host_spoofing_are_rejected(self):
        req = urllib.request.Request(self.url + "/api/projects", data=b'{}', headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(403, caught.exception.code)
        req = urllib.request.Request(self.url + "/api/status", headers={"Host": "evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(403, caught.exception.code)
        self.assertEqual([], self.app.store.list())

    def test_video_ranges_and_path_traversal(self):
        project = self.app.store.create("测试", "demo", 3)
        output = self.app.store.folder(project["id"]) / "output"
        output.mkdir()
        (output / "movie.mp4").write_bytes(b"0123456789")
        req = urllib.request.Request(self.url + f"/files/{project['id']}/output/movie.mp4", headers={"Range": "bytes=3-6"})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(206, response.status)
            self.assertEqual(b"3456", response.read())
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url + f"/files/{project['id']}/%2e%2e/%2e%2e/secret.mp4")
        self.assertEqual(400, caught.exception.code)


class DemoAcceptance(unittest.TestCase):
    def test_full_demo_and_local_redo_preserve_other_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            config = load()
            config["video"].update(width=180, height=320)
            project = store.create("雨夜里，邮递员收到一封写给明天的信", "demo", 3)
            pipeline = Pipeline(ROOT, config, store)
            pipeline.run(project["id"], threading.Event())
            complete = store.get(project["id"])
            self.assertEqual("completed", complete["status"])
            folder = store.folder(project["id"])
            self.assertTrue((folder / complete["output"]).is_file())
            original = {s["id"]: hashlib.sha256((folder / s["video"]).read_bytes()).hexdigest() for s in complete["shots"]}
            # Missing lower-numbered exports must not overwrite a newer export.
            existing = folder / "output/final-009.mp4"
            existing.write_bytes(b"preserve this existing result")
            store.edit_shot(project["id"], "S02", {"narration": "第二个镜头已修改"})
            pipeline.run(project["id"], threading.Event())
            updated = store.get(project["id"])
            self.assertEqual("output/final-010.mp4", updated["output"])
            self.assertEqual(b"preserve this existing result", existing.read_bytes())
            for shot in updated["shots"]:
                if shot["id"] == "S02":
                    self.assertEqual(2, len(shot["versions"]))
                else:
                    self.assertEqual(1, len(shot["versions"]))
                    self.assertEqual(original[shot["id"]], hashlib.sha256((folder / shot["video"]).read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
