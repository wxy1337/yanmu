from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

from .control import check_cancelled


class MediaError(RuntimeError):
    pass


def _binary(env_name: str, fallback: str, configured: str = "") -> str:
    configured = configured or os.getenv(env_name, "")
    found = configured or shutil.which(fallback)
    if not found and fallback == "ffmpeg":
        try:
            import imageio_ffmpeg

            found = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError, OSError):
            found = None
    if not found:
        raise MediaError(
            f"未找到 {fallback}。请安装 FFmpeg 并加入 PATH，或设置 {env_name} 环境变量。"
        )
    return found


def ensure_media_tools() -> tuple[str, str | None]:
    from .config import get_settings

    settings = get_settings()
    ffmpeg = _binary("FFMPEG_BINARY", "ffmpeg", settings.ffmpeg_binary)
    try:
        ffprobe = _binary("FFPROBE_BINARY", "ffprobe", settings.ffprobe_binary)
    except MediaError:
        ffprobe = None
    return ffmpeg, ffprobe


HARDWARE_ENCODERS = {
    "h264_nvenc": "NVIDIA NVENC",
    "h264_qsv": "Intel Quick Sync",
    "h264_amf": "AMD AMF",
    "h264_videotoolbox": "Apple VideoToolbox",
}


def _parse_hardware_encoders(output: str) -> list[dict[str, str]]:
    available: list[dict[str, str]] = []
    for encoder, label in HARDWARE_ENCODERS.items():
        if any(line.split()[1:2] == [encoder] for line in output.splitlines()):
            available.append({"encoder": encoder, "label": label})
    return available


@lru_cache(maxsize=1)
def available_hardware_encoders() -> list[dict[str, str]]:
    try:
        ffmpeg, _ = ensure_media_tools()
        result = _run([ffmpeg, "-hide_banner", "-encoders"])
        return _parse_hardware_encoders(result.stdout)
    except MediaError:
        return []


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    from .config import get_settings

    check_cancelled()
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=startupinfo,
    )
    deadline = time.monotonic() + get_settings().media_timeout_seconds
    try:
        while True:
            check_cancelled()
            if time.monotonic() >= deadline:
                raise MediaError("媒体处理超时，可调整 MEDIA_TIMEOUT_SECONDS 后重试。")
            try:
                stdout, stderr = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        process.kill()
        process.communicate()
        raise
    result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-8:]
        raise MediaError("FFmpeg 处理失败：\n" + "\n".join(detail))
    return result


def probe_duration(source: Path) -> float | None:
    _, ffprobe = ensure_media_tools()
    if not ffprobe:
        try:
            import av

            with av.open(str(source)) as container:
                if container.duration is not None:
                    return float(container.duration / av.time_base)
                for stream in container.streams.video:
                    if stream.duration is not None and stream.time_base is not None:
                        return float(stream.duration * stream.time_base)
        except Exception:
            # Duration is only used for progress reporting; processing can continue without it.
            return None
        return None
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(source),
        ]
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def extract_audio(source: Path, destination: Path) -> None:
    ffmpeg, _ = ensure_media_tools()
    _run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )


def _ass_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    value = value.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return f"ass=filename='{value}'"


def _video_codec_args(encoder: str) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", encoder, "-preset", "medium", "-global_quality", "20"]
    if encoder == "h264_amf":
        return ["-c:v", encoder, "-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"]
    if encoder == "h264_videotoolbox":
        return ["-c:v", encoder, "-q:v", "65"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]


def _burn_command(
    ffmpeg: str, source: Path, subtitle: Path, destination: Path, encoder: str
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vf",
        _ass_filter_path(subtitle),
        *_video_codec_args(encoder),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(destination),
    ]


def burn_subtitles(
    source: Path,
    subtitle: Path,
    destination: Path,
    acceleration: str = "auto",
    preferred_encoder: str = "auto",
) -> str:
    ffmpeg, _ = ensure_media_tools()
    hardware = available_hardware_encoders()
    candidates = [item["encoder"] for item in hardware]
    if acceleration == "cuda":
        candidates = [encoder for encoder in candidates if encoder == "h264_nvenc"]
    if preferred_encoder != "auto":
        candidates = [preferred_encoder] if preferred_encoder in candidates else []

    if acceleration != "cpu" and candidates:
        encoder = candidates[0]
        try:
            _run(_burn_command(ffmpeg, source, subtitle, destination, encoder))
            return HARDWARE_ENCODERS[encoder]
        except MediaError:
            # An encoder can be compiled into FFmpeg but unavailable with the current driver.
            destination.unlink(missing_ok=True)

    _run(_burn_command(ffmpeg, source, subtitle, destination, "libx264"))
    return "CPU x264（GPU 编码不可用时自动回退）" if acceleration != "cpu" else "CPU x264"
