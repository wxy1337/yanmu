import unittest

from app.models import Job


class JobCompatibilityTests(unittest.TestCase):
    def test_existing_job_without_language_override_remains_automatic(self) -> None:
        job = Job.from_dict(
            {
                "id": "old-job",
                "filename": "sample.mp4",
                "source_path": "source.mp4",
                "model_size": "small",
                "burn_subtitles": False,
            }
        )
        self.assertEqual(job.source_language, "auto")


if __name__ == "__main__":
    unittest.main()
