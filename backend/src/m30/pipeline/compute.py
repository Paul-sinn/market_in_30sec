"""숫자 계산. 프로젝트의 % 반올림은 여기 한 곳뿐이다."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from m30.adapters.prices import DailyBar


def round_pct(value: Decimal) -> Decimal:
    """소수 첫째 자리, ROUND_HALF_UP(0에서 먼 쪽: -1.25 → -1.3). 결과 0은 -0.0이 아니라 0.0."""
    q = value.quantize(Decimal("0.1"), ROUND_HALF_UP)
    return abs(q) if q == 0 else q


def change_pct(bars: Sequence[DailyBar]) -> Decimal | None:
    """bars: 날짜 오름차순, 카드 거래일 전날까지. 마지막 봉 종가 대 전일 종가 등락률(%). 계산 못 하면 None."""
    if len(bars) < 2:
        return None
    prev, last = bars[-2].close, bars[-1].close
    if prev <= 0:
        return None
    return round_pct((last - prev) / prev * 100)
