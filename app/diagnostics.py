from __future__ import annotations

import importlib.util
import platform
import re
import shutil
import subprocess
from pathlib import Path

from .assets import manifest, safe_path
from .config import executable, resolve


def doctor(root: Path, config: dict, mode: str = "real") -> dict:
    checks = []
    def add(name, ok, detail, *, required=True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "required": required})
    for binary in ("ffmpeg", "ffprobe"):
        try:
            add(binary, True, executable(root, config, binary))
        except FileNotFoundError as error:
            add(binary, False, str(error))
    add("字幕绘制", importlib.util.find_spec("PIL") is not None, "需要 Pillow；启动脚本会安装")
    if mode == "real":
        add("运行系统", platform.system() == "Windows", "真实生成需要 Windows x64 + NVIDIA；Mac 请使用演示模式")
        for label, value in (("Qwen 推理程序", config["llama"]["executable"]),
                             ("ComfyUI Python", config["comfy"]["python"]),
                             ("ComfyUI", config["comfy"]["directory"] + "/main.py")):
            path = resolve(root, value)
            add(label, path.is_file(), str(path))
        for asset in manifest(root)["assets"]:
            if asset["group"] == "models" and not asset.get("extract_to"):
                path = safe_path(root, asset["path"])
                add(asset["id"], path.is_file() and path.stat().st_size == asset["size"],
                    f"{asset['size'] / 1024**3:.2f} GiB · 安装时校验 SHA256，启动时检查文件长度")
        tts = resolve(root, config["tts"]["model_dir"])
        required = ["model.onnx", "voices.bin", "tokens.txt", "lexicon-us-en.txt", "lexicon-zh.txt",
                    "date-zh.fst", "number-zh.fst", "espeak-ng-data/phontab", "espeak-ng-data/phondata",
                    "espeak-ng-data/phonindex", "espeak-ng-data/intonations"]
        missing = [name for name in required if not (tts / name).is_file()]
        add("中文配音模型", not missing, "完整" if not missing else "缺少 " + ", ".join(missing))
        add("配音引擎", importlib.util.find_spec("sherpa_onnx") is not None, "需要 sherpa-onnx 1.13.8")
        try:
            result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
            match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", result.stdout)
            good = result.returncode == 0 and match and (int(match[1]), int(match[2])) >= (13, 3)
            add("NVIDIA 驱动", good, "本发行包需要驱动支持 CUDA 13.3；无需另装 CUDA Toolkit")
            memory = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, timeout=10)
            add("显卡信息", memory.returncode == 0, memory.stdout.strip() or memory.stderr.strip(), required=False)
        except (OSError, subprocess.TimeoutExpired):
            add("NVIDIA 驱动", False, "未找到可用 nvidia-smi；请安装 NVIDIA 官方驱动")
    free = shutil.disk_usage(root).free / 1024**3
    add("可用磁盘", free >= 10, f"剩余 {free:.1f} GiB；首次完整安装建议至少 100 GiB", required=False)
    return {"ready": all(c["ok"] for c in checks if c["required"]), "checks": checks,
            "platform": platform.system(), "mode": mode}
