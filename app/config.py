from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    data_dir: Path = Path("./data")
    max_upload_mb: int = Field(default=4096, ge=1)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=8)
    max_pending_jobs: int = Field(default=20, ge=1)
    min_free_disk_mb: int = Field(default=1024, ge=0)
    media_timeout_seconds: float = Field(default=14400, gt=0)
    ffmpeg_binary: str = ""
    ffprobe_binary: str = ""

    whisper_model: Literal["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"] = (
        "small"
    )
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    acceleration_mode: Literal["auto", "cpu", "cuda"] = "auto"
    gpu_video_encoder: str = "auto"
    cuda_dll_directory: str = ""

    translation_provider: Literal["openai_compatible", "libretranslate"] = "openai_compatible"
    translation_base_url: str = "https://api.openai.com/v1"
    translation_api_key: str = ""
    translation_model: str = "gpt-4.1-mini"
    translation_timeout_seconds: float = Field(default=90, gt=0)
    translation_retries: int = Field(default=2, ge=0, le=5)

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir.resolve() / "jobs"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    return settings
