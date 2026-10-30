from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class MarketNewsItem:
    """시장 전체 소식의 원천인 공식 발표 하나(#11). title·text는 프롬프트 데이터 블록에만 들어간다."""

    key: str  # 출처 안에서 유일한 id(GUID·URL). 중복 제거 키
    source: str  # 발표 기관 표기. 어댑터 코드가 정한 값, 60자 이하 한 줄
    published_at: datetime  # tz-aware
    title: str  # 원문 그대로
    text: str  # 원문 그대로
    raw: str  # market_news_item.payload


class MarketNewsSource(Protocol):
    def items(self, since: datetime, until: datetime) -> list[MarketNewsItem] | None:
        """published_at이 [since, until)인 발표. 순서 무관. [] = 확인했지만 없음. None = 출처가 없음(미지원). 실패는 SourceError."""
        ...
