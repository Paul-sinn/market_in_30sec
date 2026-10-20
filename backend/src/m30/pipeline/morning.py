"""아침 파이프라인. 바깥 인터페이스는 run 하나."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from m30.adapters import SourceError
from m30.adapters.events import EventSource
from m30.adapters.prices import PriceSource
from m30.config import ET
from m30.db.store import CardStore
from m30.models import CardLine, CardStatus, LineStatus, StockCard
from m30.pipeline.compute import bars_usable, change_pct
from m30.pipeline.lines import (
    EVENT_SCOPE,
    EVENT_WINDOW,
    PRICE_SCOPE,
    delayed_line,
    event_line,
    leverage_tag,
    price_fact_line,
)

LOOKBACK = timedelta(weeks=53)  # 52주 이력 + 52주 전 날이 휴장일이어도 거래일이 들어가는 1주


@dataclass(frozen=True)
class RunSummary:
    trading_day: date
    cards_saved: int
    change_delayed: tuple[str, ...]  # 등락률을 계산 못 해 delayed로 저장한 티커 (오름차순)


class MorningPipeline:
    def __init__(self, *, prices: PriceSource, events: EventSource, store: CardStore) -> None:
        self._prices = prices
        self._events = events
        self._store = store

    def run(self, trading_day: date) -> RunSummary:
        if isinstance(trading_day, datetime):
            # datetime은 date의 하위 클래스라 그대로 두면 시각이 거래일로 쓰인다
            raise TypeError("trading_day must be a date, not a datetime")
        checked_at = datetime.now(ET)  # 이 실행의 모든 줄이 같은 확인 시각을 쓴다
        saved = 0
        delayed = []
        for cov in self._store.list_coverage():
            bars = self._prices.daily_bars(cov.ticker, trading_day - LOOKBACK, trading_day - timedelta(days=1))
            usable = bars_usable(bars, trading_day)  # 지난 카드 값은 읽지 않는다. 그날 받은 봉으로만
            pct = change_pct(bars) if usable else None
            price_fact = price_fact_line(bars, checked_at) if usable else delayed_line(PRICE_SCOPE, checked_at)
            self._store.upsert_card(
                StockCard(
                    ticker=cov.ticker,
                    trading_day=trading_day,
                    status=CardStatus.FALLBACK,  # 이번 티켓은 첫 번째 줄을 만들지 않는다
                    change_pct=pct,
                    change_status=LineStatus.DELAYED if pct is None else LineStatus.CHECKED_FOUND,
                    event_line=self._event_line(cov.ticker, trading_day, checked_at),
                    price_fact_line=price_fact,
                    leverage_tag=leverage_tag(cov.leverage),
                )
            )
            saved += 1
            if pct is None:
                delayed.append(cov.ticker)
        return RunSummary(trading_day=trading_day, cards_saved=saved, change_delayed=tuple(delayed))

    def _event_line(self, ticker: str, trading_day: date, checked_at: datetime) -> CardLine:
        try:
            events = self._events.upcoming_events(ticker, trading_day, trading_day + EVENT_WINDOW)
        except SourceError:  # 다른 예외는 버그라 그대로 올린다
            return delayed_line(EVENT_SCOPE, checked_at)
        return event_line(events, trading_day, checked_at)
