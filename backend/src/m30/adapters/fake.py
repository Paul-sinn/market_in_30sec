"""가짜 시세 어댑터. 시나리오 JSON 파일에서 데이터를 읽는다."""

import json
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from pathlib import Path

from m30.adapters.prices import DailyBar
from m30.models import Coverage

SCENARIO_KEYS = {"coverage", "prices"}  # #4·#5가 키를 추가할 때 같이 늘린다
BAR_KEYS = {f.name for f in fields(DailyBar)}
PRICE_KEYS = {"open", "high", "low", "close"}


@dataclass(frozen=True)
class Scenario:
    coverage: list[Coverage]
    prices: dict[str, list[DailyBar]]  # 티커 → 날짜 오름차순


def load_scenario(path: Path) -> Scenario:
    raw = json.loads(Path(path).read_text(), parse_float=Decimal)
    if set(raw) != SCENARIO_KEYS:
        raise ValueError(f"{path.name}: top-level keys must be {sorted(SCENARIO_KEYS)}, got {sorted(raw)}")
    prices = {}
    for ticker, rows in raw["prices"].items():
        bars = sorted((_bar(path, ticker, row) for row in rows), key=lambda b: b.day)
        days = [b.day for b in bars]
        if len(set(days)) != len(days):
            raise ValueError(f"{path.name}: {ticker} has two bars on the same day")
        prices[ticker] = bars
    return Scenario(coverage=[Coverage(**row) for row in raw["coverage"]], prices=prices)


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
