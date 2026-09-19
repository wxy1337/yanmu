from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

JobStatus = Literal["queued", "processing", "cancelling", "cancelled", "completed", "failed"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SubtitleSegment:
    start: float
    end: float
    text: str
    translation: str | None = None


@dataclass(slots=True)
class Job:
    id: str
    filename: str
    source_path: str
    model_size: str
    burn_subtitles: bool
    acceleration: str = "auto"
    source_language: str = "auto"
    status: JobStatus = "queued"
    stage: str = "等待处理"
    progress: int = 0
    language: str | None = None
    language_name: str | None = None
    language_probability: float | None = None
    is_bilingual: bool | None = None
    hardware_used: str | None = None
    error: str | None = None
    subtitle_path: str | None = None
    ass_path: str | None = None
    output_video_path: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self, *, public: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if public:
            data.pop("source_path", None)
            data.pop("subtitle_path", None)
            data.pop("ass_path", None)
            data.pop("output_video_path", None)
            data["downloads"] = {
                "subtitle": f"/api/jobs/{self.id}/files/subtitle" if self.subtitle_path else None,
                "video": f"/api/jobs/{self.id}/files/video" if self.output_video_path else None,
                "source": f"/api/jobs/{self.id}/files/source",
                "ass": f"/api/jobs/{self.id}/files/ass" if self.ass_path else None,
                "preview": (
                    f"/api/jobs/{self.id}/files/preview"
                    if self.subtitle_path
                    and (Path(self.subtitle_path).parent / "preview.vtt").is_file()
                    else None
                ),
            }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        allowed = {item.name for item in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in allowed})
