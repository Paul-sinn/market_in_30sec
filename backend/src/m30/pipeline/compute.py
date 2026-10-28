"""숫자 계산·표기. 프로젝트의 %·금액 반올림은 여기 한 곳뿐이다."""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from m30.adapters.prices import DailyBar
from m30.trading_day import previous_trading_day


def round_pct(value: Decimal) -> Decimal:
    """소수 첫째 자리, ROUND_HALF_UP(0에서 먼 쪽: -1.25 → -1.3). 결과 0은 -0.0이 아니라 0.0."""
    q = value.quantize(Decimal("0.1"), ROUND_HALF_UP)
    return abs(q) if q == 0 else q


def bars_usable(bars: Sequence[DailyBar], trading_day: date) -> bool:
    """등락률·세 번째 줄을 계산해도 되는 봉인가. False면 둘 다 지연.
    True = 봉 2개 이상, 전부 분할 조정가, 전부 open·high·low·close > 0, 마지막 봉 = 직전 거래일,
           이웃한 봉은 모두 이웃한 거래일(빠진 거래일·휴장일 봉이 있으면 False, #4 R-8). 첫 봉보다 앞은 보지 않는다."""
    return (
        len(bars) >= 2
        and all(b.adjusted and min(b.open, b.high, b.low, b.close) > 0 for b in bars)
        and bars[-1].day == previous_trading_day(trading_day)
        and all(a.day == previous_trading_day(b.day) for a, b in pairwise(bars))
    )


def change_pct(bars: Sequence[DailyBar]) -> Decimal | None:
    """bars: 날짜 오름차순, 카드 거래일 전날까지. 마지막 봉 종가 대 전일 종가 등락률(%). 계산 못 하면 None."""
    if len(bars) < 2:
        return None
    prev, last = bars[-2].close, bars[-1].close
    if prev <= 0:
        return None
    return round_pct((last - prev) / prev * 100)


def streak(bars: Sequence[DailyBar]) -> int:
    """마지막 봉부터 같은 방향이 이어진 날 수. 상승 +n, 하락 −n, 마지막 날이 보합이면 0. bars는 bars_usable 통과분.
    하루 방향 = 반올림한 등락률의 부호. 0.0%(보합)이면 끊긴다(카드에 0.0%로 보인 날을 연속에 넣지 않는다)."""
    n = 0
    for prev, cur in zip(reversed(bars[:-1]), reversed(bars[1:])):
        pct = round_pct((cur.close - prev.close) / prev.close * 100)
        step = (pct > 0) - (pct < 0)
        if step == 0 or (n and (step > 0) != (n > 0)):
            break
        n += step
    return n


def week52_gaps(bars: Sequence[DailyBar]) -> tuple[Decimal, Decimal] | None:
    """(52주 고점 대비 아래 %, 52주 저점 대비 위 %), 둘 다 round_pct, 음수면 0.0.
    창 = 마지막 봉 날짜 − 52주보다 뒤의 봉(마지막 봉 포함). 고점 = 창의 장중 고가 최댓값, 저점 = 장중 저가 최솟값.
    None = 첫 봉이 마지막 봉 날짜 − 52주보다 뒤(상장 1년 미만·이력 부족)."""
    last = bars[-1]
    start = last.day - timedelta(weeks=52)
    if bars[0].day > start:
        return None
    window = [b for b in bars if b.day > start]
    high = max(b.high for b in window)
    low = min(b.low for b in window)
    zero = Decimal("0.0")  # 종가 > 고가 같은 데이터 오류에 음수 거리를 내지 않는다
    below = max(round_pct((high - last.close) / high * 100), zero)
    above = max(round_pct((last.close - low) / low * 100), zero)
    return below, above


USD_UNITS = (("", 1, "1"), ("K", 10**3, "0.1"), ("M", 10**6, "0.1"), ("B", 10**9, "0.1"), ("T", 10**12, "0.1"))


def format_usd(amount: Decimal) -> str:
    """큰 금액 축약(U6 = A): $94B, $1.2M, $1.2T, $950K, $950. 단위로 나눈 값을 소수 첫째 자리 ROUND_HALF_UP, .0은 뺀다.
    작은 단위부터 반올림 값이 1000 미만인 첫 단위를 쓴다 → 반올림해서 1000이 되면 다음 단위(999.95M → $1B).
    0 미만이면 ValueError."""
    if amount < 0:
        raise ValueError("amount must not be negative")
    for unit, size, step in USD_UNITS:
        shown = (amount / size).quantize(Decimal(step), ROUND_HALF_UP)
        if shown < 1000 or unit == "T":
            return f"${shown:f}".removesuffix(".0") + unit


def format_per_share(amount: Decimal) -> str:
    """주당 금액(U7 = B). 소수 넷째 자리 ROUND_HALF_UP → 끝자리 0 제거 → 최소 2자리.
    0.70 → $0.70, 1.5 → $1.50, 0.2475 → $0.2475, 0.00456 → $0.0046. 0보다 크고 0.0001 미만 → <$0.0001.
    0 이하면 ValueError."""
    if amount <= 0:
        raise ValueError("per-share amount must be greater than 0")
    if amount < Decimal("0.0001"):  # 반올림하면 $0.0000(틀린 0)이나 $0.0001(발표값보다 큼)이 된다
        return "<$0.0001"
    shown = amount.quantize(Decimal("0.0001"), ROUND_HALF_UP).normalize()
    if shown.as_tuple().exponent > -2:  # 발표값 자릿수는 살리되 센트 자리까지는 채운다
        shown = shown.quantize(Decimal("0.01"))
    return f"${shown:f}"


# 원문 숫자 → 카드 표기(스펙 #6 D3 표). 대안 순서 = 표 순서, 왼쪽부터 finditer. 겹치는 \s* 반복 없이 공백은 " ?"만
_NUM = r"\d+(?:,\d{3})*(?:\.\d+)?"
_UNIT = r"(?i:thousand|million|billion|trillion|mn|mm|bn|[kmbt])\b"
_PER_SHARE = r" (?:per (?:diluted |basic )?share|a share)\b"
_PCT = r" ?(?:%|(?i:percent|per cent)\b)"
_CARD_NUMBER = re.compile(
    rf"\$ ?(?P<ra>{_NUM})(?P<rc> to | and | through | ?[-–] ?)\$? ?(?P<rb>{_NUM})(?: ?(?P<ru>{_UNIT})|(?P<rs>{_PER_SHARE}))"
    rf"|\$ ?(?P<un>{_NUM}) ?(?P<uu>{_UNIT})"
    rf"|\$ ?(?P<sn>{_NUM})(?P<ss>{_PER_SHARE})"
    rf"|\$ ?{_NUM}"  # 단위 없는 금액: 단위를 모르면 1,000배 틀린 값이 "계산된 값"이 된다
    rf"|(?P<pa>\d{{1,3}}(?:\.\d+)?)(?P<pc> to |[-–])(?P<pb>{_NUM}){_PCT}"
    rf"|(?P<pn>{_NUM}){_PCT}"
    r"|(?P<q>\bQ[1-4]\b)"
    r"|\d+(?:[.,]\d+)*"
)
_UNIT_SIZE = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mn": 6, "mm": 6, "billion": 9, "b": 9, "bn": 9,
              "trillion": 12, "t": 12}


def _num(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _money(number: str, unit: str | None) -> tuple[str, bool]:
    """(표기, 목록에 넣나). 단위 없음 = 주당 금액. 주당 0과 표기할 수 없는 값은 가린다."""
    try:
        if unit is not None:
            return format_usd(_num(number) * 10 ** _UNIT_SIZE[unit.lower()]), True
        return (format_per_share(_num(number)), True) if _num(number) > 0 else ("#", False)
    except ArithmeticError:  # Decimal 정밀도(28자리)를 넘으면 반올림이 InvalidOperation: 공시 하나가 실행을 멈추지 않게 가린다
        return "#", False


def _pct(number: str) -> tuple[str, bool]:
    try:
        return f"{round_pct(_num(number))}%", True
    except ArithmeticError:  # _money와 같은 이유
        return "#", False


def _pieces(m: re.Match) -> list[tuple[str, bool]]:
    if m["ra"]:
        a, b = _money(m["ra"], m["ru"]), _money(m["rb"], m["ru"])
        return [a, (m["rc"], False), b, *([(m["rs"], False)] if m["rs"] and b[1] else [])]
    if m["un"]:
        return [_money(m["un"], m["uu"])]
    if m["sn"]:
        shown = _money(m["sn"], None)
        return [shown, *([(m["ss"], False)] if shown[1] else [])]
    if m["pa"]:
        return [_pct(m["pa"]), (m["pc"], False), _pct(m["pb"])]
    if m["pn"]:
        return [_pct(m["pn"])]
    return [(m[0], False) if m["q"] else ("#", False)]


def card_numbers(text: str, max_chars: int) -> tuple[str, bool, tuple[str, ...]]:
    """원문 속 금액·%를 카드 표기(format_usd·format_per_share·round_pct)로 바꾸고 나머지 숫자는 '#'으로 가린 뒤
    max_chars자까지 자른다(바꾼 값은 쪼개지 않는다). 규칙은 스펙 #6 D3 표.
    (바꾼 텍스트, 잘렸는지, 남은 텍스트에 통째로 있는 바꾼 값 — 처음 나온 순서, 중복 없음)."""
    out: list[str] = []
    values: list[tuple[int, int, str]] = []  # (시작, 끝, 값) — 바꾼 텍스트 안 위치
    size = pos = 0
    for m in _CARD_NUMBER.finditer(text):
        for piece, listed in [(text[pos : m.start()], False), *_pieces(m)]:
            if listed:
                values.append((size, size + len(piece), piece))
            out.append(piece)
            size += len(piece)
        pos = m.end()
    full = "".join(out) + text[pos:]
    cut = min(len(full), max_chars)
    cut = next((start for start, end, _ in values if start < cut < end), cut)
    return full[:cut], len(full) > max_chars, tuple(dict.fromkeys(v for _, end, v in values if end <= cut))
