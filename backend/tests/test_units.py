"""순수 함수 경계값. DB 없이 돈다."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from m30.adapters.events import Earnings, EarningsTiming, ExDividend
from m30.adapters.prices import DailyBar
from m30.config import ET, ConfigError, is_local_db, load_settings
from m30.models import CardLine, LineStatus
from m30.pipeline.compute import change_pct, format_per_share, format_usd, round_pct, streak
from m30.pipeline.lines import EVENT_WINDOW, event_line, leverage_tag, price_fact_line
from m30.trading_day import previous_trading_day

CHECKED = datetime(2026, 10, 16, 7, 30, tzinfo=ET)


def test_DB_주소가_없으면_변수_이름만_알려주고_멈춘다():
    with pytest.raises(ConfigError, match="SUPABASE_DB_URL"):
        load_settings({})


def test_설정을_출력해도_DB_비밀번호가_보이지_않는다():
    settings = load_settings({"SUPABASE_DB_URL": "postgresql://u:s3cret@127.0.0.1:54322/postgres"})
    assert "s3cret" not in repr(settings)


@pytest.mark.parametrize(
    "url, local",
    [
        ("postgresql://postgres:pw@127.0.0.1:54322/postgres", True),
        ("postgresql://postgres:pw@localhost:54322/postgres", True),
        ("postgresql://postgres:pw@[::1]:54322/postgres", True),
        ("host=127.0.0.1 port=54322 user=postgres", True),
        ("postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres", False),
        ("postgresql://postgres:pw@127.0.0.1.example.com:5432/postgres", False),
        ("postgresql://postgres:pw@/postgres", False),
    ],
)
def test_로컬_DB_주소만_로컬로_인정한다(url, local):
    assert is_local_db(url) is local


@pytest.mark.parametrize(
    "raw, shown",
    [("1.25", "1.3"), ("-1.25", "-1.3"), ("0.04", "0.0"), ("-0.04", "0.0"), ("0", "0.0")],
)
def test_등락률은_소수_첫째_자리에서_0에서_먼_쪽으로_반올림하고_음수_0은_없다(raw, shown):
    assert str(round_pct(Decimal(raw))) == shown


def bar(day, close):
    c = Decimal(close)
    return DailyBar(day=date(2026, 10, day), open=c, high=c, low=c, close=c, volume=1000, adjusted=True)


@pytest.mark.parametrize(
    "bars",
    [
        [bar(15, "180.00")],  # 봉 1개
        [bar(14, "0"), bar(15, "5.00")],  # 전일 종가 0
        [bar(14, "-1.00"), bar(15, "5.00")],  # 전일 종가 음수
    ],
    ids=["봉_1개", "전일_종가_0", "전일_종가_음수"],
)
def test_계산할_수_없으면_등락률을_만들지_않는다(bars):
    assert change_pct(bars) is None


def test_시간대_없는_확인_시각으로는_줄을_만들_수_없다():
    with pytest.raises(ValueError, match="checked_at"):
        CardLine("No new SEC filings found", LineStatus.CHECKED_NONE, datetime(2026, 10, 16, 7, 30), "SEC filings")


def test_출처_범위는_미지원_줄에서만_비울_수_있다():
    checked = datetime(2026, 10, 16, 7, 30, tzinfo=ET)
    assert CardLine("Not covered yet", LineStatus.UNSUPPORTED, checked, None).source_scope is None
    with pytest.raises(ValueError, match="source_scope"):
        CardLine("No new SEC filings found", LineStatus.CHECKED_NONE, checked, None)


@pytest.mark.parametrize(
    "day, previous",
    [((10, 19), (10, 16)), ((10, 13), (10, 12)), ((10, 17), (10, 16)), ((10, 18), (10, 16))],
    ids=["월요일", "화요일", "토요일", "일요일"],
)
def test_직전_거래일은_주말을_건너뛴다(day, previous):
    assert previous_trading_day(date(2026, *day)) == date(2026, *previous)


def ohlc(day, close):
    c = Decimal(close)
    return DailyBar(day=day, open=c, high=c, low=c, close=c, volume=1000, adjusted=True)


def week52(last_close, first_day=date(2025, 10, 16)):
    """마지막 봉 2026-10-15. 2026-10-15 − 52주 = 2025-10-16. 고점 100, 저점 80(25% 아래라 근처 아님)."""
    days_closes = [(first_day, "100"), (date(2026, 3, 2), "80"), (date(2026, 6, 1), "100"), (date(2026, 10, 14), "100"),
                   (date(2026, 10, 15), last_close)]
    return [ohlc(d, c) for d, c in days_closes]


@pytest.mark.parametrize(
    "last_close, text",
    [("100", "At 52-week high"), ("99.96", "At 52-week high"), ("99.95", "0.1% below 52-week high")],
    ids=["정확히_같음", "0.04%_아래는_0.0", "0.05%_아래는_0.1"],
)
def test_52주_고점과_정확히_같거나_반올림해_0_0이면_At_52_week_high다(last_close, text):
    assert price_fact_line(week52(last_close), CHECKED).text == text


@pytest.mark.parametrize(
    "first_day, text",
    [(date(2025, 10, 16), "At 52-week high"), (date(2025, 10, 17), "No additional price highlights")],
    ids=["52주_전_날부터_있음", "하루_모자람"],
)
def test_52주_사실은_마지막_봉_52주_전까지_이력이_있어야_쓴다(first_day, text):
    assert price_fact_line(week52("100", first_day), CHECKED).text == text


@pytest.mark.parametrize(
    "last_close, text",
    [
        ("90", "10.0% below 52-week high"),  # (100 − 90) / 100, 저점 80에서 12.5% 위
        ("89.9", "No additional price highlights"),  # 고점에서 10.1% 아래, 저점에서 12.4% 위
        ("88", "10.0% above 52-week low"),  # (88 − 80) / 80, 고점에서 12.0% 아래
        ("88.08", "No additional price highlights"),  # 저점에서 10.1% 위, 고점에서 11.9% 아래
    ],
    ids=["고점_10.0%", "고점_10.1%", "저점_10.0%", "저점_10.1%"],
)
def test_52주_고점·저점_거리는_10_0퍼센트까지_가격_사실이다(last_close, text):
    assert price_fact_line(week52(last_close), CHECKED).text == text


@pytest.mark.parametrize(
    "closes, text",
    [
        (["101", "100", "101", "102"], "No additional price highlights"),
        (["101", "100", "101", "102", "103"], "Up 3 days in a row"),
        (["99", "100", "99", "98"], "No additional price highlights"),
        (["99", "100", "99", "98", "97"], "Down 3 days in a row"),
    ],
    ids=["상승_2일", "상승_3일", "하락_2일", "하락_3일"],
)
def test_연속_상승·하락은_3일부터_가격_사실이다(closes, text):
    bars = [ohlc(date(2026, 10, 12) + timedelta(days=i), c) for i, c in enumerate(closes)]  # 52주 이력 없음
    assert price_fact_line(bars, CHECKED).text == text


@pytest.mark.parametrize(
    "closes, days",
    [
        (["100", "101", "102", "103"], 3),
        (["103", "102", "101", "100"], -3),
        (["100", "101", "102", "102"], 0),
        (["100", "101", "102", "102.04"], 0),  # +0.039% → 0.0% 보합
        (["100", "101", "102", "102.06"], 3),  # +0.059% → 0.1% 상승
        (["100", "101", "101", "102"], 1),
    ],
    ids=["상승_3일", "하락_3일", "마지막_날_보합", "반올림_0.0은_보합", "반올림_0.1은_상승", "중간_보합에서_끊김"],
)
def test_연속_일수는_반올림해서_0_0퍼센트인_날에_끊긴다(closes, days):
    assert streak([ohlc(date(2026, 10, 12) + timedelta(days=i), c) for i, c in enumerate(closes)]) == days


TUE, FRI = date(2026, 10, 13), date(2026, 10, 16)


@pytest.mark.parametrize(
    "event, status",
    [
        (Earnings(TUE + EVENT_WINDOW, True, None), LineStatus.CHECKED_FOUND),
        (Earnings(TUE + EVENT_WINDOW + timedelta(days=1), True, None), LineStatus.CHECKED_NONE),
        (ExDividend(TUE - timedelta(days=1), Decimal("0.51")), LineStatus.CHECKED_NONE),
    ],
    ids=["기간_마지막_날", "기간_다음_날", "지난_일정"],
)
def test_일정은_거래일부터_표시_기간_끝까지만_고른다(event, status):
    assert event_line([event], TUE, CHECKED).status is status  # 어댑터가 범위를 어겨도 줄은 범위를 지킨다


def test_D_N은_달력일로_센다():
    line = event_line([Earnings(date(2026, 10, 19), True, EarningsTiming.BEFORE_OPEN)], FRI, CHECKED)
    assert line.text == "Earnings Mon 10/19 before open (D-3)"  # 거래일로 세면 D-1


def test_추정_실적일의_est는_발표_시점_뒤_D_N_앞에_온다():
    line = event_line([Earnings(date(2026, 10, 15), False, EarningsTiming.AFTER_CLOSE)], TUE, CHECKED)
    assert line.text == "Earnings Thu 10/15 after close (est.) (D-2)"


@pytest.mark.parametrize(
    "leverage, tag",
    [
        ("3.00", "3x · resets daily"),
        ("-3.00", "−3x inverse · resets daily"),  # U+2212 진짜 마이너스
        ("1.50", "1.5x · resets daily"),
        ("-1.00", "−1x inverse · resets daily"),
        ("10.00", "10x · resets daily"),  # 1E+1 표기가 나오지 않는다
        (None, None),
    ],
    ids=["3배", "인버스_3배", "1.5배", "인버스_1배", "10배", "레버리지_상품_아님"],
)
def test_레버리지_태그는_배율과_방향에서_만든다(leverage, tag):
    assert leverage_tag(None if leverage is None else Decimal(leverage)) == tag


@pytest.mark.parametrize(
    "amount, shown",
    [
        ("0.70", "$0.70"),
        ("1.5", "$1.50"),
        ("0.51", "$0.51"),
        ("0.2475", "$0.2475"),
        ("0.00456", "$0.0046"),
        ("0.00015", "$0.0002"),  # 넷째 자리 반올림은 0에서 먼 쪽
        ("0.00025", "$0.0003"),  # 짝수 쪽 반올림(ROUND_HALF_EVEN)이면 $0.0002
        ("0.99995", "$1.00"),
        ("0.24741", "$0.2474"),  # 항상 올림(ROUND_UP·ROUND_CEILING)이면 $0.2475
        ("0.24745", "$0.2475"),  # 0에서 먼 쪽. 짝수 쪽이면 $0.2474
    ],
)
def test_주당_금액은_센트까지_쓰고_발표값을_반올림해_없애지_않는다(amount, shown):
    assert format_per_share(Decimal(amount)) == shown


@pytest.mark.parametrize(
    "amount, shown",
    [("0.0001", "$0.0001"), ("0.000099", "<$0.0001"), ("0.00009999", "<$0.0001"), ("0.00005", "<$0.0001")],
    ids=["정확히_0.0001", "0.0001_바로_아래", "0.0001에_더_가까운_아래", "반올림하면_0.0001이_되는_값"],
)
def test_주당_금액이_0보다_크고_0_0001달러_미만이면_반올림하지_않고_작다고_표시한다(amount, shown):
    assert format_per_share(Decimal(amount)) == shown


@pytest.mark.parametrize(
    "amount, shown",
    [
        (94_000_000_000, "$94B"),
        (94_300_000_000, "$94.3B"),
        (1_200_000, "$1.2M"),
        (1_250_000, "$1.3M"),
        (999_940_000, "$999.9M"),
        (999_950_000, "$1B"),  # 반올림하면 1000M → 다음 단위
        (1_200_000_000_000, "$1.2T"),
        (950_000, "$950K"),
        (950, "$950"),
    ],
)
def test_큰_금액은_단위로_축약하고_소수_첫째_자리까지_쓴다(amount, shown):
    assert format_usd(Decimal(amount)) == shown


@pytest.mark.parametrize("fmt, amount", [(format_usd, "-1"), (format_per_share, "0"), (format_per_share, "-0.5")])
def test_음수_금액이나_0_이하_주당_금액은_표기하지_않는다(fmt, amount):
    with pytest.raises(ValueError):
        fmt(Decimal(amount))
