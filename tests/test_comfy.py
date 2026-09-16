"""HTTP contract tests; these do not run the H3 model or claim GPU acceptance."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
import uuid

from app.providers.comfy import (
    ComfyCancelled, ComfyClient, ComfyError, ComfyTimeout, build_workflow,
)


@contextmanager
def fake_comfy(routes):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_route()

        def do_POST(self):
            self.handle_route()

        def handle_route(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            calls.append((self.command, self.path, json.loads(body) if body else None))
            status, content, mime = routes(self.command, self.path, calls[-1][2])
            encoded = content if isinstance(content, bytes) else json.dumps(content).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield ComfyClient(f"http://127.0.0.1:{server.server_port}", timeout=2), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class WorkflowTests(unittest.TestCase):
    def test_native_av_graph_and_frame_rounding(self):
        workflow = build_workflow("窗边的一只猫", 768, 1344, 5, 123)
        self.assertEqual(workflow["5"]["inputs"]["length"], 124)
        self.assertEqual(workflow["5"]["inputs"]["prompt"], "窗边的一只猫")
        self.assertEqual(workflow["11"]["inputs"]["samples"], ["10", 0])
        self.assertEqual(workflow["12"]["inputs"]["samples"], ["10", 0])
        self.assertEqual(workflow["13"]["inputs"]["audio"], ["12", 0])
        self.assertEqual(workflow["14"]["inputs"]["format.codec"], "h264")
        self.assertEqual(workflow["9"]["inputs"]["steps"], 20)
        self.assertFalse(any("Lora" in node["class_type"] for node in workflow.values()))
        second = build_workflow("另一个镜头", 1344, 768, 15, 456)
        self.assertEqual(second["5"]["inputs"]["length"], 362)
        self.assertEqual(workflow["6"]["inputs"]["noise_seed"], 123)
        for node in workflow.values():
            for value in node["inputs"].values():
                if isinstance(value, list):
                    self.assertIn(value[0], workflow)

    def test_rejects_invalid_dimensions_duration_and_output_path(self):
        for field, value in (("width", 720), ("seconds", float("nan")), ("seconds", 1), ("seed", -1), ("filename_prefix", "../outside"), ("filename_prefix", "C:\\outside"), ("steps", True)):
            kwargs = dict(prompt="hello", width=768, height=1344, seconds=5, seed=1)
            kwargs[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build_workflow(**kwargs)


class ComfyHTTPTests(unittest.TestCase):
    def test_submit_wait_download_native_images_output_and_free(self):
        prompt_id = str(uuid.uuid4())
        video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"video" * 100
        history = {"status": {"completed": True, "status_str": "success", "messages": []}, "outputs": {"14": {"images": [{"filename": "clip_00001_.mp4", "subfolder": "aigc/镜头 1", "type": "output"}], "animated": [True]}}}
        poll_count = 0

        def route(method, path, data):
            nonlocal poll_count
            if path == "/system_stats":
                return 200, {"devices": [{"name": "fake GPU"}]}, "application/json"
            if path == "/prompt":
                self.assertEqual(data["prompt"]["5"]["inputs"]["prompt"], "测试")
                self.assertTrue(data["client_id"])
                return 200, {"prompt_id": prompt_id, "node_errors": {}}, "application/json"
            if path == "/history/" + prompt_id:
                poll_count += 1
                return 200, {} if poll_count == 1 else {prompt_id: history}, "application/json"
            if path.startswith("/view?"):
                self.assertEqual(parse_qs(urlsplit(path).query)["subfolder"], ["aigc/镜头 1"])
                return 200, video_bytes, "video/mp4"
            if path == "/free":
                self.assertEqual(data, {"unload_models": True, "free_memory": True})
                return 200, b"", "application/json"
            return 404, {}, "application/json"

        with fake_comfy(route) as (client, calls), tempfile.TemporaryDirectory() as folder:
            self.assertEqual(client.check_health()["devices"][0]["name"], "fake GPU")
            submitted = client.submit(build_workflow("测试", 768, 1344, 5, 0))
            progress = []
            result = client.wait(submitted, timeout=3, poll_interval=0.01, on_progress=progress.append)
            saved = client.download_video(result, Path(folder) / "片段.mp4")
            self.assertEqual(saved.read_bytes(), video_bytes)
            self.assertGreaterEqual(len(progress), 2)
            self.assertFalse(list(Path(folder).glob("*.part")))
            client.free()

    def test_preflight_reports_missing_native_node_and_model(self):
        workflow = build_workflow("test", 768, 1344, 5, 0)
        info = {node["class_type"]: {"input": {"required": {}}} for node in workflow.values()}
        info["UNETLoader"]["input"]["required"]["unet_name"] = [[], {}]
        with fake_comfy(lambda *args: (200, info, "application/json")) as (client, _):
            with self.assertRaisesRegex(ComfyError, "未找到模型"):
                client.validate_workflow(workflow)
            info["UNETLoader"]["input"]["required"]["unet_name"][0] = [workflow["1"]["inputs"]["unet_name"]]
            client.validate_workflow(workflow)
            del info["MiniMaxH3ImageToVideo"]
            with self.assertRaisesRegex(ComfyError, "缺少节点"):
                client.validate_workflow(workflow)

    def test_backend_error_includes_failing_node(self):
        prompt_id = str(uuid.uuid4())
        result = {prompt_id: {"status": {"completed": False, "status_str": "error", "messages": [["execution_error", {"node_id": "10", "node_type": "SamplerCustomAdvanced", "exception_message": "CUDA out of memory"}]]}, "outputs": {}}}
        with fake_comfy(lambda *args: (200, result, "application/json")) as (client, _):
            with self.assertRaisesRegex(ComfyError, "SamplerCustomAdvanced.*CUDA out of memory"):
                client.wait(prompt_id, poll_interval=0.01)

    def test_submission_validation_errors_are_actionable(self):
        body = {"error": {"message": "Prompt failed validation"}, "node_errors": {"2": {"errors": [{"message": "Value not in list", "details": "clip_name missing.safetensors"}]}}}
        with fake_comfy(lambda *args: (400, body, "application/json")) as (client, _):
            with self.assertRaisesRegex(ComfyError, "HTTP 400.*节点 2.*missing.safetensors"):
                client.submit(build_workflow("test", 768, 1344, 5, 0))

    def test_cancel_targets_one_uuid_without_global_queue_mutation(self):
        prompt_id = str(uuid.uuid4())
        event = threading.Event()
        event.set()
        with fake_comfy(lambda *args: (200, b"", "application/json")) as (client, calls):
            with self.assertRaises(ComfyCancelled):
                client.wait(prompt_id, cancel_event=event)
            self.assertEqual(calls, [("POST", "/queue", {"delete": [prompt_id]}), ("POST", "/interrupt", {"prompt_id": prompt_id})])

    def test_timeout_cancels_only_this_prompt(self):
        prompt_id = str(uuid.uuid4())
        with fake_comfy(lambda *args: (200, {}, "application/json")) as (client, calls):
            with self.assertRaises(ComfyTimeout):
                client.wait(prompt_id, timeout=0.02, poll_interval=0.005)
            self.assertEqual(calls[-2:], [("POST", "/queue", {"delete": [prompt_id]}), ("POST", "/interrupt", {"prompt_id": prompt_id})])

    def test_download_failure_preserves_previous_file(self):
        history = {"outputs": {"14": {"images": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]}}}
        with fake_comfy(lambda *args: (200, b"bad result", "text/html")) as (client, _), tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing.mp4"
            target.write_bytes(b"old video")
            with self.assertRaises(ComfyError):
                client.download_video(history, target)
            self.assertEqual(target.read_bytes(), b"old video")
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_download_rejects_path_traversal_from_history(self):
        history = {"outputs": {"14": {"images": [{"filename": "clip.mp4", "subfolder": "../../private", "type": "output"}]}}}
        with fake_comfy(lambda *args: (200, {}, "application/json")) as (client, calls), tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                client.download_video(history, Path(folder) / "clip.mp4")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
