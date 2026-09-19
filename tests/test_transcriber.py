import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.transcriber import _get_model, _model_cache, is_model_download_error, transcribe


class TranscriptionLanguageTests(unittest.TestCase):
    def test_auto_detection_uses_more_audio(self) -> None:
        recorded = {}

        class FakeModel:
            def transcribe(self, audio_path, **options):
                recorded.update(options)
                return [SimpleNamespace(start=0.0, end=1.0, text="Hello")], SimpleNamespace(
                    language="en", language_probability=0.73
                )

        with patch("app.transcriber._get_model", return_value=FakeModel()):
            language, probability, segments = transcribe(
                Path("example.wav"), "small", "cpu", "int8", 10.0
            )

        self.assertEqual(language, "en")
        self.assertEqual(probability, 0.73)
        self.assertEqual(segments[0].text, "Hello")
        self.assertIsNone(recorded["language"])
        self.assertEqual(recorded["language_detection_segments"], 3)
        self.assertEqual(recorded["language_detection_threshold"], 0.8)

    def test_manual_language_skips_detection_probability(self) -> None:
        recorded = {}

        class FakeModel:
            def transcribe(self, audio_path, **options):
                recorded.update(options)
                return [SimpleNamespace(start=0.0, end=1.0, text="Hello")], SimpleNamespace(
                    language="en", language_probability=1.0
                )

        with patch("app.transcriber._get_model", return_value=FakeModel()):
            language, probability, _ = transcribe(
                Path("example.wav"), "medium", "cpu", "int8", None, source_language="en"
            )

        self.assertEqual(language, "en")
        self.assertIsNone(probability)
        self.assertEqual(recorded["language"], "en")


class ModelDownloadTests(unittest.TestCase):
    def tearDown(self) -> None:
        _model_cache.clear()

    def test_incomplete_download_is_not_reported_as_cuda_failure(self) -> None:
        def raise_incomplete(*args, **kwargs):
            raise RuntimeError(
                "cached snapshot incomplete: model.bin missing; SSL connection failed"
            )

        fake_module = SimpleNamespace(WhisperModel=raise_incomplete)
        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            with self.assertRaisesRegex(RuntimeError, "模型尚未下载完整"):
                _get_model("medium", "cuda", "float16")

    def test_nested_download_failure_is_recognized(self) -> None:
        root = ConnectionError("SSL connection aborted")
        error = RuntimeError("model load failed")
        error.__cause__ = root
        self.assertTrue(is_model_download_error(error))


if __name__ == "__main__":
    unittest.main()
