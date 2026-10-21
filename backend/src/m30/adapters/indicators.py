from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class IndicatorRelease:
    name: str  # 지표 이름, 출처 표기 그대로 ("CPI")
    released_at: datetime  # 발표 시각, tz-aware
    raw: str  # 출처가 준 원본 그대로


class IndicatorSource(Protocol):
    def releases(self, start: date, end: date) -> list[IndicatorRelease]:
        """발표 시각의 동부 날짜가 start~end(양 끝 포함)인 지표 일정. [] = 확인했지만 없음. 실패는 SourceError."""
        ...
