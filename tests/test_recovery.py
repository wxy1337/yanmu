import json
import threading
from concurrent.futures import Future
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.checkpoints import load_checkpoint, save_checkpoint
from app.config import Settings
from app.control import JobCancelled, cancel_event
from app.jobs import JobStore
from app.models import Job, SubtitleSegment
from app.pipeline import Pipeline
from app.subtitles import render_vtt
from app.translator import TranslationConfig, TranslationError, Translator


@pytest.fixture
def environment(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path, min_free_disk_mb=0)
    store = JobStore(settings.jobs_dir)
    pipeline = Pipeline(settings, store)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "pipeline", pipeline)
    yield settings, store, pipeline, TestClient(main.app)
    pipeline.shutdown()


def make_job(settings, store, status="failed"):
    job = store.create(Job("test-job", "sample.mp4", "", "small", False, status=status))
    source = settings.jobs_dir / job.id / "source.mp4"
    source.write_bytes(b"video")
    store.update(job.id, source_path=str(source))
    return job


def test_retry_reuses_transcription(environment):
    settings, store, pipeline, _ = environment
    job = make_job(settings, store)
    checkpoint = settings.jobs_dir / job.id / "segments.json"
    save_checkpoint(checkpoint, "en", 0.9, [SubtitleSegment(0, 12, "Hello", "你好")], "CPU")
    with (
        patch("app.pipeline.transcribe") as recognize,
        patch("app.pipeline.extract_audio") as extract,
    ):
        pipeline.process(job.id)
    assert job.status == "completed"
    recognize.assert_not_called()
    extract.assert_not_called()
    assert (checkpoint.parent / "preview.vtt").is_file()


def test_restart_marks_interrupted_job_retriable_and_persists(environment):
    settings, store, _, _ = environment
    job = make_job(settings, store, "processing")
    restored = JobStore(settings.jobs_dir)
    assert restored.get(job.id).status == "failed"
    assert (
        json.loads((settings.jobs_dir / job.id / "job.json").read_text("utf-8"))["status"]
        == "failed"
    )


def test_cancellation_keeps_checkpoint(environment):
    settings, store, pipeline, _ = environment
    job = make_job(settings, store)
    checkpoint = settings.jobs_dir / job.id / "segments.json"
    save_checkpoint(checkpoint, "en", 1, [SubtitleSegment(0, 1, "Hello")], "CPU")
    event = threading.Event()
    event.set()
    token = cancel_event.set(event)
    try:
        pipeline.process(job.id)
    finally:
        cancel_event.reset(token)
    assert job.status == "cancelled"
    assert checkpoint.is_file()


def test_cancel_queued_and_reject_duplicate_submission(environment):
    settings, store, pipeline, client = environment
    job = make_job(settings, store)
    future = Future()
    with patch.object(pipeline.executor, "submit", return_value=future):
        assert client.post(f"/api/jobs/{job.id}/retry").status_code == 202
        assert client.post(f"/api/jobs/{job.id}/retry").status_code == 409
        assert client.delete(f"/api/jobs/{job.id}").status_code == 409
        assert client.post(f"/api/jobs/{job.id}/cancel").status_code == 202
    assert future.cancelled()
    assert job.status == "cancelled"
    assert client.delete(f"/api/jobs/{job.id}").status_code == 204
    assert not (settings.jobs_dir / job.id).exists()


def test_queue_limit_is_enforced(environment):
    settings, store, pipeline, _ = environment
    settings.max_pending_jobs = 1
    job = make_job(settings, store)
    future = Future()
    with patch.object(pipeline.executor, "submit", return_value=future):
        pipeline.submit(job.id)
        with pytest.raises(ValueError, match="队列"):
            pipeline.submit("another")
        pipeline.cancel(job.id)


def test_model_language_and_upload_limits(environment):
    settings, _, _, client = environment
    response = client.post(
        "/api/jobs",
        files={"file": ("a.mp4", b"x")},
        data={"model_size": "distil-large-v3", "source_language": "ja"},
    )
    assert response.status_code == 422
    settings.max_upload_mb = 1
    response = client.post("/api/jobs", headers={"Content-Length": str(3 * 1024 * 1024)})
    assert response.status_code == 413
    response = client.post("/api/jobs", headers={"Origin": "https://unrelated.example"})
    assert response.status_code == 403


def test_low_disk_rejects_upload(environment):
    _, _, _, client = environment
    with patch("app.main.shutil.disk_usage") as usage:
        usage.return_value.free = 0
        response = client.post("/api/jobs", files={"file": ("a.mp4", b"data")})
    assert response.status_code == 507


def test_subtitle_files_available_after_render(environment):
    settings, store, pipeline, client = environment
    job = make_job(settings, store)
    save_checkpoint(
        settings.jobs_dir / job.id / "segments.json",
        "zh",
        1,
        [SubtitleSegment(0, 12, "你好")],
        "CPU",
    )
    pipeline.process(job.id)
    assert client.get(f"/api/jobs/{job.id}/files/preview").text.startswith("WEBVTT")
    assert client.get(f"/api/jobs/{job.id}/files/ass").status_code == 200


def test_vtt_escapes_markup_and_keeps_long_speech():
    result = render_vtt([SubtitleSegment(0, 12, "<b>Hello</b>", "你好")], True)
    assert "00:00:12.000" in result
    assert "&lt;b&gt;Hello&lt;/b&gt;" in result
    assert "你好" in result


def translator():
    return Translator(TranslationConfig("openai_compatible", "http://localhost/v1", "", "test", 1))


def response(items):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(items)}}]})


def test_translation_retries_429_and_saves_progress():
    segments = [SubtitleSegment(0, 1, "Hello world")]
    saved = []
    with (
        patch(
            "httpx.Client.post",
            side_effect=[httpx.Response(429), response([{"id": 0, "translation": "你好世界"}])],
        ) as post,
        patch("app.translator.interruptible_wait"),
    ):
        translator().translate(segments, "en", lambda done, total: saved.append((done, total)))
    assert post.call_count == 2
    assert saved == [(1, 1)]


def test_bad_credentials_are_not_retried():
    with patch("httpx.Client.post", return_value=httpx.Response(401)) as post:
        with pytest.raises(TranslationError, match="401"):
            translator().translate([SubtitleSegment(0, 1, "Hello")], "en")
    assert post.call_count == 1


def test_malformed_translation_retries_without_partial_commit():
    segments = [SubtitleSegment(0, 1, "Hello"), SubtitleSegment(1, 2, "World")]
    with (
        patch(
            "httpx.Client.post",
            return_value=response(
                [{"id": 0, "translation": "你好"}, {"id": 0, "translation": "世界"}]
            ),
        ),
        patch("app.translator.interruptible_wait"),
    ):
        with pytest.raises(TranslationError):
            translator().translate(segments, "en")
    assert all(item.translation is None for item in segments)


def test_completed_translation_is_not_requested_again(tmp_path):
    checkpoint = tmp_path / "segments.json"
    segments = [SubtitleSegment(0, 1, "Hello", "你好"), SubtitleSegment(1, 2, "World")]
    save_checkpoint(checkpoint, "en", 1, segments, "CPU")
    _, _, restored, _ = load_checkpoint(checkpoint)
    with patch(
        "httpx.Client.post", return_value=response([{"id": 1, "translation": "世界"}])
    ) as post:
        translator().translate(restored, "en")
    payload = post.call_args.kwargs["json"]["messages"][-1]["content"]
    assert '"id": 0' not in payload
    assert restored[0].translation == "你好"


def test_cancelled_translation_makes_no_request():
    event = threading.Event()
    event.set()
    token = cancel_event.set(event)
    try:
        with patch("httpx.Client.post") as post, pytest.raises(JobCancelled):
            translator().translate([SubtitleSegment(0, 1, "Hello")], "en")
        post.assert_not_called()
    finally:
        cancel_event.reset(token)


def test_running_task_can_be_cancelled_before_cleanup(environment):
    settings, store, pipeline, client = environment
    job = make_job(settings, store)
    entered = threading.Event()
    stopped = threading.Event()

    def extract(*args):
        from app.control import check_cancelled

        entered.set()
        event = cancel_event.get()
        assert event.wait(3), "Cancellation did not arrive"
        stopped.set()
        check_cancelled()

    with (
        patch("app.pipeline.probe_duration", return_value=1),
        patch("app.pipeline.extract_audio", side_effect=extract),
    ):
        pipeline.submit(job.id)
        assert entered.wait(3)
        assert client.post(f"/api/jobs/{job.id}/cancel").status_code == 202
        assert stopped.wait(3)
        pipeline.shutdown()
    assert job.status == "cancelled"
    assert job.id not in pipeline._active
    assert client.delete(f"/api/jobs/{job.id}").status_code == 204


def test_cancelling_status_is_not_overwritten(environment):
    settings, store, _, _ = environment
    job = make_job(settings, store, "cancelling")
    store.update(job.id, status="processing", stage="progress", progress=50)
    assert job.status == "cancelling"
    with pytest.raises(ValueError):
        store.delete(job.id)


def test_partial_translation_survives_later_batch_failure(environment):
    settings, store, pipeline, _ = environment
    settings.translation_base_url = "http://localhost/v1"
    settings.translation_retries = 0
    job = make_job(settings, store)
    checkpoint = settings.jobs_dir / job.id / "segments.json"
    segments = [SubtitleSegment(0, 1, "a" * 4500), SubtitleSegment(1, 2, "Hello")]
    save_checkpoint(checkpoint, "en", 1, segments, "CPU")
    with patch(
        "httpx.Client.post",
        side_effect=[response([{"id": 0, "translation": "第一段"}]), httpx.Response(503)],
    ):
        pipeline.process(job.id)
    assert job.status == "failed"
    _, _, saved, _ = load_checkpoint(checkpoint)
    assert saved[0].translation == "第一段"
    assert saved[1].translation is None
    with patch(
        "httpx.Client.post", return_value=response([{"id": 1, "translation": "你好"}])
    ) as post:
        pipeline.process(job.id)
    assert job.status == "completed"
    assert post.call_count == 1


def test_chunked_upload_guard_rejects_without_content_length(environment):
    import asyncio

    from starlette.formparsers import MultiPartException

    from app.limits import UploadGuard

    settings, _, _, _ = environment
    settings.max_upload_mb = 1
    messages = []

    async def downstream(scope, receive, send):
        try:
            await receive()
            await receive()
        except MultiPartException:
            await send({"type": "http.response.start", "status": 400, "headers": []})
            await send({"type": "http.response.body", "body": b"limited"})

    async def receive():
        return {"type": "http.request", "body": b"x" * (1024 * 1024 + 1), "more_body": True}

    async def send(message):
        messages.append(message)

    asyncio.run(
        UploadGuard(downstream, lambda: settings)(
            {"type": "http", "path": "/api/jobs", "method": "POST", "headers": []}, receive, send
        )
    )
    assert messages[0]["status"] == 413


def test_media_timeout_terminates_process(environment):
    import sys

    from app.media import MediaError, _run

    settings, _, _, _ = environment
    settings.media_timeout_seconds = 0.1
    with patch("app.config.get_settings", return_value=settings):
        with pytest.raises(MediaError, match="超时"):
            _run([sys.executable, "-c", "import time; time.sleep(20)"])


def test_edit_subtitles_updates_exports_invalidates_video_and_checks_revision(environment):
    settings, store, pipeline, client = environment
    job = make_job(settings, store)
    save_checkpoint(
        settings.jobs_dir / job.id / "segments.json",
        "en",
        1,
        [SubtitleSegment(0, 12, "Hello", "你好")],
        "CPU",
    )
    pipeline.process(job.id)
    store.update(job.id, output_video_path="old-video.mp4")
    data = client.get(f"/api/jobs/{job.id}/segments").json()
    payload = {
        "revision": data["revision"],
        "segments": [{"start": 1, "end": 10, "text": "Hello again", "translation": "再次你好"}],
    }
    saved = client.put(f"/api/jobs/{job.id}/segments", json=payload)
    assert saved.status_code == 200
    assert job.output_video_path is None
    assert "再次你好" in client.get(f"/api/jobs/{job.id}/files/preview").text
    assert client.put(f"/api/jobs/{job.id}/segments", json=payload).status_code == 409
    assert client.get(f"/api/jobs/{job.id}/files/video").status_code == 404


def test_invalid_edit_does_not_change_saved_subtitles(environment):
    settings, store, pipeline, client = environment
    job = make_job(settings, store)
    checkpoint = settings.jobs_dir / job.id / "segments.json"
    save_checkpoint(checkpoint, "zh", 1, [SubtitleSegment(0, 1, "你好")], "CPU")
    pipeline.process(job.id)
    data = client.get(f"/api/jobs/{job.id}/segments").json()
    data["segments"][0]["end"] = -1
    before = checkpoint.read_bytes()
    assert client.put(f"/api/jobs/{job.id}/segments", json=data).status_code == 422
    assert checkpoint.read_bytes() == before


def test_rerender_uses_edited_subtitles_without_recognition(environment):
    settings, store, pipeline, _ = environment
    job = make_job(settings, store, "completed")
    save_checkpoint(
        settings.jobs_dir / job.id / "segments.json",
        "en",
        1,
        [SubtitleSegment(0, 12, "Hello", "你好")],
        "CPU",
    )
    with (
        patch("app.pipeline.transcribe") as transcribe,
        patch("app.pipeline.burn_subtitles", return_value="CPU") as burn,
    ):
        pipeline.submit(job.id, render_only=True)
        with pipeline._lock:
            active = pipeline._active.get(job.id)
        if active:
            active[1].result(timeout=3)
    assert job.status == "completed"
    transcribe.assert_not_called()
    burn.assert_called_once()


def test_model_cache_evicts_unused_models():
    import sys
    from types import SimpleNamespace

    from app.transcriber import _get_model, _model_cache

    _model_cache.clear()
    try:
        with patch.dict(
            sys.modules,
            {"faster_whisper": SimpleNamespace(WhisperModel=lambda *args, **kwargs: object())},
        ):
            _get_model("tiny", "cpu", "int8")
            _get_model("small", "cpu", "int8")
        assert len(_model_cache) == 1
        assert ("small", "cpu", "int8") in _model_cache
    finally:
        _model_cache.clear()
