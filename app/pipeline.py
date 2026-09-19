from __future__ import annotations

import hashlib
import threading
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .checkpoints import load_checkpoint, save_checkpoint
from .config import Settings
from .control import JobCancelled, cancel_event, check_cancelled
from .jobs import JobStore
from .media import burn_subtitles, extract_audio, probe_duration
from .models import SubtitleSegment
from .subtitles import is_chinese_language, write_subtitles
from .transcriber import (
    configure_cuda_dll_directory,
    disable_cuda_for_process,
    is_cuda_runtime_error,
    resolve_whisper_runtime,
    transcribe,
)
from .translator import TranslationConfig, Translator

LANGUAGE_NAMES = {
    "zh": "中文",
    "yue": "粤语",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "ar": "阿拉伯语",
    "pt": "葡萄牙语",
    "it": "意大利语",
    "nl": "荷兰语",
    "tr": "土耳其语",
    "pl": "波兰语",
    "vi": "越南语",
    "th": "泰语",
    "id": "印度尼西亚语",
    "hi": "印地语",
    "uk": "乌克兰语",
    "sv": "瑞典语",
    "cs": "捷克语",
    "el": "希腊语",
    "he": "希伯来语",
    "fa": "波斯语",
}


class Pipeline:
    def __init__(self, settings: Settings, store: JobStore):
        self.settings = settings
        self.store = store
        self._lock = threading.RLock()
        self._active: dict[str, tuple[threading.Event, Future | None]] = {}
        configure_cuda_dll_directory(settings.cuda_dll_directory)
        self.executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_jobs, thread_name_prefix="yanmu-job"
        )

    def submit(self, job_id: str, *, render_only: bool = False) -> None:
        with self._lock:
            if job_id in self._active:
                raise ValueError("任务仍在处理中。")
            if len(self._active) >= self.settings.max_pending_jobs:
                raise ValueError("处理队列已满，请稍后重试。")
            job = self.store.get(job_id)
            allowed = {"completed"} if render_only else {"queued", "failed", "cancelled"}
            if job is None or job.status not in allowed:
                raise ValueError("此任务不能重试。")
            if render_only:
                if not (self.settings.jobs_dir / job_id / "segments.json").is_file():
                    raise ValueError("旧任务没有保存识别结果，请重新上传。")
                self.store.update(job_id, burn_subtitles=True, output_video_path=None)
            event = threading.Event()
            self._active[job_id] = (event, None)
            try:
                self.store.update(job_id, status="queued", stage="等待处理", error=None)
                future = self.executor.submit(self._run_job, job_id, event)
                self._active[job_id] = (event, future)
            except Exception:
                self._active.pop(job_id, None)
                self.store.update(job_id, status="failed", stage="提交失败", error="请稍后重试。")
                raise

    def _run_job(self, job_id: str, event: threading.Event) -> None:
        token = cancel_event.set(event)
        try:
            self.process(job_id)
        finally:
            cancel_event.reset(token)
            with self._lock:
                self._active.pop(job_id, None)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            active = self._active.get(job_id)
            job = self.store.get(job_id)
            if not active or not job or job.status not in {"queued", "processing", "cancelling"}:
                raise ValueError("任务已经停止。")
            event, future = active
            event.set()
            if future is not None and future.cancel():
                self.store.update(job_id, status="cancelled", stage="已取消")
                self._active.pop(job_id, None)
            else:
                self.store.update(job_id, status="cancelling", stage="正在停止，请稍候")

    def delete(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._active:
                raise ValueError("任务尚未停止，请稍后删除。")
            self.store.delete(job_id)

    def read_segments(self, job_id: str) -> dict:
        with self._lock:
            job = self.store.get(job_id)
            if job is None or job.status != "completed" or job_id in self._active:
                raise ValueError("请等待任务完成后编辑字幕。")
            path = self.settings.jobs_dir / job_id / "segments.json"
            if not path.is_file():
                raise ValueError("旧任务没有保存可编辑字幕，请重新上传生成。")
            _, _, segments, _ = load_checkpoint(path)
            return {
                "revision": hashlib.sha256(path.read_bytes()).hexdigest(),
                "segments": [asdict(segment) for segment in segments],
                "bilingual": job.is_bilingual,
            }

    def edit_segments(self, job_id: str, revision: str, segments: list[SubtitleSegment]) -> dict:
        with self._lock:
            current = self.read_segments(job_id)
            if current["revision"] != revision:
                raise ValueError("字幕已被其他页面修改，请重新打开编辑器。")
            job = self.store.get(job_id)
            if current["bilingual"] and any(not item.translation for item in segments):
                raise ValueError("双语字幕的译文不能为空。")
            directory = self.settings.jobs_dir / job_id
            path = directory / "segments.json"
            language, probability, _, hardware = load_checkpoint(path)
            save_checkpoint(path, language, probability, segments, hardware)
            # A previously burned video no longer matches the new text/timing.
            self.store.update(
                job_id,
                output_video_path=None,
                subtitle_path=None,
                ass_path=None,
                status="failed",
                stage="字幕导出中，失败时可重试",
            )
            srt, ass = write_subtitles(segments, directory, bool(job.is_bilingual))
            self.store.update(
                job_id,
                subtitle_path=str(srt),
                ass_path=str(ass),
                status="completed",
                stage="字幕已更新，可重新压制视频",
                error=None,
            )
            return self.read_segments(job_id)

    def process(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if not job:
            return
        work_dir = self.settings.jobs_dir / job.id
        source = Path(job.source_path)
        audio = work_dir / "audio.wav"
        try:
            check_cancelled()
            checkpoint = work_dir / "segments.json"
            if checkpoint.is_file():
                language, probability, segments, asr_hardware = load_checkpoint(checkpoint)
                self.store.update(
                    job_id, status="processing", stage="恢复已保存的字幕", progress=68
                )
            else:
                self.store.update(job_id, status="processing", stage="分析视频", progress=12)
                duration = probe_duration(source)

                self.store.update(job_id, stage="提取清晰音轨", progress=20)
                extract_audio(source, audio)

                device, compute_type = resolve_whisper_runtime(
                    job.acceleration,
                    self.settings.whisper_device,
                    self.settings.whisper_compute_type,
                )
                asr_hardware = (
                    f"NVIDIA CUDA · {compute_type}" if device == "cuda" else f"CPU · {compute_type}"
                )
                self.store.update(
                    job_id,
                    stage=f"识别人声与语种（{asr_hardware}）",
                    hardware_used=asr_hardware,
                    progress=32,
                )

                def run_transcription(active_device: str, active_compute_type: str):
                    active_hardware = (
                        f"NVIDIA CUDA · {active_compute_type}"
                        if active_device == "cuda"
                        else f"CPU · {active_compute_type}"
                    )
                    return transcribe(
                        audio,
                        job.model_size,
                        active_device,
                        active_compute_type,
                        duration,
                        on_progress=lambda value: self.store.update(
                            job_id,
                            stage=f"识别人声与语种（{active_hardware}）",
                            progress=min(64, 32 + round(value * 0.32)),
                        ),
                        source_language=job.source_language,
                    )

                try:
                    language, probability, segments = run_transcription(device, compute_type)
                except RuntimeError as exc:
                    if (
                        device != "cuda"
                        or job.acceleration != "auto"
                        or not is_cuda_runtime_error(exc)
                    ):
                        raise
                    disable_cuda_for_process(str(exc))
                    device, compute_type = "cpu", "int8"
                    asr_hardware = "CPU · int8（CUDA 不可用，已自动回退）"
                    self.store.update(
                        job_id,
                        stage=f"识别人声与语种（{asr_hardware}）",
                        hardware_used=asr_hardware,
                        progress=32,
                    )
                    language, probability, segments = run_transcription(device, compute_type)
                save_checkpoint(checkpoint, language, probability, segments, asr_hardware)
            check_cancelled()
            bilingual = not is_chinese_language(language)
            self.store.update(
                job_id,
                language=language,
                language_name=LANGUAGE_NAMES.get(language, language.upper()),
                language_probability=round(probability, 4) if probability is not None else None,
                is_bilingual=bilingual,
                stage="翻译简体中文字幕" if bilingual else "整理简体中文字幕",
                progress=68,
            )

            if bilingual:
                translator = Translator(
                    TranslationConfig(
                        provider=self.settings.translation_provider,
                        base_url=self.settings.translation_base_url,
                        api_key=self.settings.translation_api_key,
                        model=self.settings.translation_model,
                        timeout=self.settings.translation_timeout_seconds,
                        retries=self.settings.translation_retries,
                    )
                )

                def save_translation(done: int, total: int) -> None:
                    save_checkpoint(checkpoint, language, probability, segments, asr_hardware)
                    check_cancelled()
                    self.store.update(
                        job_id,
                        stage=f"翻译字幕 {done}/{total}",
                        progress=68 + round(14 * done / max(1, total)),
                    )

                translator.translate(segments, language, on_progress=save_translation)

            check_cancelled()
            self.store.update(job_id, stage="生成字幕文件", progress=83)
            srt_path, ass_path = write_subtitles(segments, work_dir, bilingual)
            self.store.update(
                job_id,
                subtitle_path=str(srt_path),
                ass_path=str(ass_path),
                progress=89,
            )

            output_video = None
            if job.burn_subtitles:
                self.store.update(job_id, stage="压制字幕到视频", progress=91)
                safe_stem = (
                    "".join(
                        char for char in Path(job.filename).stem if char not in '<>:"/\\|?*'
                    ).strip()
                    or "video"
                )
                output_video = work_dir / f"带字幕_{safe_stem}.mp4"
                encoder_used = burn_subtitles(
                    source,
                    ass_path,
                    output_video,
                    acceleration=job.acceleration,
                    preferred_encoder=self.settings.gpu_video_encoder,
                )
                self.store.update(
                    job_id,
                    hardware_used=f"语音识别：{asr_hardware}；视频编码：{encoder_used}",
                )

            with self._lock:
                check_cancelled()
                self.store.update(
                    job_id,
                    status="completed",
                    stage="处理完成",
                    progress=100,
                    output_video_path=str(output_video) if output_video else None,
                )
        except JobCancelled:
            self.store.update(
                job_id, status="cancelled", stage="已取消，可重试继续处理", error=None
            )
        except Exception as exc:
            event = cancel_event.get()
            if event is not None and event.is_set():
                self.store.update(job_id, status="cancelled", stage="已取消", error=None)
                return
            try:
                (work_dir / "processing.log").write_text(traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass  # A full disk must not prevent updating the in-memory failure state.
            self.store.update(
                job_id,
                status="failed",
                stage="处理失败",
                error=str(exc),
            )
        finally:
            audio.unlink(missing_ok=True)

    def shutdown(self) -> None:
        with self._lock:
            for job_id in list(self._active):
                try:
                    self.cancel(job_id)
                except ValueError:
                    pass
        self.executor.shutdown(wait=True, cancel_futures=True)
