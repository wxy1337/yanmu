"""Run a real two-video smoke test with a local deterministic translation stub.

This script is intentionally not part of unittest discovery because it downloads a
Whisper model and requires FFmpeg. It validates media extraction, CUDA recognition,
language routing, translation transport, SRT/ASS generation, and hard-subtitle encoding.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TranslationStub(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        content = request["messages"][-1]["content"]
        items = json.loads(content.split("字幕：", 1)[1])
        translations = []
        for item in items:
            source = item["text"].lower()
            if "welcome" in source:
                translation = "欢迎使用言幕工作室。"
            elif "short video" in source:
                translation = "这个短视频用于测试自动字幕和 GPU 加速。"
            else:
                translation = "这是一条简体中文测试译文。"
            translations.append({"id": item["id"], "translation": translation})
        response = {
            "choices": [{"message": {"content": json.dumps(translations, ensure_ascii=False)}}]
        }
        payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run() -> None:
    ffmpeg = os.environ.get("FFMPEG_BINARY")
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise SystemExit("Set FFMPEG_BINARY to a working FFmpeg executable.")

    data_dir = ROOT / ".test-artifacts" / "smoke-data"
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["TRANSLATION_PROVIDER"] = "openai_compatible"
    os.environ["TRANSLATION_BASE_URL"] = "http://127.0.0.1:18181/v1"
    os.environ["TRANSLATION_API_KEY"] = "smoke-test"
    os.environ["TRANSLATION_MODEL"] = "translation-stub"

    from app.config import get_settings
    from app.jobs import JobStore
    from app.models import Job
    from app.pipeline import Pipeline
    from app.text import contains_han

    get_settings.cache_clear()
    settings = get_settings()
    acceleration = os.environ.get("SMOKE_ACCELERATION", "cuda")
    store = JobStore(settings.jobs_dir)
    pipeline = Pipeline(settings, store)
    server = ThreadingHTTPServer(("127.0.0.1", 18181), TranslationStub)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    cases = [
        ("english-smoke", ROOT / ".test-artifacts" / "english_test.mp4", True, False),
        ("chinese-smoke", ROOT / ".test-artifacts" / "chinese_test.mp4", False, True),
    ]
    results: list[dict[str, object]] = []
    try:
        for job_id, source, burn, expected_chinese in cases:
            job_dir = settings.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            target = job_dir / "source.mp4"
            shutil.copy2(source, target)
            job = store.create(
                Job(
                    id=job_id,
                    filename=source.name,
                    source_path=str(target),
                    model_size="tiny",
                    burn_subtitles=burn,
                    acceleration=acceleration,
                )
            )
            pipeline.process(job.id)
            completed = store.get(job.id)
            assert completed is not None
            if completed.status != "completed":
                raise AssertionError(f"{job.id} failed: {completed.error}")
            if expected_chinese and completed.is_bilingual:
                raise AssertionError("Chinese video was incorrectly routed to bilingual subtitles.")
            if not expected_chinese and not completed.is_bilingual:
                raise AssertionError("English video was not routed to bilingual subtitles.")
            subtitle = Path(completed.subtitle_path or "")
            if not subtitle.is_file() or subtitle.stat().st_size == 0:
                raise AssertionError("Subtitle output is missing.")
            subtitle_text = subtitle.read_text(encoding="utf-8-sig")
            first_block_lines = subtitle_text.split("\n\n", 1)[0].splitlines()[2:]
            if expected_chinese:
                if len(first_block_lines) != 1 or not contains_han(first_block_lines[0]):
                    raise AssertionError(
                        "Chinese video did not produce one Simplified Chinese line."
                    )
            else:
                if len(first_block_lines) < 2:
                    raise AssertionError("Bilingual subtitle does not contain two text lines.")
                if contains_han(first_block_lines[0]) or not contains_han(first_block_lines[1]):
                    raise AssertionError(
                        "Bilingual order/content is wrong: foreign source must be above Chinese."
                    )
            if burn and not Path(completed.output_video_path or "").is_file():
                raise AssertionError("Burned video output is missing.")
            results.append(
                {
                    "job": completed.id,
                    "status": completed.status,
                    "language": completed.language,
                    "bilingual": completed.is_bilingual,
                    "hardware": completed.hardware_used,
                    "subtitle": str(subtitle),
                    "video": completed.output_video_path,
                }
            )
    finally:
        pipeline.shutdown()
        server.shutdown()
        server.server_close()

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
