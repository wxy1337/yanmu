from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .models import SubtitleSegment
from .text import contains_han, to_simplified, translation_should_contain_han


class TranslationError(RuntimeError):
    pass


@dataclass(slots=True)
class TranslationConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout: float


def _chunks(segments: list[SubtitleSegment], max_chars: int = 4500) -> list[list[tuple[int, str]]]:
    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    size = 0
    for index, segment in enumerate(segments):
        length = len(segment.text)
        if current and size + length > max_chars:
            chunks.append(current)
            current = []
            size = 0
        current.append((index, segment.text))
        size += length
    if current:
        chunks.append(current)
    return chunks


def _extract_json_array(content: str) -> list[dict[str, Any]]:
    start = content.find("[")
    end = content.rfind("]")
    if start < 0 or end < start:
        raise TranslationError("翻译接口没有返回预期的 JSON 数组。")
    try:
        result = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise TranslationError("翻译接口返回内容无法解析。") from exc
    if not isinstance(result, list):
        raise TranslationError("翻译接口返回格式不正确。")
    return result


class Translator:
    def __init__(self, config: TranslationConfig):
        self.config = config

    def translate(self, segments: list[SubtitleSegment], source_language: str) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise TranslationError("缺少 httpx，请先安装项目依赖。") from exc

        with httpx.Client(timeout=self.config.timeout) as client:
            if self.config.provider == "libretranslate":
                self._translate_libre(client, segments, source_language)
            else:
                self._translate_openai_compatible(client, segments, source_language)

    def _translate_openai_compatible(
        self, client: Any, segments: list[SubtitleSegment], source_language: str
    ) -> None:
        if not self.config.api_key and "api.openai.com" in self.config.base_url:
            raise TranslationError(
                "外语视频需要翻译服务。请在 .env 中填写 TRANSLATION_API_KEY，"
                "或将 TRANSLATION_BASE_URL 指向本地 Ollama/LM Studio。"
            )
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        for chunk in _chunks(segments):
            items = [{"id": index, "text": text} for index, text in chunk]
            payload = {
                "model": self.config.model,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是专业字幕译者。将输入字幕准确、简洁地翻译成简体中文。"
                            "保留人名、术语、语气和上下文，不添加解释。"
                            "译文必须使用简体中文，不能只复述外文原文。"
                            "只返回 JSON 数组，每项格式为 {\"id\":数字,\"translation\":\"译文\"}。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"源语言代码：{source_language}\n字幕："
                        + json.dumps(items, ensure_ascii=False),
                    },
                ],
            }
            response = client.post(url, headers=headers, json=payload)
            if response.is_error:
                raise TranslationError(
                    f"翻译接口请求失败（HTTP {response.status_code}）：{response.text[:300]}"
                )
            try:
                content = response.json()["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(
                        block.get("text", "") for block in content if isinstance(block, dict)
                    )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise TranslationError("翻译接口响应格式不兼容。") from exc
            translated = _extract_json_array(str(content))
            mapping = {
                int(item["id"]): to_simplified(str(item["translation"]).strip())
                for item in translated
                if "id" in item and "translation" in item
            }
            missing = [index for index, _ in chunk if not mapping.get(index)]
            if missing:
                raise TranslationError(f"翻译结果缺少 {len(missing)} 条字幕，请重试。")
            for index, _ in chunk:
                if translation_should_contain_han(segments[index].text) and not contains_han(
                    mapping[index]
                ):
                    raise TranslationError(
                        f"第 {index + 1} 条译文没有包含中文，翻译服务可能复述了外文原文。"
                    )
                segments[index].translation = mapping[index]

    def _translate_libre(
        self, client: Any, segments: list[SubtitleSegment], source_language: str
    ) -> None:
        url = self.config.base_url.rstrip("/") + "/translate"
        for segment in segments:
            payload = {
                "q": segment.text,
                "source": source_language,
                "target": "zh",
                "format": "text",
            }
            if self.config.api_key:
                payload["api_key"] = self.config.api_key
            response = client.post(url, json=payload)
            if response.is_error:
                raise TranslationError(
                    f"LibreTranslate 请求失败（HTTP {response.status_code}）。"
                )
            try:
                segment.translation = to_simplified(response.json()["translatedText"].strip())
                if translation_should_contain_han(segment.text) and not contains_han(
                    segment.translation
                ):
                    raise TranslationError("LibreTranslate 返回的译文没有包含中文。")
            except (KeyError, TypeError, ValueError) as exc:
                raise TranslationError("LibreTranslate 响应格式不正确。") from exc
