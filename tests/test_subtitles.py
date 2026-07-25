import tempfile
import unittest
from pathlib import Path

from app.models import SubtitleSegment
from app.subtitles import (
    format_srt_time,
    is_chinese_language,
    render_ass,
    render_srt,
    subtitle_display_end,
    write_subtitles,
)


class SubtitleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.segments = [
            SubtitleSegment(0.0, 1.25, "Hello", "你好"),
            SubtitleSegment(2.5, 4.0, "World", "世界"),
        ]

    def test_chinese_language_variants(self) -> None:
        self.assertTrue(is_chinese_language("zh"))
        self.assertTrue(is_chinese_language("zh-CN"))
        self.assertTrue(is_chinese_language("yue"))
        self.assertFalse(is_chinese_language("en"))

    def test_srt_timestamp_rounding(self) -> None:
        self.assertEqual(format_srt_time(3661.234), "01:01:01,234")

    def test_subtitle_display_is_capped_during_long_silence(self) -> None:
        segment = SubtitleSegment(10.0, 42.0, "Long silence follows")
        self.assertEqual(subtitle_display_end(segment), 15.0)
        result = render_srt([segment], bilingual=False)
        self.assertIn("00:00:10,000 --> 00:00:15,000", result)

    def test_subtitle_display_keeps_short_segments_visible(self) -> None:
        segment = SubtitleSegment(3.0, 3.05, "Short")
        self.assertEqual(subtitle_display_end(segment), 3.2)

    def test_ass_timestamp_uses_capped_display_end(self) -> None:
        result = render_ass([SubtitleSegment(1.0, 20.0, "Hello")], bilingual=False)
        self.assertIn("Dialogue: 0,0:00:01.00,0:00:06.00", result)

    def test_bilingual_srt_has_two_lines(self) -> None:
        result = render_srt(self.segments, bilingual=True)
        self.assertIn("Hello\n你好", result)
        self.assertLess(result.index("Hello"), result.index("你好"))
        self.assertIn("00:00:02,500 --> 00:00:04,000", result)

    def test_monolingual_srt_omits_translation(self) -> None:
        result = render_srt(self.segments, bilingual=False)
        self.assertNotIn("你好", result)

    def test_ass_escapes_braces(self) -> None:
        result = render_ass([SubtitleSegment(0, 1, "A {tag}", "中")], bilingual=True)
        self.assertIn(r"A \{tag\}", result)
        self.assertIn(r"\N", result)
        self.assertLess(result.index(r"A \{tag\}"), result.index("中"))

    def test_output_names_follow_language_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            srt, ass = write_subtitles(self.segments, Path(directory), bilingual=True)
            self.assertEqual(srt.name, "双语字幕.srt")
            self.assertTrue(srt.exists())
            self.assertTrue(ass.exists())

    def test_chinese_output_name_explicitly_says_simplified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            srt, _ = write_subtitles(self.segments, Path(directory), bilingual=False)
            self.assertEqual(srt.name, "简体中文字幕.srt")


if __name__ == "__main__":
    unittest.main()
