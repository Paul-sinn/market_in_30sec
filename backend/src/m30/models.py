from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class LineStatus(StrEnum):
    CHECKED_FOUND = "checked_found"  # 확인함·있음 (등락률: 계산함)
    CHECKED_NONE = "checked_none"  # 확인함·없음 (조용한 날로 치는 유일한 상태)
    DELAYED = "delayed"  # 지연
    UNSUPPORTED = "unsupported"  # 미지원


class CardStatus(StrEnum):
    NORMAL = "normal"
    FALLBACK = "fallback"  # 축소판 (첫 번째 줄 없음)


@dataclass(frozen=True)
class Coverage:
    ticker: str
    name: str


@dataclass(frozen=True)
class CardLine:
    text: str
    status: LineStatus
    checked_at: datetime
    source_scope: str | None  # status가 UNSUPPORTED일 때만 None

    def __post_init__(self) -> None:
        # 시간대 없는 시각은 timestamptz에 세션 시간대(UTC)로 들어가 4~5시간이 조용히 어긋난다
        if self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        if self.source_scope is None and self.status is not LineStatus.UNSUPPORTED:
            raise ValueError("source_scope is required unless status is unsupported")


@dataclass(frozen=True)
class StockCard:
    ticker: str
    trading_day: date
    status: CardStatus
    change_pct: Decimal | None  # 소수 첫째 자리로 반올림된 % 값
    change_status: LineStatus
    news_line: CardLine | None = None  # None = 아직 만들지 않음
    event_line: CardLine | None = None
    price_fact_line: CardLine | None = None
    updated_at: datetime | None = None  # DB가 채움. 저장소에서 읽은 카드에만 있음 (ET)
