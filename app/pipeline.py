from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Settings
from .jobs import JobStore
from .media import burn_subtitles, extract_audio, probe_duration
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
        configure_cuda_dll_directory(settings.cuda_dll_directory)
        self.executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_jobs, thread_name_prefix="yanmu-job"
        )

    def submit(self, job_id: str) -> None:
        self.executor.submit(self.process, job_id)

    def process(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if not job:
            return
        work_dir = self.settings.jobs_dir / job.id
        source = Path(job.source_path)
        audio = work_dir / "audio.wav"
        try:
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
                )

            try:
                language, probability, segments = run_transcription(device, compute_type)
            except RuntimeError as exc:
                if device != "cuda" or job.acceleration != "auto" or not is_cuda_runtime_error(exc):
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
            bilingual = not is_chinese_language(language)
            self.store.update(
                job_id,
                language=language,
                language_name=LANGUAGE_NAMES.get(language, language.upper()),
                language_probability=round(probability, 4),
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
                    )
                )
                translator.translate(segments, language)

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
                safe_stem = "".join(
                    char for char in Path(job.filename).stem if char not in '<>:"/\\|?*'
                ).strip() or "video"
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

            self.store.update(
                job_id,
                status="completed",
                stage="处理完成",
                progress=100,
                output_video_path=str(output_video) if output_video else None,
            )
        except Exception as exc:
            (work_dir / "processing.log").write_text(traceback.format_exc(), encoding="utf-8")
            self.store.update(
                job_id,
                status="failed",
                stage="处理失败",
                error=str(exc),
            )
        finally:
            audio.unlink(missing_ok=True)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)
