from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class EarningsTiming(StrEnum):
    BEFORE_OPEN = "before_open"
    AFTER_CLOSE = "after_close"


@dataclass(frozen=True)
class Earnings:
    day: date
    confirmed: bool  # False = 추정일 → (est.)
    timing: EarningsTiming | None  # None = 발표 시점 모름 → 문구에서 뺀다


@dataclass(frozen=True)
class ExDividend:
    day: date  # 배당락일
    amount: Decimal  # 주당 달러, > 0. 회사가 발표한 배당만 (벤더 예상치는 빼야 한다. 템플릿에 (est.) 자리가 없다)


CorporateEvent = Earnings | ExDividend


class EventSource(Protocol):
    def upcoming_events(self, ticker: str, start: date, end: date) -> list[CorporateEvent] | None:
        """start~end(양 끝 포함)의 실적일·배당락일. 순서 보장 없음.
        [] = 확인했지만 없음. None = 이 출처가 이 종목을 다루지 않음(미지원).
        실패(네트워크·응답 형식 등)는 SourceError. None으로 돌려주지 않는다."""
        ...
