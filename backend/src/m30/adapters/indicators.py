from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class IndicatorRelease:
    name: str  # 화면 이름. 어댑터 코드가 정한 값("CPI", "Jobs report"). 외부 제목을 그대로 넣지 않는다(#50, MarketNewsItem.source와 같은 규칙)
    released_at: datetime  # 발표 시각, tz-aware
    raw: str  # 출처가 준 원본 그대로


class IndicatorSource(Protocol):
    def releases(self, start: date, end: date) -> list[IndicatorRelease] | None:
        """발표 시각의 동부 날짜가 start~end(양 끝 포함)인 지표 일정. [] = 확인했지만 없음. None = 출처가 없음(미지원).
        실패는 SourceError. None으로 돌려주지 않는다."""
        ...
