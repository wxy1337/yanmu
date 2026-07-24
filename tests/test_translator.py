import unittest

from app.models import SubtitleSegment
from app.translator import TranslationError, _chunks, _extract_json_array


class TranslatorUtilityTests(unittest.TestCase):
    def test_chunks_keep_segment_indices(self) -> None:
        segments = [SubtitleSegment(0, 1, "a" * 10), SubtitleSegment(1, 2, "b" * 10)]
        chunks = _chunks(segments, max_chars=12)
        self.assertEqual(chunks, [[(0, "a" * 10)], [(1, "b" * 10)]])

    def test_json_array_can_be_inside_markdown_fence(self) -> None:
        result = _extract_json_array('```json\n[{"id":0,"translation":"你好"}]\n```')
        self.assertEqual(result[0]["translation"], "你好")

    def test_invalid_translation_response_is_rejected(self) -> None:
        with self.assertRaises(TranslationError):
            _extract_json_array("not json")


if __name__ == "__main__":
    unittest.main()

