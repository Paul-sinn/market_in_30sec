from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class DailyBar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adjusted: bool  # OHLC가 분할·배당 조정가인지


class PriceSource(Protocol):
    def daily_bars(self, ticker: str, start: date, end: date) -> list[DailyBar]:
        """start~end 양 끝 포함, 날짜 오름차순. 데이터 없으면 []."""
        ...
