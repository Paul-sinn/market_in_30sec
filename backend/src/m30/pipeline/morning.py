"""아침 파이프라인. 바깥 인터페이스는 run 하나."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from m30.adapters.prices import PriceSource
from m30.db.store import CardStore
from m30.models import CardStatus, LineStatus, StockCard
from m30.pipeline.compute import change_pct

LOOKBACK = timedelta(days=14)


@dataclass(frozen=True)
class RunSummary:
    trading_day: date
    cards_saved: int
    change_delayed: tuple[str, ...]  # 등락률을 계산 못 해 delayed로 저장한 티커 (오름차순)


class MorningPipeline:
    def __init__(self, *, prices: PriceSource, store: CardStore) -> None:
        self._prices = prices
        self._store = store

    def run(self, trading_day: date) -> RunSummary:
        if isinstance(trading_day, datetime):
            # datetime은 date의 하위 클래스라 그대로 두면 시각이 거래일로 쓰인다
            raise TypeError("trading_day must be a date, not a datetime")
        saved = 0
        delayed = []
        for cov in self._store.list_coverage():
            bars = self._prices.daily_bars(cov.ticker, trading_day - LOOKBACK, trading_day - timedelta(days=1))
            pct = change_pct(bars)
            self._store.upsert_card(
                StockCard(
                    ticker=cov.ticker,
                    trading_day=trading_day,
                    status=CardStatus.FALLBACK,  # 이번 티켓은 첫 번째 줄을 만들지 않는다
                    change_pct=pct,
                    change_status=LineStatus.DELAYED if pct is None else LineStatus.CHECKED_FOUND,
                )
            )
            saved += 1
            if pct is None:
                delayed.append(cov.ticker)
        return RunSummary(trading_day=trading_day, cards_saved=saved, change_delayed=tuple(delayed))
