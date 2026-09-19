from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import SubtitleSegment


def save_checkpoint(
    path: Path,
    language: str,
    probability: float | None,
    segments: list[SubtitleSegment],
    hardware: str,
) -> None:
    payload = {
        "version": 1,
        "language": language,
        "probability": probability,
        "hardware": hardware,
        "segments": [asdict(segment) for segment in segments],
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_checkpoint(path: Path) -> tuple[str, float | None, list[SubtitleSegment], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("任务缓存版本不兼容。")
    return (
        payload["language"],
        payload["probability"],
        [SubtitleSegment(**item) for item in payload["segments"]],
        payload["hardware"],
    )
