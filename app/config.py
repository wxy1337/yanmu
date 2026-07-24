from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    data_dir: Path = Path("./data")
    max_upload_mb: int = 4096
    max_concurrent_jobs: int = 1
    ffmpeg_binary: str = ""
    ffprobe_binary: str = ""

    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    acceleration_mode: Literal["auto", "cpu", "cuda"] = "auto"
    gpu_video_encoder: str = "auto"
    cuda_dll_directory: str = ""

    translation_provider: Literal["openai_compatible", "libretranslate"] = "openai_compatible"
    translation_base_url: str = "https://api.openai.com/v1"
    translation_api_key: str = ""
    translation_model: str = "gpt-4.1-mini"
    translation_timeout_seconds: float = 90

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir.resolve() / "jobs"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    return settings
