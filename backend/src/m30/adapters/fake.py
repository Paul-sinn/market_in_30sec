"""가짜 시세·일정 어댑터. 시나리오 JSON 파일에서 데이터를 읽는다."""

import json
from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal
from pathlib import Path

from m30.adapters import SourceError
from m30.adapters.events import CorporateEvent, Earnings, EarningsTiming, ExDividend
from m30.adapters.prices import DailyBar
from m30.models import Coverage

REQUIRED_KEYS = {"coverage", "prices"}
OPTIONAL_KEYS = {"events", "event_failures"}  # 없으면 모든 티커가 일정 미지원. 다음 티켓은 선택 키로 더한다
BAR_KEYS = {f.name for f in fields(DailyBar)}
PRICE_KEYS = {"open", "high", "low", "close"}
EVENT_KEYS = {"earnings": {"kind", "day", "confirmed", "timing"}, "ex_dividend": {"kind", "day", "amount"}}


@dataclass(frozen=True)
class Scenario:
    coverage: list[Coverage]
    prices: dict[str, list[DailyBar]]  # 티커 → 날짜 오름차순
    events: dict[str, list[CorporateEvent]] = field(default_factory=dict)  # 키가 없는 티커 = 일정 미지원
    event_failures: frozenset[str] = frozenset()  # 이 티커는 SourceError


def load_scenario(path: Path) -> Scenario:
    path = Path(path)
    raw = json.loads(path.read_text(), parse_float=Decimal)
    if not REQUIRED_KEYS <= set(raw) <= REQUIRED_KEYS | OPTIONAL_KEYS:
        raise ValueError(
            f"{path.name}: top-level keys must be {sorted(REQUIRED_KEYS)} plus optional {sorted(OPTIONAL_KEYS)},"
            f" got {sorted(raw)}"
        )
    prices = {}
    for ticker, rows in raw["prices"].items():
        bars = sorted((_bar(path, ticker, row) for row in rows), key=lambda b: b.day)
        days = [b.day for b in bars]
        if len(set(days)) != len(days):
            raise ValueError(f"{path.name}: {ticker} has two bars on the same day")
        prices[ticker] = bars
    events = {
        ticker: [_event(path, ticker, row) for row in rows] for ticker, rows in raw.get("events", {}).items()
    }
    failures = frozenset(raw.get("event_failures", []))
    if both := sorted(failures & set(events)):
        raise ValueError(f"{path.name}: {', '.join(both)} in both 'events' and 'event_failures'")
    return Scenario(
        coverage=[_coverage(row) for row in raw["coverage"]],
        prices=prices,
        events=events,
        event_failures=failures,
    )


def _coverage(row: dict) -> Coverage:
    if row.get("leverage") is not None:
        row = {**row, "leverage": Decimal(row["leverage"])}
    return Coverage(**row)


def _event(path: Path, ticker: str, row: dict) -> CorporateEvent:
    keys = EVENT_KEYS.get(row.get("kind"))
    if keys is None:
        raise ValueError(f"{path.name}: {ticker} event key 'kind' must be one of {sorted(EVENT_KEYS)}")
    if set(row) != keys:
        raise ValueError(f"{path.name}: {ticker} {row['kind']} keys must be {sorted(keys)}, got {sorted(row)}")
    day = date.fromisoformat(row["day"])
    if row["kind"] == "earnings":
        if not isinstance(row["confirmed"], bool):
            raise ValueError(f"{path.name}: {ticker} earnings key 'confirmed' must be true or false")
        if row["timing"] not in (None, *EarningsTiming):
            timings = [t.value for t in EarningsTiming]
            raise ValueError(f"{path.name}: {ticker} earnings key 'timing' must be one of {timings} or null")
        timing = None if row["timing"] is None else EarningsTiming(row["timing"])
        return Earnings(day=day, confirmed=row["confirmed"], timing=timing)
    amount = row["amount"]
    if isinstance(amount, bool) or not isinstance(amount, int | Decimal) or amount <= 0:
        raise ValueError(f"{path.name}: {ticker} ex_dividend key 'amount' must be a number greater than 0")
    return ExDividend(day=day, amount=Decimal(amount))


def _bar(path: Path, ticker: str, row: dict) -> DailyBar:
    if set(row) != BAR_KEYS:
        raise ValueError(f"{path.name}: {ticker} bar keys must be {sorted(BAR_KEYS)}, got {sorted(row)}")
    if not isinstance(row["adjusted"], bool):
        raise ValueError(f"{path.name}: {ticker} bar key 'adjusted' must be true or false")
    return DailyBar(
        day=date.fromisoformat(row["day"]),
        **{k: Decimal(row[k]) for k in PRICE_KEYS},
        volume=int(row["volume"]),
        adjusted=row["adjusted"],
    )


class FakePriceSource:
    def __init__(self, scenario: Scenario) -> None:
        self._prices = scenario.prices

    def daily_bars(self, ticker: str, start: date, end: date) -> list[DailyBar]:
        return [b for b in self._prices.get(ticker, []) if start <= b.day <= end]


class FakeEventSource:
    def __init__(self, scenario: Scenario) -> None:
        self._events = scenario.events
        self._failures = scenario.event_failures

    def upcoming_events(self, ticker: str, start: date, end: date) -> list[CorporateEvent] | None:
        if ticker in self._failures:
            raise SourceError(f"fake event source failed for {ticker}")
        if ticker not in self._events:
            return None
        return [e for e in self._events[ticker] if start <= e.day <= end]
