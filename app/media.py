"""FFmpeg assembly with CPU-rendered captions and narration-led timing."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time


def _dimensions(width: int, height: int) -> None:
    if width < 64 or height < 64 or width % 2 or height % 2:
        raise ValueError("视频宽高须为不小于 64 的偶数。")


def _font(size: int):
    from PIL import ImageFont

    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [os.environ.get("AIGC_FONT", ""), windows / "msyh.ttc",
                  windows / "simhei.ttf", "/System/Library/Fonts/Supplemental/Songti.ttc",
                  "/System/Library/Fonts/STHeiti Light.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(str(candidate), size=size)
    raise RuntimeError("未找到中文字体。请安装微软雅黑/思源黑体，或用 AIGC_FONT 指向字体文件。")


def _overlay(text: str, path: Path, width: int, height: int, ai_label: bool) -> None:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = _font(max(14, round(width * 0.047)))
    max_width = width * 0.85
    lines, current = [], ""
    # Pixel wrapping also handles Chinese, which usually has no word spaces.
    for character in " ".join(text.split()):
        if current and draw.textlength(current + character, font=font) > max_width:
            lines.append(current)
            current = ""
        current += character
    if current:
        lines.append(current)
    line_height = round(font.size * 1.5)
    if len(lines) * line_height > height * 0.42:
        raise ValueError("单镜头字幕过长，请缩短旁白后重新生成。")
    if lines:
        bottom = height - round(height * 0.075)
        top = bottom - len(lines) * line_height
        draw.rounded_rectangle((width * 0.04, top - font.size * 0.4,
                                width * 0.96, bottom + font.size * 0.3),
                               radius=font.size // 3, fill=(0, 0, 0, 170))
        for index, line in enumerate(lines):
            draw.text((width / 2, top + index * line_height), line, font=font,
                      anchor="mt", fill="white", stroke_width=1, stroke_fill="black")
    if ai_label:
        label_font = _font(max(12, round(width * 0.028)))
        label = "AI 生成"
        x, y = round(width * 0.05), round(height * 0.025)
        draw.rounded_rectangle((x - 6, y - 5,
                                x + draw.textlength(label, font=label_font) + 6,
                                y + label_font.size + 7),
                               radius=4, fill=(0, 0, 0, 170))
        draw.text((x, y), label, font=label_font, fill="white")
    canvas.save(path)


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


class MediaTools:
    def __init__(self, ffmpeg: str, ffprobe: str, *, cancel_event: threading.Event | None = None):
        # Resolve binaries before changing cwd for safe, fixed-name FFmpeg manifests.
        self.ffmpeg = shutil.which(str(ffmpeg)) or str(Path(ffmpeg).resolve())
        self.ffprobe = shutil.which(str(ffprobe)) or str(Path(ffprobe).resolve())
        self.cancel_event = cancel_event

    def _run(self, arguments: list[str], *, cwd: Path | None = None) -> str:
        if self.cancel_event and self.cancel_event.is_set():
            raise RuntimeError("媒体处理已取消。")
        try:
            process = subprocess.Popen(arguments, cwd=cwd, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True,
                                       encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 FFmpeg/FFprobe，请重新运行安装器。") from exc
        try:
            deadline = time.monotonic() + 1800
            while True:
                if self.cancel_event and self.cancel_event.is_set():
                    raise RuntimeError("媒体处理已取消。")
                if time.monotonic() >= deadline:
                    raise RuntimeError("媒体处理超过 30 分钟，已停止当前 FFmpeg 进程。")
                try:
                    stdout, stderr = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise RuntimeError("媒体处理失败：" + stderr[-4000:])
            return stdout
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=1)

    def probe(self, path: Path) -> dict:
        return json.loads(self._run([self.ffprobe, "-v", "error", "-show_format",
                                    "-show_streams", "-of", "json", str(Path(path).resolve())]))

    def assemble(self, clips: list[Path], narrations: list[Path], subtitles: list[str],
                 destination: Path, *, width=720, height=1280, ai_label=True) -> Path:
        """Burn captions, trim/freeze each clip to narration, then mux a single AAC track."""
        if not clips or len(clips) != len(narrations) or len(clips) != len(subtitles):
            raise ValueError("镜头、旁白和字幕须数量相同且不能为空。")
        _dimensions(width, height)
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        durations, audio_durations = [], []
        clips = [Path(path).resolve() for path in clips]
        narrations = [Path(path).resolve() for path in narrations]
        for clip, narration in zip(clips, narrations):
            if not any(s.get("codec_type") == "video" for s in self.probe(clip)["streams"]):
                raise ValueError(f"镜头没有视频轨：{clip.name}")
            metadata = self.probe(narration)
            audio = next((s for s in metadata["streams"] if s.get("codec_type") == "audio"), None)
            if not audio:
                raise ValueError(f"旁白没有音轨：{narration.name}")
            seconds = float(audio.get("duration") or metadata["format"].get("duration", 0))
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError(f"旁白时长无效：{narration.name}")
            audio_durations.append(seconds)
            # A short tail prevents abrupt cuts and aligns each transition to a frame.
            durations.append(math.ceil((seconds + 0.2) * 24) / 24)
        with tempfile.TemporaryDirectory(prefix="aigc-render-", dir=destination.parent) as temporary:
            work = Path(temporary)
            cues, offset = [], 0.0
            for index, (clip, text, duration) in enumerate(zip(clips, subtitles, durations)):
                overlay = work / f"caption-{index}.png"
                _overlay(text, overlay, width, height, ai_label)
                filters = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,"
                           f"setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={duration:.8f},"
                           f"trim=duration={duration:.8f}[base];"
                           "[base][1:v]overlay=0:0:shortest=1,format=yuv420p[outv]")
                self._run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                           "-i", str(clip), "-loop", "1", "-framerate", "24", "-i", overlay.name,
                           "-filter_complex", filters, "-map", "[outv]", "-an", "-t", f"{duration:.8f}",
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                           "-pix_fmt", "yuv420p", f"segment-{index}.mp4"], cwd=work)
                clean_text = " ".join(text.split())
                cues.append(f"{index + 1}\n{_timestamp(offset)} --> "
                            f"{_timestamp(offset + audio_durations[index])}\n{clean_text}\n")
                offset += duration
            (work / "video.ffconcat").write_text(
                "ffconcat version 1.0\n" + "".join(f"file segment-{i}.mp4\n" for i in range(len(clips))),
                encoding="utf-8")
            arguments = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                         "-f", "concat", "-safe", "0", "-i", "video.ffconcat"]
            for narration in narrations:
                arguments += ["-i", str(narration)]
            audio_filters = [f"[{i + 1}:a]aresample=48000,aformat=channel_layouts=mono,"
                             f"asetpts=PTS-STARTPTS,apad,atrim=duration={duration:.8f}[a{i}]"
                             for i, duration in enumerate(durations)]
            audio_filters.append("".join(f"[a{i}]" for i in range(len(clips))) +
                                 f"concat=n={len(clips)}:v=0:a=1[outa]")
            arguments += ["-filter_complex", ";".join(audio_filters), "-map", "0:v:0",
                          "-map", "[outa]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                          "-t", f"{sum(durations):.8f}", "-movflags", "+faststart",
                          "-metadata", "comment=AI-generated video" if ai_label else "comment=DEMO pipeline test",
                          "final.mp4"]
            self._run(arguments, cwd=work)
            (work / "final.srt").write_text("\n".join(cues), encoding="utf-8")
            os.replace(work / "final.mp4", destination)
            os.replace(work / "final.srt", destination.with_suffix(".srt"))
        return destination

    def demo_clip(self, destination: Path, seconds: float = 5, width=360, height=640, index=1) -> Path:
        """Create an explicitly marked placeholder for tests; no AI model is used."""
        from PIL import Image, ImageDraw

        _dimensions(width, height)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("演示时长必须为正数。")
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="aigc-demo-", dir=destination.parent) as temporary:
            work = Path(temporary)
            canvas = Image.new("RGB", (width, height), ["#16324f", "#345134", "#52375d"][(index - 1) % 3])
            draw = ImageDraw.Draw(canvas)
            for text, y, size in [("DEMO", height * 0.3, width * 0.15),
                                  (f"SHOT {index}", height * 0.43, width * 0.07),
                                  ("流程测试 / 非 AI 视频", height * 0.51, width * 0.045)]:
                draw.text((width / 2, y), text, font=_font(max(12, int(size))),
                          anchor="mt", fill="white")
            canvas.save(work / "demo.png")
            self._run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-loop", "1", "-framerate", "24", "-i", "demo.png", "-t", str(seconds),
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                       "-movflags", "+faststart", "demo.mp4"], cwd=work)
            os.replace(work / "demo.mp4", destination)
        return destination
