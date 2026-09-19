from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SegmentEdit(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=20000)
    translation: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.end <= self.start:
            raise ValueError("结束时间必须晚于开始时间。")
        return self


class SubtitleEdit(BaseModel):
    revision: str = Field(min_length=64, max_length=64)
    segments: list[SegmentEdit] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def ordered_segments(self):
        for previous, current in zip(self.segments, self.segments[1:], strict=False):
            if current.start < previous.start:
                raise ValueError("字幕必须按开始时间排序。")
        return self
