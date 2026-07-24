from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=1)
def _simplified_converter():
    try:
        from opencc import OpenCC
    except ImportError as exc:
        raise RuntimeError(
            "缺少简体中文转换组件，请执行 pip install -r requirements.txt。"
        ) from exc
    return OpenCC("t2s")


def to_simplified(text: str) -> str:
    """Normalize Traditional Chinese characters to Simplified Chinese."""
    return _simplified_converter().convert(text)


def contains_han(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def translation_should_contain_han(source: str) -> bool:
    """Ignore isolated names/codes, but require Chinese for normal foreign sentences."""
    alphabetic_words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", source)
    return len(alphabetic_words) >= 2 or len(source.strip()) >= 12

