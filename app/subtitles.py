from __future__ import annotations

from pathlib import Path

from .models import SubtitleSegment

MIN_SUBTITLE_DISPLAY_SECONDS = 0.2


def is_chinese_language(language: str | None) -> bool:
    if not language:
        return False
    normalized = language.lower().replace("_", "-")
    return normalized == "zh" or normalized.startswith("zh-") or normalized in {"yue", "cmn"}


def format_srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def subtitle_display_end(segment: SubtitleSegment) -> float:
    minimum_end = segment.start + MIN_SUBTITLE_DISPLAY_SECONDS
    return max(segment.end, minimum_end)


def render_vtt(segments: list[SubtitleSegment], bilingual: bool) -> str:
    from html import escape

    blocks = ["WEBVTT"]
    for segment in segments:
        start = format_srt_time(segment.start).replace(",", ".")
        end = format_srt_time(subtitle_display_end(segment)).replace(",", ".")
        text = escape(segment.text.strip())
        if bilingual and segment.translation:
            text += "\n" + escape(segment.translation.strip())
        blocks.append(f"{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + "\n"


def render_srt(segments: list[SubtitleSegment], bilingual: bool) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        end = subtitle_display_end(segment)
        lines = [segment.text.strip()]
        if bilingual and segment.translation:
            lines.append(segment.translation.strip())
        blocks.append(
            f"{index}\n{format_srt_time(segment.start)} --> {format_srt_time(end)}\n"
            + "\n".join(lines)
        )
    return "\n\n".join(blocks) + "\n"


def _format_ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass(text: str) -> str:
    return (
        text.strip()
        .replace("\\", "＼")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", r"\N")
        .replace("\n", r"\N")
    )


def render_ass(segments: list[SubtitleSegment], bilingual: bool) -> str:
    header = """[Script Info]
Title: YanMu generated subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,52,&H00FFFFFF,&H000000FF,&H00101824,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,58,1
Style: Bilingual,Noto Sans CJK SC,46,&H00FFFFFF,&H000000FF,&H00101824,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,48,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for segment in segments:
        end = subtitle_display_end(segment)
        text = _escape_ass(segment.text)
        style = "Default"
        if bilingual and segment.translation:
            style = "Bilingual"
            text = f"{text}\\N{{\\fs42\\c&H9DDEFF&}}{_escape_ass(segment.translation)}"
        events.append(
            "Dialogue: 0,"
            f"{_format_ass_time(segment.start)},{_format_ass_time(end)},{style},,0,0,0,,{text}"
        )
    return header + "\n".join(events) + "\n"


def write_subtitles(
    segments: list[SubtitleSegment], output_dir: Path, bilingual: bool
) -> tuple[Path, Path]:
    srt_path = output_dir / ("双语字幕.srt" if bilingual else "简体中文字幕.srt")
    ass_path = output_dir / "字幕样式.ass"
    srt_path.write_text(render_srt(segments, bilingual), encoding="utf-8-sig")
    ass_path.write_text(render_ass(segments, bilingual), encoding="utf-8-sig")
    (output_dir / "preview.vtt").write_text(render_vtt(segments, bilingual), encoding="utf-8")
    return srt_path, ass_path
