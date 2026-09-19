import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as app_module
from app.config import Settings
from app.jobs import JobStore


class JobLanguageApiTests(unittest.TestCase):
    def test_uploaded_job_keeps_manual_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(_env_file=None, data_dir=Path(directory))
            store = JobStore(settings.jobs_dir)
            with (
                patch.object(app_module, "settings", settings),
                patch.object(app_module, "store", store),
                patch.object(app_module.pipeline, "submit"),
            ):
                response = TestClient(app_module.app).post(
                    "/api/jobs",
                    files={"file": ("sample.mp4", b"video-data", "video/mp4")},
                    data={"model_size": "medium", "source_language": "ja"},
                )

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["source_language"], "ja")
            self.assertEqual(store.get(response.json()["id"]).source_language, "ja")

    def test_unsupported_language_is_rejected(self) -> None:
        response = TestClient(app_module.app).post(
            "/api/jobs",
            files={"file": ("sample.mp4", b"video-data", "video/mp4")},
            data={"source_language": "unknown"},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
