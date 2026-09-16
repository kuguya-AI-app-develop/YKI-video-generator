from array import array
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from app.media import MediaTools, _timestamp
from app.providers.tts import TTS


FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


def write_tone(path: Path, seconds: float, frequency=400):
    samples = array("h", (int(5000 * math.sin(2 * math.pi * frequency * index / 24000))
                          for index in range(round(seconds * 24000))))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(samples.tobytes())


@unittest.skipUnless(Path(FFMPEG).is_file() and Path(FFPROBE).is_file(), "FFmpeg not installed")
class MediaIntegrationTests(unittest.TestCase):
    def test_unicode_paths_trim_and_pad_with_continuous_audio(self):
        # Apostrophes, spaces, Chinese and brackets must stay out of FFmpeg filter syntax.
        with tempfile.TemporaryDirectory(prefix="短片 [test] ' ") as temporary:
            root = Path(temporary)
            media = MediaTools(FFMPEG, FFPROBE)
            short = media.demo_clip(root / "短 视频.mp4", seconds=0.3, width=180, height=320)
            long = media.demo_clip(root / "long.mp4", seconds=1.5, width=256, height=144, index=2)
            first, second = root / "旁白'1.wav", root / "旁白[2].wav"
            write_tone(first, 0.65)
            write_tone(second, 0.41, 700)
            output = media.assemble([short, long], [first, second],
                                    ["你好，世界。", "雨停了，一个新的故事开始。"],
                                    root / "成 片.mp4", width=180, height=320)
            metadata = media.probe(output)
            video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
            audio = next(s for s in metadata["streams"] if s["codec_type"] == "audio")
            expected = math.ceil((0.65 + 0.2) * 24) / 24 + math.ceil((0.41 + 0.2) * 24) / 24
            self.assertAlmostEqual(float(metadata["format"]["duration"]), expected, delta=0.045)
            self.assertEqual((video["codec_name"], video["pix_fmt"], video["width"], video["height"]),
                             ("h264", "yuv420p", 180, 320))
            self.assertEqual(video["r_frame_rate"], "24/1")
            self.assertEqual(audio["codec_name"], "aac")
            subtitles = output.with_suffix(".srt").read_text(encoding="utf-8")
            self.assertIn("00:00:00,000 --> 00:00:00,650", subtitles)
            self.assertIn("00:00:00,875 --> 00:00:01,285", subtitles)
            self.assertIn("你好，世界。", subtitles)
            # Decode the final audio; a real tone survives in both narration segments.
            decoded = subprocess.run([FFMPEG, "-v", "error", "-i", str(output), "-f", "s16le",
                                      "-ac", "1", "-ar", "24000", "pipe:1"],
                                     capture_output=True, check=True).stdout
            samples = array("h")
            samples.frombytes(decoded)
            for start in [0.1, 0.98]:
                section = samples[int(start * 24000):int((start + 0.1) * 24000)]
                self.assertGreater(max(abs(v) for v in section), 1000)

    def test_invalid_media_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "existing.mp4"
            destination.write_bytes(b"previous output")
            with self.assertRaises(ValueError):
                MediaTools(FFMPEG, FFPROBE).assemble([], [], [], destination)
            self.assertEqual(destination.read_bytes(), b"previous output")


class TTSTests(unittest.TestCase):
    def test_missing_model_reports_installation_problem(self):
        with tempfile.TemporaryDirectory() as temporary:
            tts = TTS({}, Path(temporary))
            with self.assertRaisesRegex(RuntimeError, "重新运行安装器"):
                tts.synthesize("你好", Path(temporary) / "audio.wav")

    def test_generated_samples_written_as_pcm_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "配 音.wav"
            tts = TTS({"speaker_id": 3}, root)
            tts._sherpa = SimpleNamespace(GenerationConfig=SimpleNamespace)
            engine = SimpleNamespace(num_speakers=103,
                                     generate=lambda text, config: SimpleNamespace(
                                         samples=[-1.0, 0.0, 1.0, 0.5], sample_rate=24000))
            with patch.object(tts, "_load", return_value=engine):
                duration = tts.synthesize("你好", destination)
            self.assertAlmostEqual(duration, 4 / 24000)
            with wave.open(str(destination), "rb") as output:
                self.assertEqual(output.getnframes(), 4)
                self.assertEqual(output.getsampwidth(), 2)
                self.assertEqual(output.getnchannels(), 1)
                self.assertEqual(output.getframerate(), 24000)

    def test_empty_model_response_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "audio.wav"
            destination.write_bytes(b"previous")
            tts = TTS({}, Path(temporary))
            tts._sherpa = SimpleNamespace(GenerationConfig=SimpleNamespace)
            engine = SimpleNamespace(num_speakers=103,
                                     generate=lambda *args: SimpleNamespace(samples=[], sample_rate=24000))
            with patch.object(tts, "_load", return_value=engine):
                with self.assertRaisesRegex(RuntimeError, "空音频"):
                    tts.synthesize("你好", destination)
            self.assertEqual(destination.read_bytes(), b"previous")

    def test_srt_timestamp_rollover(self):
        self.assertEqual(_timestamp(59.9999), "00:01:00,000")


class MediaCancellationTests(unittest.TestCase):
    def test_cancellation_terminates_and_reaps_owned_subprocess(self):
        cancel = threading.Event()
        media = MediaTools(FFMPEG, FFPROBE, cancel_event=cancel)
        children = []
        original_popen = subprocess.Popen

        def capture_process(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            children.append(process)
            return process

        timer = threading.Timer(0.3, cancel.set)
        started = time.monotonic()
        timer.start()
        try:
            with patch("app.media.subprocess.Popen", side_effect=capture_process):
                with self.assertRaisesRegex(RuntimeError, "已取消"):
                    media._run([sys.executable, "-c", "import time; time.sleep(60)"])
            self.assertLess(time.monotonic() - started, 3)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].returncode)
            self.assertIsNotNone(children[0].poll())
        finally:
            timer.cancel()


if __name__ == "__main__":
    unittest.main()
