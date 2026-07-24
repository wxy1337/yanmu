import unittest

from app.text import contains_han, to_simplified, translation_should_contain_han


class SimplifiedChineseTests(unittest.TestCase):
    def test_traditional_chinese_is_normalized(self) -> None:
        self.assertEqual(
            to_simplified("歡迎使用語言字幕，裏面是測試。"),
            "欢迎使用语言字幕，里面是测试。",
        )

    def test_han_detection(self) -> None:
        self.assertTrue(contains_han("简体中文"))
        self.assertFalse(contains_han("English only"))

    def test_sentence_requires_chinese_translation(self) -> None:
        self.assertTrue(translation_should_contain_han("This is a complete sentence."))
        self.assertFalse(translation_should_contain_han("OpenAI"))


if __name__ == "__main__":
    unittest.main()
