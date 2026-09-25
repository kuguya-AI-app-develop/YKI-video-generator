from __future__ import annotations

import contextlib
import hashlib
import math
import platform
import random
import re
import threading
import wave
from pathlib import Path

from .config import executable, resolve
from .diagnostics import doctor
from .media import MediaTools
from .processes import Cancelled, ManagedProcess, check_cancel
from .providers.comfy import ComfyClient, build_workflow
from .providers.llama import create_plan, demo_plan
from .providers.tts import TTS
from .storage import Store, now, atomic_json


def silent_wav(path: Path, seconds: float = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * round(seconds * 24000))


def pad_narration(path: Path, minimum: float = 4.8) -> float:
    with wave.open(str(path), "rb") as source:
        parameters = source.getparams()
        frames = source.readframes(source.getnframes())
    current = parameters.nframes / parameters.framerate
    if current < minimum:
        frames += b"\0" * (math.ceil((minimum - current) * parameters.framerate) * parameters.sampwidth * parameters.nchannels)
        with wave.open(str(path), "wb") as output:
            output.setparams(parameters)
            output.writeframes(frames)
        current = len(frames) / parameters.sampwidth / parameters.nchannels / parameters.framerate
    return current


class Pipeline:
    def __init__(self, root: Path, config: dict, store: Store):
        self.root, self.config, self.store = root, config, store

    def stage(self, project_id: str, label: str, progress: int) -> None:
        self.store.update(project_id, lambda p: p.update(stage=label, progress=progress))
        self.store.event(project_id, label)

    def _llama_process(self, cancel):
        cfg = self.config["llama"]
        gpu_layers = cfg.get("gpu_layers", "auto")
        if not ((isinstance(gpu_layers, str) and gpu_layers in {"auto", "all"}) or
                (type(gpu_layers) is int and gpu_layers >= 0)):
            raise ValueError("llama.gpu_layers 必须为 auto、all 或非负整数。")
        command = [str(resolve(self.root, cfg["executable"])), "--model", str(resolve(self.root, cfg["model"])),
                   "--host", "127.0.0.1", "--port", str(cfg["port"]), "--ctx-size", str(cfg["context"]),
                   "--n-gpu-layers", str(gpu_layers), "--fit", "on", "--parallel", "1", "--jinja", "--flash-attn", "on",
                   "--alias", "local-planner", "--chat-template-kwargs", '{"enable_thinking":false}']
        return ManagedProcess(command, self.root, self.root / "logs/llama.log", cfg["port"], "/health", cfg["startup_timeout"], cancel)

    def _comfy_process(self, cancel):
        cfg = self.config["comfy"]
        command = [str(resolve(self.root, cfg["python"])), "-s", "main.py", "--windows-standalone-build",
                   "--listen", "127.0.0.1", "--port", str(cfg["port"]), "--disable-auto-launch",
                   "--disable-metadata", "--use-pytorch-cross-attention"]
        for name, flag in (("fast_disk", "--fast-disk"), ("disable_pinned_memory", "--disable-pinned-memory")):
            enabled = cfg.get(name, False)
            if type(enabled) is not bool:
                raise ValueError(f"comfy.{name} 必须为布尔值。")
            if enabled:
                command.append(flag)
        return ManagedProcess(command, resolve(self.root, cfg["directory"]), self.root / "logs/comfy.log",
                              cfg["port"], "/system_stats", cfg["startup_timeout"], cancel)

    def run(self, project_id: str, cancel: threading.Event) -> None:
        project = self.store.get(project_id)
        mode = project["mode"]
        demo = mode == "demo"
        diagnostics = doctor(self.root, self.config, mode)
        if not diagnostics["ready"]:
            detail = "; ".join(c["name"] + ": " + c["detail"] for c in diagnostics["checks"] if c["required"] and not c["ok"])
            raise RuntimeError("运行环境尚未就绪：" + detail)
        self.store.update(project_id, lambda p: p.update(status="running", error=None, cancel_requested=False))
        if not project.get("provenance"):
            fingerprint = hashlib.sha256((self.root / "config/models.lock.json").read_bytes()).hexdigest()
            self.store.update(project_id, lambda p: p.update(provenance={"models_manifest_sha256": fingerprint,
                                                                        "mode": mode, "created_at": now()}))
        media = MediaTools(executable(self.root, self.config, "ffmpeg"), executable(self.root, self.config, "ffprobe"), cancel_event=cancel)
        folder = self.store.folder(project_id)
        if not project["shots"]:
            self.stage(project_id, "生成故事与镜头计划" if not demo else "创建演示镜头（不调用 AI）", 3)
            check_cancel(cancel)
            if demo:
                plan = demo_plan(project["prompt"], project["shot_count"])
            else:
                with self._llama_process(cancel):
                    plan = create_plan(project["prompt"], project["shot_count"],
                                       base_url=f"http://127.0.0.1:{self.config['llama']['port']}",
                                       timeout=self.config["llama"]["request_timeout"])
                self.store.event(project_id, "编剧模型已退出，显存交给视频生成")
            check_cancel(cancel)
            shots = [{"id": f"S{i + 1:02}", "prompt": item["prompt"], "narration": item["narration"],
                      "locked": False, "status": "pending", "versions": [], "selected_version": None,
                      "audio": None, "video": None, "seed": random.randrange(2**32)} for i, item in enumerate(plan["shots"])]
            self.store.update(project_id, lambda p: p.update(title=plan["title"], character=plan["character"], style=plan["style"], shots=shots))
        project = self.store.get(project_id)
        # Missing completed assets are detected without silently substituting demo media.
        def detect_missing(p):
            for shot in p["shots"]:
                if shot["status"] == "completed" and any(not shot.get(k) or not (folder / shot[k]).is_file() for k in ("audio", "video")):
                    shot.update(status="pending", audio=None)
        self.store.update(project_id, detect_missing)
        project = self.store.get(project_id)
        pending = [shot for shot in project["shots"] if shot["status"] != "completed"]
        tts = TTS(self.config, self.root) if not demo else None
        for index, shot in enumerate(pending):
            check_cancel(cancel)
            version = f"v{len(shot['versions']) + 1:03}"
            audio_relative = f"renders/{shot['id']}/{version}.wav"
            audio_path = folder / audio_relative
            self.stage(project_id, f"准备 {shot['id']} 的旁白" if not demo else f"准备 {shot['id']} 演示音轨（静音）", 12 + round(index / max(1, len(pending)) * 8))
            if shot.get("audio") != audio_relative or not audio_path.is_file():
                if demo:
                    silent_wav(audio_path)
                else:
                    tts.synthesize(shot["narration"], audio_path)
                    pad_narration(audio_path)
            with wave.open(str(audio_path), "rb") as source:
                seconds = source.getnframes() / source.getframerate()
            if not demo and seconds > 14.5:
                raise ValueError(f"{shot['id']} 旁白长达 {seconds:.1f} 秒；请缩短该镜头旁白后继续")
            shot.update(audio=audio_relative, duration=max(5, seconds + 0.25) if not demo else seconds + 0.25,
                        pending_version=version)
            self.store.update(project_id, lambda p, s=shot: next(item for item in p["shots"] if item["id"] == s["id"]).update(s))
        check_cancel(cancel)
        context = self._comfy_process(cancel) if pending and not demo else contextlib.nullcontext()
        if pending and not demo:
            self.stage(project_id, "加载 H3 视频引擎", 22)
        with context:
            client = ComfyClient(f"http://127.0.0.1:{self.config['comfy']['port']}") if pending and not demo else None
            for index, shot in enumerate(pending):
                check_cancel(cancel)
                version = shot["pending_version"]
                relative = f"renders/{shot['id']}/{version}.mp4"
                destination = folder / relative
                self.stage(project_id, f"生成镜头 {shot['id']} · {index + 1}/{len(pending)}", 25 + round(index / len(pending) * 60))
                if demo:
                    media.demo_clip(destination, seconds=shot["duration"], width=360, height=640, index=index + 1)
                else:
                    prompt = (f"{project['style']}. Same protagonist in every shot: {project['character']}. "
                              f"{shot['prompt']} No speaking, no dialogue, no on-screen text. Ambient sound only.")
                    cfg = self.config["comfy"]
                    workflow = build_workflow(prompt, cfg["width"], cfg["height"], shot["duration"], shot["seed"],
                                              steps=cfg["steps"], filename_prefix=f"studio/{project_id}/{shot['id']}/{version}")
                    atomic_json(folder / f"renders/{shot['id']}/{version}.workflow.json", workflow)
                    client.validate_workflow(workflow)
                    prompt_id = client.submit(workflow)
                    self.store.update(project_id, lambda p: p.update(comfy_prompt_id=prompt_id))
                    history = client.wait(prompt_id, timeout=cfg["render_timeout"], cancel_event=cancel,
                                          on_progress=lambda message: self.store.event(project_id, message))
                    client.download_video(history, destination)
                check_cancel(cancel)
                if not any(s.get("codec_type") == "video" for s in media.probe(destination)["streams"]):
                    raise RuntimeError(f"{shot['id']} 未生成有效视频，已停止合成")
                record = {"id": version, "video": relative, "audio": shot["audio"], "prompt": shot["prompt"],
                          "narration": shot["narration"], "seed": shot["seed"], "created_at": now()}
                shot.update(status="completed", selected_version=version, video=relative, versions=shot["versions"] + [record])
                self.store.update(project_id, lambda p, s=shot: next(item for item in p["shots"] if item["id"] == s["id"]).update(s))
        check_cancel(cancel)
        self.stage(project_id, "合成视频、中文字幕与旁白", 90)
        project = self.store.get(project_id)
        output_folder = folder / "output"
        output_folder.mkdir(exist_ok=True)
        numbers = [int(match[1]) for path in output_folder.glob("final-*.mp4")
                   if (match := re.fullmatch(r"final-(\d+)\.mp4", path.name))]
        number = max(numbers, default=0) + 1
        output = f"output/final-{number:03}.mp4"
        media.assemble([folder / s["video"] for s in project["shots"]], [folder / s["audio"] for s in project["shots"]],
                       [s["narration"] for s in project["shots"]], folder / output,
                       width=self.config["video"]["width"], height=self.config["video"]["height"], ai_label=not demo)
        check_cancel(cancel)
        metadata = media.probe(folder / output)
        self.store.update(project_id, lambda p: p.update(status="completed", stage="演示完成（非 AI 视频）" if demo else "视频已完成",
                                                       progress=100, output=output, error=None,
                                                       duration=float(metadata["format"]["duration"])))
        self.store.event(project_id, "成片已保存，原始镜头与版本一并保留")
