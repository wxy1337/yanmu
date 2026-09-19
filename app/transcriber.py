from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .control import check_cancelled
from .models import SubtitleSegment
from .subtitles import is_chinese_language
from .text import to_simplified

_model_cache: dict[tuple[str, str, str], Any] = {}
_model_lock = threading.Lock()
_cuda_disabled_reason: str | None = None
_cuda_search_directories: list[Path] = []
_cuda_directory_handles: list[Any] = []


def configure_cuda_dll_directory(configured: str = "") -> None:
    if os.name != "nt":
        return
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path(__file__).resolve().parents[1] / ".tools" / "cuda12-libs")
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_dir() or resolved in _cuda_search_directories:
            continue
        _cuda_search_directories.append(resolved)
        os.environ["PATH"] = str(resolved) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            _cuda_directory_handles.append(os.add_dll_directory(str(resolved)))


def cuda_device_count() -> int:
    """Return CUDA devices visible to CTranslate2 without failing app startup."""
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except (ImportError, RuntimeError, OSError, ValueError):
        return 0


def disable_cuda_for_process(reason: str) -> None:
    global _cuda_disabled_reason
    _cuda_disabled_reason = reason


def cuda_runtime_status() -> tuple[bool, str]:
    count = cuda_device_count()
    if count < 1:
        return False, "未检测到 NVIDIA CUDA 设备"
    if _cuda_disabled_reason:
        return False, f"CUDA 本次运行已禁用：{_cuda_disabled_reason}"
    if os.name != "nt":
        return True, "CUDA 设备可用"

    for library in ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll"):
        found_in_path = any(
            (Path(directory.strip('"')) / library).is_file()
            for directory in os.environ.get("PATH", "").split(os.pathsep)
            if directory
        )
        found_in_configured_directory = any(
            (directory / library).is_file() for directory in _cuda_search_directories
        )
        if not found_in_path and not found_in_configured_directory:
            return False, f"缺少或无法加载 {library}"
    return True, "CUDA 12 与 cuDNN 9 运行库可用"


def is_cuda_runtime_error(error: BaseException) -> bool:
    message = str(error).lower()
    markers = (
        "cuda",
        "cublas",
        "cudnn",
        "out of memory",
        "memory allocation",
        "driver version",
    )
    return any(marker in message for marker in markers)


def is_model_download_error(error: BaseException) -> bool:
    """Recognize incomplete caches and connection failures during model loading."""
    markers = (
        "cached snapshot",
        "incomplete",
        "localentrynotfound",
        "huggingface",
        "model.bin",
        "ssl",
        "connectionerror",
        "connecterror",
        "timed out",
    )
    current: BaseException | None = error
    while current is not None:
        description = f"{type(current).__name__} {current}".lower()
        if any(marker in description for marker in markers):
            return True
        current = current.__cause__ or current.__context__
    return False


def resolve_whisper_runtime(
    acceleration: str,
    configured_device: str = "auto",
    configured_compute_type: str = "auto",
    detected_cuda_devices: int | None = None,
) -> tuple[str, str]:
    """Resolve a safe faster-whisper device and compute type."""
    count = cuda_device_count() if detected_cuda_devices is None else detected_cuda_devices
    runtime_ready = count > 0 if detected_cuda_devices is not None else cuda_runtime_status()[0]

    if acceleration == "cpu":
        device = "cpu"
    elif acceleration == "cuda":
        if not runtime_ready:
            reason = cuda_runtime_status()[1] if detected_cuda_devices is None else "CUDA 不可用"
            raise RuntimeError(
                f"未检测到完整可用的 NVIDIA CUDA 环境：{reason}。请安装 NVIDIA 驱动、"
                "CUDA 12 和 cuDNN 9，或将硬件加速改为“自动/仅 CPU”。"
            )
        device = "cuda"
    elif configured_device != "auto":
        device = configured_device
        if device == "cuda" and not runtime_ready:
            reason = cuda_runtime_status()[1]
            raise RuntimeError(f"WHISPER_DEVICE=cuda，但 CUDA 环境不可用：{reason}。")
    else:
        device = "cuda" if runtime_ready else "cpu"

    if configured_compute_type != "auto":
        compute_type = configured_compute_type
    else:
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def _get_model(model_size: str, device: str, compute_type: str) -> Any:
    key = (model_size, device, compute_type)
    with _model_lock:
        if key not in _model_cache:
            # Drop unused cached models before allocating another large model.
            # Active transcriptions retain their own reference until they finish.
            _model_cache.clear()
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "缺少 faster-whisper，请先执行 pip install -r requirements.txt。"
                ) from exc
            try:
                _model_cache[key] = WhisperModel(
                    model_size, device=device, compute_type=compute_type, download_root=None
                )
            except Exception as exc:
                if is_model_download_error(exc):
                    raise RuntimeError(
                        f"{model_size} 模型尚未下载完整或连接已中断。请检查网络和磁盘空间，"
                        "然后重新提交任务；下载会复用已缓存的文件。"
                    ) from exc
                if device == "cuda" and is_cuda_runtime_error(exc):
                    raise RuntimeError(
                        "CUDA 语音识别初始化失败。请确认 NVIDIA 驱动、CUDA 12、cuBLAS 和 "
                        "cuDNN 9 已正确安装，或改用“自动/仅 CPU”。"
                    ) from exc
                raise
        return _model_cache[key]


def transcribe(
    audio_path: Path,
    model_size: str,
    device: str,
    compute_type: str,
    duration: float | None,
    on_progress: Callable[[int], None] | None = None,
    source_language: str = "auto",
) -> tuple[str, float | None, list[SubtitleSegment]]:
    check_cancelled()
    model = _get_model(model_size, device, compute_type)
    check_cancelled()
    raw_segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
        language=None if source_language == "auto" else source_language,
        language_detection_segments=3,
        language_detection_threshold=0.8,
    )
    segments: list[SubtitleSegment] = []
    last_progress = -1
    for item in raw_segments:
        check_cancelled()
        text = item.text.strip()
        if not text:
            continue
        if is_chinese_language(info.language):
            text = to_simplified(text)
        segments.append(SubtitleSegment(start=item.start, end=item.end, text=text))
        if on_progress and duration:
            progress = min(100, round(item.end / duration * 100))
            if progress > last_progress:
                on_progress(progress)
                last_progress = progress
    if not segments:
        raise RuntimeError("没有识别到清晰语音，请确认视频包含可听见的人声。")
    probability = float(info.language_probability) if source_language == "auto" else None
    return info.language, probability, segments
