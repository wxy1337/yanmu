from __future__ import annotations

import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .jobs import JobStore
from .media import MediaError, available_hardware_encoders, ensure_media_tools
from .models import Job
from .pipeline import Pipeline
from .transcriber import cuda_device_count, cuda_runtime_status

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg", ".ts"}
ALLOWED_MODELS = {"tiny", "base", "small", "medium", "large-v3", "distil-large-v3"}
ALLOWED_ACCELERATION = {"auto", "cpu", "cuda"}
ALLOWED_LANGUAGES = {
    "auto", "zh", "en", "ja", "ko", "fr", "de", "es", "ru", "pt", "it", "vi", "th", "id", "hi", "ar"
}
STATIC_DIR = Path(__file__).parent / "static"

settings = get_settings()
store = JobStore(settings.jobs_dir)
pipeline = Pipeline(settings, store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    pipeline.shutdown()


app = FastAPI(
    title="言幕 API",
    description="自动识别视频语种并生成简体中文或中外双语字幕",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    try:
        ensure_media_tools()
        ffmpeg_ready = True
        message = "服务就绪"
    except MediaError as exc:
        ffmpeg_ready = False
        message = str(exc)
    cuda_count = cuda_device_count()
    cuda_ready, cuda_message = cuda_runtime_status()
    return {
        "ok": True,
        "ffmpeg_ready": ffmpeg_ready,
        "message": message,
        "translation_configured": bool(settings.translation_api_key)
        or "localhost" in settings.translation_base_url,
        "default_model": settings.whisper_model,
        "acceleration": {
            "cuda_available": cuda_ready,
            "cuda_device_count": cuda_count,
            "cuda_message": cuda_message,
            "video_encoders": available_hardware_encoders() if ffmpeg_ready else [],
        },
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, object]]:
    return [job.to_dict(public=True) for job in store.list()[:50]]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict(public=True)


@app.post("/api/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    model_size: str = Form(default=settings.whisper_model),
    burn_subtitles: bool = Form(default=False),
    acceleration: str = Form(default=settings.acceleration_mode),
    source_language: str = Form(default="auto"),
) -> dict[str, object]:
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="不支持该视频格式，请上传 MP4、MOV、MKV、AVI、WebM 或 MPEG 文件。",
        )
    if model_size not in ALLOWED_MODELS:
        raise HTTPException(status_code=422, detail="不支持该识别模型")
    if acceleration not in ALLOWED_ACCELERATION:
        raise HTTPException(status_code=422, detail="不支持该硬件加速模式")
    if source_language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=422, detail="不支持该视频语言")

    job_id = uuid.uuid4().hex
    work_dir = settings.jobs_dir / job_id
    work_dir.mkdir(parents=True, exist_ok=False)
    source = work_dir / f"source{suffix}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with source.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"视频超过 {settings.max_upload_mb} MB 上传限制。",
                    )
                output.write(chunk)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    if size == 0:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传的视频文件为空")

    job = store.create(
        Job(
            id=job_id,
            filename=filename,
            source_path=str(source),
            model_size=model_size,
            burn_subtitles=burn_subtitles,
            acceleration=acceleration,
            source_language=source_language,
            progress=8,
            stage="已上传，等待处理",
        )
    )
    pipeline.submit(job.id)
    return job.to_dict(public=True)


@app.get("/api/jobs/{job_id}/files/{kind}")
def download_file(job_id: str, kind: str) -> FileResponse:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    paths = {
        "source": job.source_path,
        "subtitle": job.subtitle_path,
        "video": job.output_video_path,
    }
    path_value = paths.get(kind)
    if not path_value:
        raise HTTPException(status_code=404, detail="文件尚未生成")
    path = Path(path_value)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if kind == "subtitle":
        filename = "双语字幕.srt" if job.is_bilingual else "简体中文字幕.srt"
        return FileResponse(path, media_type="application/x-subrip", filename=filename)
    if kind == "video":
        return FileResponse(path, media_type="video/mp4", filename=path.name)
    return FileResponse(path, filename=job.filename)
