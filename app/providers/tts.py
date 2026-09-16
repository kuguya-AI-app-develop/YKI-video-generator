"""Offline Chinese narration with the Apache-2.0 Kokoro v1.1 model."""

from __future__ import annotations

from array import array
import math
import os
from pathlib import Path
import sys
import tempfile
import wave


class TTS:
    """Load Kokoro lazily on CPU; model installation belongs to the installer."""

    def __init__(self, config: dict, root: Path):
        self.config = config.get("tts", config)
        self.root = Path(root).resolve()
        self._engine = None
        self._sherpa = None

    def _load(self):
        if self._engine is not None:
            return self._engine
        directory = Path(self.config.get("model_dir", "models/kokoro-multi-lang-v1_1"))
        if not directory.is_absolute():
            directory = self.root / directory
        required = ["model.onnx", "voices.bin", "tokens.txt", "lexicon-us-en.txt",
                    "lexicon-zh.txt", "date-zh.fst", "number-zh.fst",
                    "espeak-ng-data/phontab", "espeak-ng-data/phonindex",
                    "espeak-ng-data/phondata", "espeak-ng-data/intonations"]
        missing = [name for name in required if not (directory / name).is_file()]
        if missing:
            raise RuntimeError("配音模型未安装完整，请重新运行安装器。缺少：" + ", ".join(missing))
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("缺少 sherpa-onnx，请重新运行安装器安装配音依赖。") from exc
        self._sherpa = sherpa_onnx
        model = sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(directory / "model.onnx"),
            voices=str(directory / "voices.bin"),
            tokens=str(directory / "tokens.txt"),
            data_dir=str(directory / "espeak-ng-data"),
            lexicon=",".join(str(directory / name) for name in
                             ["lexicon-us-en.txt", "lexicon-zh.txt"]),
        )
        settings = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=model, provider="cpu", debug=False,
                num_threads=max(1, min(16, int(self.config.get("threads", 4)))),
            ),
            rule_fsts=",".join(str(directory / name) for name in ["date-zh.fst", "number-zh.fst"]),
            max_num_sentences=1,
        )
        if not settings.validate():
            raise RuntimeError("Kokoro 配音配置无效，请检查模型目录及安装日志。")
        self._engine = sherpa_onnx.OfflineTts(settings)
        return self._engine

    def synthesize(self, text: str, destination: Path) -> float:
        """Write a mono PCM16 WAV atomically and return its exact duration."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("配音文本不能为空。")
        speed = float(self.config.get("speed", 1.0))
        if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise ValueError("配音速度须在 0.5–2.0 之间。")
        engine = self._load()
        sid = int(self.config.get("speaker_id", 3))
        if not 0 <= sid < engine.num_speakers:
            raise ValueError(f"配音音色 ID 无效：{sid}")
        generation = self._sherpa.GenerationConfig()
        generation.sid = sid
        generation.speed = speed
        generation.silence_scale = 0.2
        audio = engine.generate(text.strip(), generation)
        if len(audio.samples) == 0 or audio.sample_rate <= 0:
            raise RuntimeError("配音模型返回了空音频，未创建输出文件。")
        samples = array("h", (int(max(-1.0, min(1.0, float(value))) * 32767)
                              for value in audio.samples))
        if sys.byteorder != "little":
            samples.byteswap()
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(suffix=".wav", dir=destination.parent)
        os.close(descriptor)
        try:
            with wave.open(temporary, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(audio.sample_rate)
                output.writeframes(samples.tobytes())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return len(samples) / audio.sample_rate
