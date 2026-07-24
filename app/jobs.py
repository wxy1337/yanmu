from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .models import Job, utc_now


class JobStore:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        for metadata in self.jobs_dir.glob("*/job.json"):
            try:
                data = json.loads(metadata.read_text(encoding="utf-8"))
                job = Job.from_dict(data)
                if job.status in {"queued", "processing"}:
                    job.status = "failed"
                    job.stage = "服务重启，任务已中断"
                    job.error = "任务处理过程中服务被重启，请重新上传视频。"
                self._jobs[job.id] = job
            except (OSError, ValueError, TypeError):
                continue

    def create(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def update(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = utc_now()
            self._persist(job)
            return job

    def _persist(self, job: Job) -> None:
        metadata = self.jobs_dir / job.id / "job.json"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        temporary = metadata.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(metadata)

