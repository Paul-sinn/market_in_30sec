"""입구 1: 시나리오 → MorningPipeline.run → 저장소 읽기 함수로 확인."""

import dataclasses
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from m30.adapters import Source
from m30.adapters.events import Earnings, EarningsTiming
from m30.adapters.holdings import Holding
from m30.adapters.fake import (
    FailurePlan,
    FakeEventSource,
    FakeFilingSource,
    FakeHoldingsSource,
    FakeIndicatorSource,
    FakeLLM,
    FakeMarketNewsSource,
    FakePriceSource,
    Scenario,
    load_scenario,
)
from m30.adapters.prices import DailyBar
from m30.config import ET
from m30.models import CardStatus, Coverage, FundHoldings, HoldStage, LineStatus
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.llm import LLMCallLimitReached
from m30.pipeline import morning
from m30.pipeline.morning import MorningPipeline, TickerError, run_failed
from m30.pipeline.newsline import NEWSLINE_SYSTEM
from m30.trading_day import is_trading_day
from conftest import SCENARIOS
from test_collect_classify import AAPL, LINE, MSFT, CrashingPrices, Killed, filing, label, reply, scenario
from test_collect_classify import run as run_with  # 출처를 바꿔 넣는 run: summary·가짜 출처를 돌려준다
from test_my_stock import add, set_plan

TUE = date(2026, 10, 13)
THU = date(2026, 10, 15)
FRI = date(2026, 10, 16)
THANKSGIVING = date(2026, 11, 26)  # NYSE 휴장
THANKSGIVING_FRI = date(2026, 11, 27)  # 조기 마감일(거래일). 직전 거래일 11-25


def run(store, scenario, day=FRI):
    """scenario: 시나리오 JSON 경로 또는 코드로 만든 Scenario."""
    if not isinstance(scenario, Scenario):
        scenario = load_scenario(scenario)
    store.upsert_coverage(scenario.coverage)
    store.add_default_tickers(day, [c.ticker for c in scenario.coverage])  # 유저 없음 → 시나리오 커버 범위 전체가 대상
    return MorningPipeline(
        prices=FakePriceSource(scenario),
        events=FakeEventSource(scenario),
        filings=FakeFilingSource(scenario),
        indicators=FakeIndicatorSource(scenario),
        holdings=FakeHoldingsSource(scenario),
        market_news=FakeMarketNewsSource(scenario),
        llm=FakeLLM(scenario),
        store=store,
        sleep=lambda seconds: None,  # 실제로 기다리지 않는다
    ).run(day)


def pipeline_runs(admin):
    """실행 기록 (거래일, 끝났는지), 시작 순."""
    return admin.execute("select trading_day, finished_at is not null from public.pipeline_run order by id").fetchall()


def cards_by_ticker(store, day):
    return {c.ticker: c for c in store.list_cards(day)}


def bar(day, close, **changes):
    """O=H=L=C=close, 분할 조정가인 봉. changes로 open·high·low·adjusted 등을 바꾼다."""
    c = Decimal(str(close))
    return DailyBar(**({"day": date.fromisoformat(day), "open": c, "high": c, "low": c, "close": c,
                        "volume": 1000, "adjusted": True} | changes))


def aapl_only(bars):
    return Scenario(coverage=[Coverage("AAPL", "Apple Inc.")], prices={"AAPL": bars})


def test_시나리오로_실행하면_종목·거래일마다_카드가_하나_저장된다(store, first_card):
    summary = run(store, first_card)

    cards = store.list_cards(FRI)
    assert [(c.ticker, c.trading_day) for c in cards] == [("AAPL", FRI), ("MSFT", FRI), ("NVDA", FRI)]
    assert {c.ticker: c.change_pct for c in cards} == {"AAPL": Decimal("1.3"), "MSFT": Decimal("-1.3"), "NVDA": None}
    assert all(c.status is CardStatus.NORMAL for c in cards)  # 공시 출처가 없는 종목(CIK 없음)은 첫 번째 줄이 문구로 채워진다
    assert summary.cards_saved == 3


def test_같은_거래일로_다시_실행해도_카드가_중복되지_않고_덮어쓴다(store, first_card, tmp_path):
    run(store, first_card)
    run(store, first_card)
    assert len(store.list_cards(FRI)) == 3

    changed = tmp_path / "aapl_204.json"
    changed.write_text(first_card.read_text().replace('"high": 203.00, "low": 200.10, "close": 202.50',
                                                      '"high": 204.00, "low": 200.10, "close": 204.00'))  # 고가도: OHLC 순서
    run(store, changed)

    cards = store.list_cards(FRI)
    assert len(cards) == 3
    assert cards[0].ticker == "AAPL" and cards[0].change_pct == Decimal("2.0")


def test_발행_중단한_카드는_같은_거래일을_다시_돌려도_중단이_유지되고_내용만_다시_저장된다(store, admin, first_card, tmp_path):
    run(store, first_card)
    admin.execute("update public.stock_card set publish_suspended = true where ticker = 'AAPL'")  # 대시보드에서 켜는 것과 같은 SQL
    changed = tmp_path / "aapl_204.json"
    changed.write_text(first_card.read_text().replace('"high": 203.00, "low": 200.10, "close": 202.50',
                                                      '"high": 204.00, "low": 200.10, "close": 204.00'))
    run(store, changed)

    assert cards_by_ticker(store, FRI)["AAPL"].change_pct == Decimal("2.0")
    assert admin.execute("select ticker from public.stock_card where publish_suspended order by ticker").fetchall() == [("AAPL",)]


def test_봉이_모자라면_등락률은_지연이고_없음으로_저장되지_않는다(store, first_card):
    summary = run(store, first_card)

    nvda = {c.ticker: c for c in store.list_cards(FRI)}["NVDA"]
    assert nvda.change_pct is None
    assert nvda.change_status is LineStatus.DELAYED
    assert (nvda.news_line.text, nvda.news_line.status) == ("Not covered yet", LineStatus.UNSUPPORTED)  # CIK 없음
    assert (nvda.event_line.text, nvda.event_line.status) == ("Not covered yet", LineStatus.UNSUPPORTED)  # 시나리오에 일정 없음
    assert nvda.price_fact_line.status is LineStatus.DELAYED  # 사실 없음(checked_none)이 아니다
    assert summary.change_delayed == ("NVDA",)


def test_봉이_여러_개여도_전일_종가는_마지막_봉_바로_앞_봉의_종가다(store, lookback_window):
    run(store, lookback_window)

    aapl = {c.ticker: c for c in store.list_cards(FRI)}["AAPL"]
    assert aapl.change_pct == Decimal("1.3")  # 10-14 200.00 → 10-15 202.50. 첫 봉(10-09 100.00) 기준이면 102.5


def test_거래일_당일과_그_뒤의_봉은_등락률_계산에_쓰지_않는다(store, lookback_window):
    run(store, lookback_window)

    msft = {c.ticker: c for c in store.list_cards(FRI)}["MSFT"]
    assert msft.change_pct == Decimal("-1.3")  # 10-14 300.00 → 10-15 296.25. 당일 봉(10-16 310.00)을 쓰면 4.6


def test_카드_시각은_동부시간_tz_aware로_돌려준다(store, first_card):
    run(store, first_card)

    for card in store.list_cards(FRI):
        assert card.updated_at.utcoffset() is not None
        assert card.updated_at.tzinfo == ET


def test_거래일_자리에_시각을_넘기면_실행하지_않고_카드도_저장하지_않는다(store, first_card):
    with pytest.raises(TypeError, match="trading_day"):  # 어댑터의 우연한 비교 오류가 아니라 입구에서 거부
        run(store, first_card, day=datetime(2026, 10, 16, 7, 30, tzinfo=ET))
    assert store.list_cards(FRI) == []


def test_휴장일이면_실행하지_않고_카드도_실행_기록도_남기지_않는다(store, admin, first_card):
    with pytest.raises(ValueError, match="trading day"):
        run(store, first_card, day=THANKSGIVING)
    assert store.list_cards(THANKSGIVING) == []
    assert pipeline_runs(admin) == []


def test_줄마다_데이터_상태·확인_시각·출처_범위가_저장된다(store, first_card, full_card):
    store.upsert_coverage(load_scenario(first_card).coverage)
    store.upsert_card(full_card)

    [card] = store.list_cards(FRI)
    assert card.status is CardStatus.NORMAL
    assert card.news_line == full_card.news_line
    assert card.event_line == full_card.event_line
    assert card.price_fact_line == full_card.price_fact_line
    assert card.news_line.checked_at.tzinfo == ET


EVENT_SCOPE = "Earnings and dividend calendar"


@pytest.mark.parametrize(
    "ticker, text, status",
    [
        ("AAPL", "Earnings Thu 10/15 after close (D-2)", LineStatus.CHECKED_FOUND),  # 11/09 배당보다 실적이 가깝다
        ("MSFT", "Earnings Thu 10/15 (est.) (D-2)", LineStatus.CHECKED_FOUND),
        ("KO", "Ex-dividend 10/14 · $0.51/share", LineStatus.CHECKED_FOUND),
        ("XOM", "Earnings Fri 10/16 after close (D-3)", LineStatus.CHECKED_FOUND),  # 시나리오엔 배당이 먼저 적혀 있다
        ("JPM", "Earnings Tue 10/13 before open (D-0)", LineStatus.CHECKED_FOUND),
        ("PFE", "No confirmed events found", LineStatus.CHECKED_NONE),
        ("NVDA", "Update delayed", LineStatus.DELAYED),
        ("SPY", "Not covered yet", LineStatus.UNSUPPORTED),
    ],
    ids=["확정_실적", "추정_실적", "배당이_더_가까움", "같은_날은_실적_먼저", "D-0", "확인함·없음", "출처_실패는_지연", "미지원"],
)
def test_두_번째_줄은_가장_가까운_일정_템플릿이나_데이터_상태_문구로_저장된다(store, events_and_tags, ticker, text, status):
    run(store, events_and_tags, TUE)

    line = cards_by_ticker(store, TUE)[ticker].event_line
    assert (line.text, line.status) == (text, status)
    assert line.source_scope == (None if status is LineStatus.UNSUPPORTED else EVENT_SCOPE)
    assert line.checked_at.tzinfo == ET


def test_0_0001달러_미만_배당은_지연하지_않고_작다고_표시하며_원래_금액은_바꾸지_않는다(store, tmp_path):
    path = tmp_path / "tiny_dividend.json"
    path.write_text('{"coverage": [{"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust"}], "prices": {},'
                    ' "events": {"SPY": [{"kind": "ex_dividend", "day": "2026-10-14", "amount": 0.00005}]}}')
    scenario = load_scenario(path)
    run(store, scenario, TUE)

    line = cards_by_ticker(store, TUE)["SPY"].event_line
    assert (line.text, line.status) == ("Ex-dividend 10/14 · <$0.0001/share", LineStatus.CHECKED_FOUND)
    assert scenario.events["SPY"][0].amount == Decimal("0.00005")  # 0.0001로 올리거나 0으로 바꾸지 않는다


def aapl_events(*events):
    return Scenario(coverage=[Coverage("AAPL", "Apple Inc.")], prices={}, events={"AAPL": list(events)})


def test_100일_뒤_실적도_두_번째_줄에_D_100으로_나온다(store):
    run(store, aapl_events(Earnings(date(2027, 1, 21), True, None)), TUE)  # 표시 기간 제한 없음(U1 = C)

    assert cards_by_ticker(store, TUE)["AAPL"].event_line.text == "Earnings Thu 1/21 (D-100)"


def test_같은_날_실적이_추정과_확정_둘이면_확정을_보여준다(store):
    run(store, aapl_events(Earnings(THU, False, None), Earnings(THU, True, EarningsTiming.AFTER_CLOSE)), TUE)

    assert cards_by_ticker(store, TUE)["AAPL"].event_line.text == "Earnings Thu 10/15 after close (D-2)"


@pytest.mark.parametrize("amount", ["0", "-0.26"])
def test_배당_금액이_0_이하인_시나리오는_읽을_때_거부하고_카드를_저장하지_않는다(store, tmp_path, amount):
    path = tmp_path / "bad_dividend.json"
    path.write_text('{"coverage": [{"ticker": "AAPL", "name": "Apple Inc."}, {"ticker": "KO", "name": "The Coca-Cola Company"}],'
                    ' "prices": {}, "events": {"AAPL": [],'
                    f' "KO": [{{"kind": "ex_dividend", "day": "2026-10-14", "amount": {amount}}}]}}}}')
    with pytest.raises(ValueError, match="bad_dividend.json: KO ex_dividend key 'amount'"):  # 실행 중 표기 함수가 아니라 로더가 거부
        run(store, path, TUE)
    assert store.list_cards(TUE) == []


def test_레버리지·인버스_ETF_카드에는_배율에서_만든_태그가_붙는다(store, events_and_tags):
    run(store, events_and_tags, TUE)

    cards = cards_by_ticker(store, TUE)
    assert cards["TQQQ"].leverage_tag == "3x · resets daily"
    assert cards["SQQQ"].leverage_tag == "−3x inverse · resets daily"  # U+2212 진짜 마이너스
    assert cards["AAPL"].leverage_tag is None


def test_커버_범위의_배율을_고쳐_다시_실행하면_고친_배율로_태그를_만든다(store):
    for leverage in ("3", "-3"):
        run(store, Scenario(coverage=[Coverage("TQQQ", "ProShares UltraPro QQQ", Decimal(leverage))], prices={}), TUE)

    [card] = store.list_cards(TUE)
    assert card.leverage_tag == "−3x inverse · resets daily"


def test_봉이_직전_거래일이_아니면_이전_카드_값을_다시_쓰지_않는다(store):
    scenario = aapl_only([bar("2026-10-13", 100), bar("2026-10-14", 101)])
    run(store, scenario, THU)
    run(store, scenario, FRI)  # 10-15 봉이 아직 없다

    [thu] = store.list_cards(THU)
    [fri] = store.list_cards(FRI)
    assert thu.change_pct == Decimal("1.0")  # 금요일 실행 뒤에 읽어도 그대로
    assert (fri.change_pct, fri.change_status) == (None, LineStatus.DELAYED)


PRICE_SCOPE = "Daily prices"


@pytest.mark.parametrize(
    "bars",
    [
        [bar("2026-10-13", 100), bar("2026-10-14", 101)],
        [bar("2026-10-13", 100), bar("2026-10-15", 101)],
        [bar("2026-10-14", 100, adjusted=False), bar("2026-10-15", 101, adjusted=False)],
        [bar("2026-10-14", 100, adjusted=False), bar("2026-10-15", 101)],
        [bar("2026-10-14", 0), bar("2026-10-15", 101)],
        [bar("2026-10-14", 100), bar("2026-10-15", 101, open=Decimal(0))],
        [bar("2026-10-14", 100), bar("2026-10-15", 101, high=Decimal(0))],
        [bar("2026-10-14", 100), bar("2026-10-15", 101, low=Decimal(0))],
        [bar(f"2026-{d}", c) for d, c in (("10-07", 100), ("10-08", 101), ("10-12", 102), ("10-13", 103), ("10-14", 104),
                                          ("10-15", 105))],  # 10-09(거래일) 봉 없음. 믿으면 Up 5 days in a row
    ],
    ids=["봉_날짜가_직전_거래일_아님", "전일_종가_누락", "조정가_아님", "앞_봉만_조정가_아님", "전일_종가_0", "시가_0", "고가_0",
         "저가_0", "중간_거래일_봉_누락"],
)
def test_봉을_믿을_수_없으면_등락률과_세_번째_줄이_지연이고_없음이_아니다(store, bars):
    summary = run(store, aapl_only(bars), FRI)

    [card] = store.list_cards(FRI)
    assert (card.change_pct, card.change_status) == (None, LineStatus.DELAYED)
    line = card.price_fact_line
    assert (line.text, line.status, line.source_scope) == ("Update delayed", LineStatus.DELAYED, PRICE_SCOPE)
    assert summary.change_delayed == ("AAPL",)


@pytest.mark.parametrize(
    "close, change",
    [("1000.999", Decimal("99999.9")), ("1000.9995", None)],  # (1000.9995 − 1) / 1 = 99,999.95% → 100,000.0%
    ids=["DB_범위_끝", "반올림하면_DB_범위_밖"],
)
def test_하루_등락률은_DB_범위_끝까지_저장하고_넘으면_그_종목만_지연이다(store, close, change):
    summary = run(store, aapl_only([bar("2026-10-14", 1), bar("2026-10-15", close)]), FRI)  # 저장 오류로 멈추지 않는다

    [card] = store.list_cards(FRI)
    assert card.change_pct == change
    assert card.price_fact_line.status is (LineStatus.DELAYED if change is None else LineStatus.CHECKED_NONE)
    assert summary.change_delayed == (() if change else ("AAPL",))


def closes(*day_close):
    return [bar(f"2026-{d}", c) for d, c in day_close]


def year(*changed):
    """2025-10-10~2026-10-15 거래일 봉 전부 O=H=L=C=100. changed 봉은 같은 날짜 봉을 바꾼다."""
    by_day = {b.day: b for b in changed}
    first, last = date(2025, 10, 10), date(2026, 10, 15)
    days = (first + timedelta(days=i) for i in range((last - first).days + 1))
    return [by_day.get(d, bar(d.isoformat(), 100)) for d in days if is_trading_day(d)]


LOW_80 = bar("2026-03-02", 80)  # 52주 저점을 멀리 둔다(저점 = 종가면 At 52-week low가 먼저 나온다)
HIGH_120 = bar("2026-03-02", 120)  # 52주 고점을 멀리 둔다(고점 대비 16.7% 이상 아래)
AT_HIGH = year(LOW_80, bar("2026-10-15", 110, open=Decimal(100), low=Decimal(100)))
HIGH_JUNE = bar("2026-06-01", 120)  # LOW_80과 함께: 마지막 종가 100은 고점에서 16.7% 아래, 저점에서 25.0% 위, 마지막 날 보합


def test_가격_데이터가_정상인데_사실이_없으면_No_additional_price_highlights이고_데이터가_빠지거나_틀리면_Update_delayed다(store):
    quiet = year(LOW_80, HIGH_JUNE)  # 휴장일(2025-11-27 … 2026-09-07)을 건너뛴 1년 봉
    prices = {
        "QUIET": quiet,
        "UNADJ": year(LOW_80, HIGH_JUNE, bar("2026-10-15", 100, adjusted=False)),
        "STALE": [b for b in quiet if b.day != date(2026, 10, 15)],  # 마지막 봉이 직전 거래일이 아님
        "NOPREV": [b for b in quiet if b.day != date(2026, 10, 14)],  # 전일 종가 누락
        "ZERO": year(LOW_80, HIGH_JUNE, bar("2026-10-14", 0)),
        "HOLIDAY": sorted([*quiet, bar("2026-09-07", 100)], key=lambda b: b.day),  # 노동절(휴장) 날짜 봉 = 데이터 오류
    }
    run(store, Scenario(coverage=[Coverage(t, t) for t in prices], prices=prices), FRI)

    lines = {t: c.price_fact_line for t, c in cards_by_ticker(store, FRI).items()}
    assert {t: (line.text, line.status) for t, line in lines.items()} == {
        "QUIET": ("No additional price highlights", LineStatus.CHECKED_NONE),
        "UNADJ": ("Update delayed", LineStatus.DELAYED),
        "STALE": ("Update delayed", LineStatus.DELAYED),
        "NOPREV": ("Update delayed", LineStatus.DELAYED),
        "ZERO": ("Update delayed", LineStatus.DELAYED),
        "HOLIDAY": ("Update delayed", LineStatus.DELAYED),
    }
    assert {line.source_scope for line in lines.values()} == {PRICE_SCOPE}  # 줄을 숨기지 않는다


@pytest.mark.parametrize(
    "bars, text",
    [
        (closes(("10-08", 100), ("10-09", 101), ("10-12", 102), ("10-13", 103), ("10-14", 104), ("10-15", 105)),
         "Up 5 days in a row"),
        (closes(("10-08", 110), ("10-09", 109), ("10-12", 108), ("10-13", 107), ("10-14", 106), ("10-15", 105)),
         "Down 5 days in a row"),
        (AT_HIGH, "At 52-week high"),
        (year(LOW_80, bar("2026-06-01", 102)), "2.0% below 52-week high"),  # (102 − 100) / 102 = 1.96%
        (year(LOW_80, bar("2026-10-15", 100, high=Decimal(105))), "4.8% below 52-week high"),  # (105 − 100) / 105
        (year(HIGH_120, bar("2026-10-15", 90, open=Decimal(100), high=Decimal(100))), "At 52-week low"),
        (year(HIGH_120, bar("2026-06-01", 98)), "2.0% above 52-week low"),  # (100 − 98) / 98 = 2.04%
        (year(HIGH_120, bar("2026-10-15", 100, low=Decimal(95))), "5.3% above 52-week low"),  # (100 − 95) / 95 = 5.26%
    ],
    ids=["연속_상승", "연속_하락", "52주_고점과_같음", "52주_고점_근처", "장중_고가_기준", "52주_저점과_같음", "52주_저점_근처",
         "장중_저가_기준"],
)
def test_세_번째_줄은_가격_사실_하나로_저장된다(store, bars, text):
    run(store, aapl_only(bars), FRI)

    [card] = store.list_cards(FRI)
    line = card.price_fact_line
    assert (line.text, line.status, line.source_scope) == (text, LineStatus.CHECKED_FOUND, PRICE_SCOPE)


def test_조기_마감일_종가는_정상_종가이고_휴장일에는_봉이_없어도_지연이_아니다(store):
    scenario = aapl_only(closes(("11-24", 100), ("11-25", 102), ("11-27", 107.1)))  # 11-26 추수감사절 휴장, 11-27 13:00 조기 마감
    run(store, scenario, THANKSGIVING_FRI)
    run(store, scenario, date(2026, 11, 30))

    [fri] = store.list_cards(THANKSGIVING_FRI)
    [mon] = store.list_cards(date(2026, 11, 30))
    assert (fri.change_pct, fri.change_status, fri.previous_trading_day) == (Decimal("2.0"), LineStatus.CHECKED_FOUND,
                                                                            date(2026, 11, 25))
    assert (mon.change_pct, mon.change_status, mon.previous_trading_day) == (Decimal("5.0"), LineStatus.CHECKED_FOUND,
                                                                            date(2026, 11, 27))  # (107.1 − 102) / 102


def test_카드에는_등락률이_지연이어도_다루는_종가_날짜인_직전_거래일이_저장된다(store, first_card):
    run(store, first_card)

    cards = cards_by_ticker(store, FRI)
    assert cards["NVDA"].change_status is LineStatus.DELAYED
    assert {t: c.previous_trading_day for t, c in cards.items()} == {"AAPL": THU, "MSFT": THU, "NVDA": THU}


@pytest.mark.parametrize(
    "high_day, text",
    [("2025-10-16", "At 52-week high"), ("2025-10-17", "No additional price highlights")],
    ids=["마지막_봉_52주_전_날은_창_밖", "그다음_날은_창_안"],  # 창 안이면 고점 120: 16.7% 아래, 저점 80에서 25.0% 위
)
def test_52주보다_오래된_고점은_52주_고점에_넣지_않는다(store, high_day, text):
    run(store, aapl_only(year(LOW_80, bar(high_day, 120))), FRI)  # 마지막 봉 2026-10-15 − 52주 = 2025-10-16

    [card] = store.list_cards(FRI)
    assert card.price_fact_line.text == text


def test_보합일에서_연속_일수가_끊긴다(store):
    bars = closes(("10-07", 110), ("10-08", 109), ("10-09", 108), ("10-12", 107), ("10-13", 107), ("10-14", 106),
                  ("10-15", 105))  # 10-13 보합을 건너뛰면 하락 5일
    run(store, aapl_only(bars), FRI)

    [card] = store.list_cards(FRI)
    assert (card.price_fact_line.text, card.price_fact_line.status) == ("No additional price highlights", LineStatus.CHECKED_NONE)


def test_상장_1년_미만이면_52주_사실을_쓰지_않는다(store):
    run(store, aapl_only([b for b in AT_HIGH if b.day >= date(2025, 10, 17)]), FRI)  # 첫 봉이 10-15 − 52주(2025-10-16)보다 뒤

    [card] = store.list_cards(FRI)
    assert (card.price_fact_line.text, card.price_fact_line.status) == ("No additional price highlights", LineStatus.CHECKED_NONE)


UP_5 = [bar(f"2026-{d}", c) for d, c in (("10-09", 101), ("10-12", 102), ("10-13", 103), ("10-14", 104), ("10-15", 105))]


@pytest.mark.parametrize(
    "bars, text",
    [
        (year(LOW_80, *UP_5), "At 52-week high"),  # U5 = A: 같음 → 연속. B면 Up 5 days in a row
        (year(LOW_80, bar("2026-06-01", 107), *UP_5), "Up 5 days in a row"),  # 연속 → 근처. C면 1.9% below 52-week high
    ],
    ids=["고점과_같음_대_연속", "고점_근처_대_연속"],
)
def test_가격_사실_후보가_여럿이면_정해진_우선순위로_하나만_고른다(store, bars, text):
    run(store, aapl_only(bars), FRI)

    [card] = store.list_cards(FRI)
    assert card.price_fact_line.text == text


def test_생성_대상은_활성_종목과_기본_종목의_합집합이다(store, admin, make_user):
    ciks = {"AAPL": "0000320193", "MSFT": "0000789019", "NVDA": "0001045810", "KO": "0000021344", "PFE": "0000078003"}
    store.upsert_coverage([Coverage(t, t, cik=cik) for t, cik in ciks.items()])
    store.add_default_tickers(FRI, ["AAPL", "MSFT"])  # 2026Q4
    store.add_default_tickers(date(2026, 9, 30), ["PFE"])  # 2026Q3: 다른 분기
    free, downgraded = make_user("free"), make_user("plus")
    for uid, tickers in ((free, ["MSFT", "NVDA"]), (downgraded, ["AAPL", "MSFT", "NVDA", "KO"])):
        for ticker in tickers:
            add(admin, uid, ticker)
    set_plan(admin, downgraded, "free")  # KO만 잠김 = 잠긴 것만 있는 종목
    # 기본 종목을 손으로 정하려고 run 도우미(시나리오 커버 범위 전체 = 기본 종목)를 쓰지 않는다
    scenario = Scenario(coverage=[], prices={})
    filings = FakeFilingSource(scenario)

    summary = MorningPipeline(
        prices=FakePriceSource(scenario),
        events=FakeEventSource(scenario),
        filings=filings,
        indicators=FakeIndicatorSource(scenario),
        holdings=FakeHoldingsSource(scenario),
        market_news=FakeMarketNewsSource(scenario),
        llm=FakeLLM(scenario),
        store=store,
        sleep=lambda seconds: None,
    ).run(FRI)

    assert [c.ticker for c in store.list_cards(FRI)] == ["AAPL", "MSFT", "NVDA"]  # KO(잠긴 것만)·PFE(다른 분기) 없음
    assert summary.cards_saved == 3  # MSFT는 셋 다에 있어도 하나
    assert sorted(filings.calls) == [ciks["AAPL"], ciks["MSFT"], ciks["NVDA"]]  # 수집도 대상만
    assert summary.llm_call_limit == 3 * 4 + 0  # 대상 3종목 × 4 + 묶음 0


# ETF 카드 라이트 버전(#10). 시나리오 etf_lite.json: AVGO는 커버 범위에만 있다(QQQ 편입 종목, 기본 종목 아님)
ETF_DEFAULTS = ("AAPL", "MSFT", "QQQ", "SPY", "TQQQ")


def run_etf(store, scenario, day=FRI, defaults=ETF_DEFAULTS, **replaced):
    """기본 종목 = defaults. replaced: 바꿔 넣을 출처(예: prices=…). 돌려주는 값: summary, 가짜 출처 6개, 티커 → 저장된 카드."""
    if not isinstance(scenario, Scenario):
        scenario = load_scenario(scenario)
    store.upsert_coverage(scenario.coverage)
    store.add_default_tickers(day, defaults)
    fakes = {
        "prices": FakePriceSource(scenario),
        "events": FakeEventSource(scenario),
        "filings": FakeFilingSource(scenario),
        "indicators": FakeIndicatorSource(scenario),
        "holdings": FakeHoldingsSource(scenario),
        "market_news": FakeMarketNewsSource(scenario),
        "llm": FakeLLM(scenario),
    } | replaced
    summary = MorningPipeline(**fakes, store=store, sleep=lambda seconds: None).run(day)
    return SimpleNamespace(summary=summary, cards=cards_by_ticker(store, day), **fakes)


def test_가짜_N_PORT_보고로_ETF마다_상위_편입_종목을_찾고_보고를_저장한다(store, etf_lite):
    ran = run_etf(store, etf_lite)

    qqq = FundHoldings(LineStatus.CHECKED_FOUND, ("AVGO", "MSFT"), 2, 0)  # AVGO는 생성 대상이 아니어도 편입 종목
    assert ran.summary.funds == {
        "QQQ": qqq,
        "SPY": FundHoldings(LineStatus.CHECKED_FOUND, ("AAPL", "MSFT"), 2, 2),  # NVIDIA(커버 범위 밖)·Amazon(CIK 없음), 선물 제외
        "TQQQ": qqq,
    }
    spy = store.latest_holdings("SPY")
    assert (spy.accession, spy.period_end, len(spy.holdings)) == ("0000884394-26-000101", date(2026, 6, 30), 5)
    assert spy.holdings[0] == Holding("Apple Inc", "0000320193", Decimal("7.1"), "EC")
    assert store.latest_holdings("TQQQ") is None  # TQQQ는 QQQ의 보고를 쓴다


AAPL_8K, MSFT_8K, AVGO_8K = "0000320193-26-000101", "0000789019-26-000045", "0001730168-26-000012"


def news(card):
    return (card.news_line.text, card.news_line.status, card.news_line.source_scope, card.news_line_accession)


def newsline_companies(llm):
    """첫 번째 줄 초안 요청이 쓴 회사, 요청 순서대로."""
    return [json.loads(r.user.split("<news>\n", 1)[1].split("\n</news>", 1)[0])["company"]
            for r in llm.requests if r.system == NEWSLINE_SYSTEM]


def test_ETF_첫_번째_줄은_상위_편입_종목_소식_중_가장_중요한_것이고_출처와_확인_범위가_붙는다(store, etf_lite):
    ran = run_etf(store, etf_lite)

    two = "SEC filings of 2 top holdings"
    assert news(ran.cards["AAPL"]) == ("Apple reported Q4 revenue of $102.5B (SEC filing)", LineStatus.CHECKED_FOUND,
                                       "SEC filings", AAPL_8K)
    # AAPL 중요도 5 > MSFT 3. 같은 공시라 AAPL 카드와 같은 문장, +N more는 SPY 후보 수 − 1
    assert news(ran.cards["SPY"]) == ("Apple reported Q4 revenue of $102.5B +1 more (SEC filing)", LineStatus.CHECKED_FOUND,
                                      two, AAPL_8K)
    # AVGO 4 > MSFT 3. AVGO는 생성 대상이 아니라 카드가 없고, 그 공시만 초안·검수를 한 번 더 한다
    assert news(ran.cards["QQQ"]) == ("Broadcom agreed to acquire a software maker +1 more (SEC filing)",
                                      LineStatus.CHECKED_FOUND, two, AVGO_8K)
    assert "AVGO" not in ran.cards
    assert ("AVGO", AVGO_8K) in {(r.ticker, r.accession) for r in store.list_classifications(FRI)}  # 편입 종목 공시도 분류는 저장
    assert newsline_companies(ran.llm) == ["Apple Inc.", "Broadcom Inc."]  # SPY는 AAPL 초안을, TQQQ는 QQQ 초안을 다시 쓴다
    assert len(ran.llm.requests) == 5  # 분류 1 + 초안 2 + 판정 2 (MSFT는 본문이 없어 부르지 않는다)
    assert ran.summary.llm_call_limit == 5 * 4 + 1  # 생성 대상 5 × 4 + 분류 묶음 1. 편입 종목 공시는 묶음에 들어 있다


CLASSIFY_ETF = {"items": [{"id": 1, "ticker": "MSFT", "kind": "leadership", "importance": 3, "opinion": False},
                          {"id": 2, "ticker": "AAPL", "kind": "earnings", "importance": 5, "opinion": False}]}
APPLE_LINE, FACT = {"sentence": "Apple reported Q4 revenue of $102.5B"}, {"label": "fact"}


def etf_replies(*replies):
    """etf_lite에서 LLM 응답만 바꾼다. replies: dict(JSON으로) 또는 str(그대로)."""
    return dataclasses.replace(load_scenario(SCENARIOS / "etf_lite.json"),
                               llm_replies=[r if isinstance(r, str) else json.dumps(r) for r in replies])


@pytest.mark.parametrize("defaults", [("AAPL", "MSFT"), ("AAPL", "MSFT", "SPY")], ids=["ETF_없음", "SPY_있음"])
def test_ETF_1등_공시가_생성_대상_종목의_1등이면_LLM을_더_부르지_않는다(store, defaults):
    ran = run_etf(store, etf_replies(CLASSIFY_ETF, APPLE_LINE, FACT), defaults=defaults)

    assert len(ran.llm.requests) == 3  # 분류 1 + Apple 초안 1 + 판정 1. AVGO는 QQQ가 대상이 아니라 받지 않는다
    assert ran.cards["AAPL"].news_line.text == "Apple reported Q4 revenue of $102.5B (SEC filing)"


def test_ETF_1등_초안이_검수에_두_번_걸리면_편입_회사_이름의_대체_줄이_들어가고_ETF_카드에도_보류함_행이_생긴다(store, etf_lite):
    classify = load_scenario(etf_lite).llm_replies[0]
    apple, broadcom = {"sentence": "Apple reported Q4 revenue of $999B"}, {"sentence": "Broadcom agreed to pay $5B"}  # 원본에 없는 숫자
    ran = run_etf(store, etf_replies(classify, apple, broadcom, apple, broadcom))

    lines = {t: c.news_line.text for t, c in ran.cards.items()}
    assert lines == {
        "AAPL": "Apple reported quarterly results (SEC filing)",
        "MSFT": "Microsoft announced a leadership update (SEC filing)",
        "QQQ": "Broadcom signed a major agreement +1 more (SEC filing)",  # 생성 대상이 아닌 AVGO의 커버 범위 이름
        "SPY": "Apple reported quarterly results +1 more (SEC filing)",
        "TQQQ": "Broadcom signed a major agreement +1 more (SEC filing)",
    }
    holds = [(h.ticker, h.accession, h.stage, h.replacement_text) for h in store.list_hold_items(FRI)]
    assert holds == [
        ("AAPL", AAPL_8K, HoldStage.NUMBERS, lines["AAPL"]),
        ("MSFT", MSFT_8K, HoldStage.DRAFT, lines["MSFT"]),  # 본문 없음
        ("QQQ", AVGO_8K, HoldStage.NUMBERS, lines["QQQ"]),
        ("SPY", AAPL_8K, HoldStage.NUMBERS, lines["SPY"]),
        ("TQQQ", AVGO_8K, HoldStage.NUMBERS, lines["TQQQ"]),
    ]
    assert len(ran.llm.requests) == 5  # 분류 1 + (Apple·Broadcom 초안 + 재생성) 4. 같은 공시는 ETF가 다시 검수하지 않는다


def test_편입_종목_공시가_없으면_ETF_첫_번째_줄은_No_new_SEC_filings_found이고_확인한_편입_회사_수를_범위로_쓴다(store, etf_lite):
    quiet = load_scenario(etf_lite)
    qqq = quiet.holdings["QQQ"]
    quiet = dataclasses.replace(quiet, filings={}, llm_replies=[],
                                holdings=quiet.holdings | {"QQQ": dataclasses.replace(qqq, holdings=qqq.holdings[:1])})  # MSFT만
    ran = run_etf(store, quiet)

    none = ("No new SEC filings found", LineStatus.CHECKED_NONE)
    assert {t: news(ran.cards[t]) for t in ("QQQ", "SPY", "TQQQ")} == {
        "QQQ": (*none, "SEC filings of 1 top holding", None),
        "SPY": (*none, "SEC filings of 2 top holdings", None),
        "TQQQ": (*none, "SEC filings of 1 top holding", None),
    }
    assert ran.llm.requests == []


def quiet_etf(**changes):
    """etf_lite에서 공시·LLM 응답을 뺀 날. changes로 필드를 바꾼다."""
    return dataclasses.replace(load_scenario(SCENARIOS / "etf_lite.json"), filings={}, llm_replies=[], **changes)


SPY_REPORT = load_scenario(SCENARIOS / "etf_lite.json").holdings["SPY"]


@pytest.mark.parametrize(
    "scenario, ticker, fund, calls",
    [
        (quiet_etf(coverage=[dataclasses.replace(c, holdings_ticker=None) for c in load_scenario(SCENARIOS / "etf_lite.json").coverage]),
         "SPY", None, []),
        (quiet_etf(holdings={}), "SPY", FundHoldings(LineStatus.UNSUPPORTED), ["QQQ", "SPY"]),
        (quiet_etf(holdings={"SPY": dataclasses.replace(SPY_REPORT, holdings=SPY_REPORT.holdings[2:])}),  # NVIDIA·Amazon·선물만
         "SPY", FundHoldings(LineStatus.UNSUPPORTED, unmatched=2), ["QQQ", "SPY"]),
        (quiet_etf(coverage=[c for c in load_scenario(SCENARIOS / "etf_lite.json").coverage if c.ticker != "QQQ"]),
         "TQQQ", FundHoldings(LineStatus.UNSUPPORTED), ["SPY"]),
    ],
    ids=["holdings_ticker_없음", "출처가_다루지_않음", "찾은_회사_없음", "편입을_읽을_ETF가_커버_범위_밖"],
)
def test_편입_데이터가_없으면_ETF_첫_번째_줄은_Not_covered_yet이다(store, scenario, ticker, fund, calls):
    ran = run_etf(store, scenario)

    assert news(ran.cards[ticker]) == ("Not covered yet", LineStatus.UNSUPPORTED, None, None)
    assert ran.summary.funds.get(ticker) == fund
    assert ran.holdings.calls == calls
    assert ran.summary.failures == ()  # 미지원은 실패가 아니다


HOLDINGS_DELAYED = ("Update delayed", LineStatus.DELAYED, "SEC filings of top holdings", None)
HOLDING_ERRORS = {  # 실패 종류 → (QQQ 호출 수, SPY도 막혔나, 실패 사유)
    "transient": (4, False, FailureReason.RETRIES_EXHAUSTED),
    "error": (1, False, FailureReason.ERROR),
    "access_denied": (1, True, FailureReason.ACCESS_DENIED),
    "rate_limited": (4, False, FailureReason.RETRIES_EXHAUSTED),
}


@pytest.mark.parametrize("error", HOLDING_ERRORS)
def test_편입_보고를_못_받고_저장분도_없으면_ETF_첫_번째_줄은_지연이고_실패가_요약에_남는다(store, error):
    ran = run_etf(store, quiet_etf(failures={(Source.HOLDINGS, "QQQ"): FailurePlan(error)}))  # QQQ가 먼저 불린다

    count, denied, reason = HOLDING_ERRORS[error]
    assert ran.holdings.calls == ["QQQ"] * count + ([] if denied else ["SPY"])  # 401·403 뒤 SPY는 부르지 않는다
    assert ran.summary.failures == tuple(SourceFailure(Source.HOLDINGS, f, reason) for f in ["QQQ", *(["SPY"] if denied else [])])
    delayed = {"QQQ", "TQQQ", *(["SPY"] if denied else [])}
    for ticker in ("QQQ", "SPY", "TQQQ"):
        assert (news(ran.cards[ticker]) == HOLDINGS_DELAYED) is (ticker in delayed), ticker
    assert ran.summary.funds["QQQ"] == ran.summary.funds["TQQQ"] == FundHoldings(LineStatus.DELAYED)
    assert news(ran.cards["AAPL"])[1] is LineStatus.CHECKED_NONE  # 종목 카드는 그대로


def test_편입_종목_CIK_하나라도_공시_수집에_실패하면_ETF_첫_번째_줄은_지연이다(store):
    ran = run_etf(store, quiet_etf(failures={(Source.SEC_FILINGS, "0000789019"): FailurePlan("error")}))  # MSFT

    delayed = ("Update delayed", LineStatus.DELAYED, "SEC filings of 2 top holdings", None)  # 편입 종목은 읽었다
    assert {t: news(ran.cards[t]) for t in ("QQQ", "SPY", "TQQQ")} == dict.fromkeys(("QQQ", "SPY", "TQQQ"), delayed)
    assert news(ran.cards["AAPL"]) == ("No new SEC filings found", LineStatus.CHECKED_NONE, "SEC filings", None)


def test_재실행에서_편입_종목_CIK_수집이_실패하면_앞_실행이_확인한_ETF_첫_번째_줄을_그대로_둔다(store, etf_lite):
    run_etf(store, etf_lite)
    before = {t: c.news_line for t, c in cards_by_ticker(store, FRI).items()}

    ran = run_etf(store, dataclasses.replace(load_scenario(etf_lite), failures={(Source.SEC_FILINGS, "0000789019"): FailurePlan("error")}))

    for ticker in ("QQQ", "SPY", "TQQQ"):  # 확인 시각까지 그대로(공시 기간은 고정이고 수집 실패는 새 정보가 아니다)
        assert ran.cards[ticker].news_line == before[ticker], ticker
    assert ran.cards["SPY"].news_line_accession == AAPL_8K


def test_같은_거래일을_다시_돌리면_저장한_편입_보고를_쓰고_출처를_부르지_않는다(store, admin, etf_lite):
    first = run_etf(store, etf_lite)
    again = run_etf(store, etf_lite)

    assert first.holdings.calls == ["QQQ", "SPY"]
    assert again.holdings.calls == []
    assert admin.execute("select fund, count(*) from public.fund_holdings group by fund order by fund").fetchall() == [
        ("QQQ", 1), ("SPY", 1)]
    assert {t: news(c) for t, c in again.cards.items()} == {t: news(c) for t, c in first.cards.items()}


@pytest.mark.parametrize("day, calls", [(date(2026, 11, 16), []), (date(2026, 11, 17), ["QQQ", "SPY"])],
                         ids=["기준일_뒤_139일", "기준일_뒤_140일"])
def test_저장한_편입_보고의_기준일에서_140일이_지난_날부터_출처를_다시_부른다(store, day, calls):
    run_etf(store, quiet_etf())  # FRI: 기준일 2026-06-30 보고 저장. 06-30 + 140일 = 11-17

    assert run_etf(store, quiet_etf(), day).holdings.calls == calls


@pytest.mark.parametrize(
    "period_end, tickers",
    [(date(2026, 3, 31), ("AAPL", "MSFT")), (date(2026, 9, 30), ("AAPL",))],
    ids=["더_오래된_보고면_저장분", "더_최근_보고면_새_보고"],
)
def test_출처가_준_보고와_저장분_중_기준일이_늦은_쪽을_쓴다(store, period_end, tickers):
    run_etf(store, quiet_etf())  # 2026-06-30 보고: AAPL·MSFT
    other = dataclasses.replace(SPY_REPORT, accession="0000884394-26-000202", period_end=period_end,
                                holdings=SPY_REPORT.holdings[:1])  # AAPL만
    ran = run_etf(store, quiet_etf(holdings={"SPY": other}), date(2026, 11, 17))

    assert ran.holdings.calls == ["QQQ", "SPY"]
    assert ran.summary.funds["SPY"].tickers == tickers


def test_편입_보고를_못_받아도_저장분이_있으면_저장분으로_ETF_줄을_만들고_실패는_요약에_남긴다(store):
    run_etf(store, quiet_etf())
    ran = run_etf(store, quiet_etf(failures={(Source.HOLDINGS, "SPY"): FailurePlan("error")}), date(2026, 11, 17))

    assert news(ran.cards["SPY"]) == ("No new SEC filings found", LineStatus.CHECKED_NONE, "SEC filings of 2 top holdings", None)
    assert ran.summary.failures == (SourceFailure(Source.HOLDINGS, "SPY", FailureReason.ERROR),)


@pytest.mark.parametrize(
    "day, line",
    [
        (date(2026, 11, 17), ("No new SEC filings found", LineStatus.CHECKED_NONE, "SEC filings of 2 top holdings", None)),
        (date(2027, 3, 29), HOLDINGS_DELAYED),  # 06-30 + 270일 = 2027-03-27
    ],
    ids=["저장분_270일_안", "저장분_270일_넘음"],
)
def test_갱신_때_출처가_다루지_않는다고_해도_저장분이_있으면_미지원이_아니라_저장분_규칙을_따른다(store, day, line):
    run_etf(store, quiet_etf())  # FRI: 기준일 2026-06-30 보고 저장
    ran = run_etf(store, quiet_etf(holdings={}), day)  # 갱신 시기: 출처 → None

    assert ran.holdings.calls == ["QQQ", "SPY"]
    assert news(ran.cards["SPY"]) == line
    assert ran.summary.failures == ()


@pytest.mark.parametrize("period_end, delayed", [("2026-01-19", False), ("2026-01-18", True)],
                         ids=["기준일_뒤_270일", "기준일_뒤_271일"])
def test_쓸_편입_보고가_기준일에서_270일을_넘으면_ETF_첫_번째_줄은_지연이다(store, period_end, delayed):
    old = dataclasses.replace(SPY_REPORT, period_end=date.fromisoformat(period_end))  # 거래일 2026-10-16
    ran = run_etf(store, quiet_etf(holdings={"SPY": old}))

    assert (news(ran.cards["SPY"]) == HOLDINGS_DELAYED) is delayed
    assert ran.summary.failures == ()


def test_ETF_두_번째_줄은_분배금_일정_템플릿이고_일정_출처가_다루지_않으면_Not_covered_yet이다(store, etf_lite):
    ran = run_etf(store, etf_lite)

    events = {t: (c.event_line.text, c.event_line.status, c.event_line.source_scope) for t, c in ran.cards.items()}
    assert events["SPY"] == ("Ex-dividend 12/19 · $1.83/share", LineStatus.CHECKED_FOUND, EVENT_SCOPE)
    assert events["QQQ"] == events["TQQQ"] == ("Not covered yet", LineStatus.UNSUPPORTED, None)  # 시나리오에 일정 키 없음


def test_레버리지_ETF는_배율_태그를_유지하고_같은_지수_ETF의_편입_소식을_쓰며_편입_보고는_한_번만_받는다(store, etf_lite):
    ran = run_etf(store, etf_lite)

    tqqq, qqq = ran.cards["TQQQ"], ran.cards["QQQ"]
    assert tqqq.leverage_tag == "3x · resets daily"
    assert qqq.leverage_tag is None
    assert news(tqqq) == news(qqq) == ("Broadcom agreed to acquire a software maker +1 more (SEC filing)",
                                       LineStatus.CHECKED_FOUND, "SEC filings of 2 top holdings", AVGO_8K)
    assert ran.holdings.calls == ["QQQ", "SPY"]  # TQQQ는 QQQ를 가리킨다: QQQ 한 번


def test_이어_하기로_건너뛴_생성_대상도_ETF_편입_종목이면_공시를_다시_받아_ETF_줄에_쓴다(store, etf_lite):
    crash = load_scenario(etf_lite)
    with pytest.raises(Killed, match="crash"):  # 카드 루프 AAPL 저장 뒤 MSFT에서 죽는다
        run_etf(store, crash, prices=CrashingPrices(FakePriceSource(crash)))
    aapl = cards_by_ticker(store, FRI)["AAPL"]
    classified = store.list_classifications(FRI)

    # 초안 순서: MSFT(본문 없음) → QQQ(AVGO 공시) → SPY(AAPL 공시)
    ran = run_etf(store, etf_replies(load_scenario(etf_lite).llm_replies[0], {"sentence": "Broadcom agreed to acquire a software maker"},
                                     APPLE_LINE, FACT, FACT))

    assert ran.summary.resumed == ("AAPL",)
    assert news(ran.cards["SPY"]) == ("Apple reported Q4 revenue of $102.5B +1 more (SEC filing)", LineStatus.CHECKED_FOUND,
                                      "SEC filings of 2 top holdings", AAPL_8K)
    assert ran.cards["AAPL"].updated_at == aapl.updated_at  # AAPL 카드는 다시 쓰지 않는다
    assert store.list_classifications(FRI) == classified  # 분류 행은 같은 값으로 교체


def test_ETF가_자기_CIK를_가져도_편입_종목을_읽을_ETF가_있으면_편입_종목_소식을_쓴다(store, etf_lite):
    trust_cik = "0000884394"
    scenario = load_scenario(etf_lite)
    scenario = dataclasses.replace(scenario, coverage=[dataclasses.replace(c, cik=trust_cik) if c.ticker == "SPY" else c
                                                       for c in scenario.coverage])
    ran = run_etf(store, scenario)

    assert news(ran.cards["SPY"])[0] == "Apple reported Q4 revenue of $102.5B +1 more (SEC filing)"
    assert trust_cik not in ran.filings.calls  # 신탁 자신의 공시는 받지 않는다


def test_재발행한_ETF_첫_번째_줄은_다시_돌려도_사람_문장이_남고_범위는_ETF_범위다(store, admin, etf_lite):
    classify = load_scenario(etf_lite).llm_replies[0]
    apple, broadcom = {"sentence": "Apple reported Q4 revenue of $999B"}, {"sentence": "Broadcom agreed to pay $5B"}
    failing = etf_replies(classify, apple, broadcom, apple, broadcom)
    run_etf(store, failing)
    human = "Apple reported quarterly revenue +1 more (SEC filing)"
    with admin.transaction():
        admin.execute("set local role service_role")
        admin.execute("update public.hold_queue set edited_text = %s, state = 'republished' where ticker = 'SPY'", (human,))
    ran = run_etf(store, failing)

    assert news(ran.cards["SPY"]) == (human, LineStatus.CHECKED_FOUND, "SEC filings of 2 top holdings", AAPL_8K)


APPLE_ROW = SPY_REPORT.holdings[0]
WEIRD_HOLDINGS = {  # 실제 어댑터가 돌려줄 수 있는 이상한 값(가짜 로더를 거치지 않게 코드로 만든다)
    "다른_ETF의_보고": {"fund": "QQQ"},
    "접수번호_형식": {"accession": "0000884394-26-1"},
    "기준일이_시각": {"period_end": datetime(2026, 6, 30, tzinfo=ET)},
    "행이_리스트": {"holdings": [APPLE_ROW]},
    "모르는_행": {"holdings": (object(),)},
    "비중_float": {"holdings": (dataclasses.replace(APPLE_ROW, pct=7.1),)},
    "비중_NaN": {"holdings": (dataclasses.replace(APPLE_ROW, pct=Decimal("NaN")),)},
    "빈_이름": {"holdings": (dataclasses.replace(APPLE_ROW, name=""),)},
    "이름_NUL": {"holdings": (dataclasses.replace(APPLE_ROW, name="Apple\x00Inc"),)},  # jsonb는 NUL을 받지 않는다
    "CIK_9자리": {"holdings": (dataclasses.replace(APPLE_ROW, cik="320193000"),)},
    "분류_NUL": {"holdings": (dataclasses.replace(APPLE_ROW, asset_category="E\x00C"),)},
    "원본_NUL": {"raw": "<edgarSubmission>\x00"},
}


@pytest.mark.parametrize("changes", WEIRD_HOLDINGS.values(), ids=WEIRD_HOLDINGS.keys())
def test_받은_편입_보고가_이상하면_저장하지_않고_그_ETF_줄만_지연이다(store, changes):
    ran = run_etf(store, quiet_etf(holdings={"SPY": dataclasses.replace(SPY_REPORT, **changes)}))  # 예외 없이 끝난다

    assert ran.summary.failures == (SourceFailure(Source.HOLDINGS, "SPY", FailureReason.INVALID_DATA),)
    assert news(ran.cards["SPY"]) == HOLDINGS_DELAYED
    assert store.latest_holdings("SPY") is None
    assert news(ran.cards["AAPL"])[1] is LineStatus.CHECKED_NONE


def cli(scenario):
    r = subprocess.run([sys.executable, "-m", "m30.pipeline", "2026-10-16", "--scenario", str(scenario)],
                       cwd=SCENARIOS.parent, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_CLI_요약은_ETF마다_편입_종목_상태와_못_찾은_회사_수만_찍는다(admin, etf_lite):
    lines = cli(etf_lite)  # CLI는 커버 범위 전체가 기본 종목: AVGO도 생성 대상(ETF 아님)

    assert "holdings: QQQ=checked_found SPY=checked_found(unmatched 2) TQQQ=checked_found" in lines
    assert not any("Apple" in line or "Broadcom" in line for line in lines)  # 공개 로그: 문장·회사 이름 없음


def test_CLI_요약은_ETF_생성_대상이_없으면_편입_종목_줄을_찍지_않는다(admin, first_card):
    assert not any(line.startswith("holdings:") for line in cli(first_card))


# 실행 기록(#17 D1): 끝난 실행마다 pipeline_run 한 행에 실패 여부와 실행 요약(코드·건수·티커만)
NVDA_NO_CIK = Coverage("NVDA", "NVIDIA Corporation")
TWO_BARS = [bar("2026-10-14", 200), bar("2026-10-15", "202.5")]  # 등락률 계산함, 가격 사실 없음


def reviewed_day(**more):
    """AAPL = 1차 통과, MSFT = 금지어로 재생성 뒤 통과, NVDA = CIK·시세 없음. LLM 6회: 분류 1묶음 → 초안 AAPL·MSFT →
    판정 AAPL → 재생성 MSFT → 판정 MSFT."""
    day = scenario(
        [AAPL, MSFT, NVDA_NO_CIK],
        [filing(1, body="Apple named a new CFO."), filing(2, cik=MSFT.cik, body="Microsoft named a new CFO.")],
        [reply(label(1), label(2, "MSFT")), LINE, json.dumps({"sentence": "Microsoft agreed to buy a startup"}), json.dumps(FACT),
         json.dumps({"sentence": "Microsoft named a new CFO"}), json.dumps(FACT)],
        **more,
    )
    return dataclasses.replace(day, prices={"AAPL": TWO_BARS, "MSFT": TWO_BARS})


def run_rows(admin):
    """실행 기록 (끝났는지, 실패 여부, 실행 요약), 시작 순."""
    return admin.execute(
        "select finished_at is not null, failed, summary from public.pipeline_run order by id").fetchall()


def statuses(checked_found=0, checked_none=0, delayed=0, unsupported=0):
    return {"checked_found": checked_found, "checked_none": checked_none, "delayed": delayed, "unsupported": unsupported}


def test_끝난_실행은_실행_기록_한_행에_단계별_건수·LLM_호출·토큰·줄_상태별_수를_남긴다(store, admin):
    run(store, reviewed_day())

    assert run_rows(admin) == [(True, False, {
        "counts": {"cards_saved": 3, "resumed": 0, "change_delayed": 1, "funds": 0, "filings": 2, "unclassified": 0,
                   "classify_batches": 1, "skipped_batches": 0, "drafts": 2, "draft_problems": 0,
                   "review_pass_first": 1, "review_pass_retry": 1, "review_replaced": 0},
        "lines": {"change": statuses(checked_found=2, delayed=1), "news": statuses(checked_found=2, unsupported=1),
                  "event": statuses(unsupported=3), "price": statuses(checked_none=2, delayed=1)},
        "failures": [], "access_denied": [], "rate_limited": [],
        # 토큰 = FakeLLM 응답 6개 × (10, 2, 5, 1)
        "llm": {"calls": 6, "limit": 13, "input_tokens": 60, "output_tokens": 12, "cache_read_tokens": 30,
                "cache_write_tokens": 6},
        # 시장 한눈에(#11): SPY·QQQ 카드 없음, 지표·소식 출처 키 없음(미지원), 소식 LLM 안 부름
        "glance": {"close": "delayed", "indicator": "unsupported", "market_news": "unsupported", "review": "-"},
    })]


def test_출처_실패가_있는_실행은_실행_기록에_실패로_남고_실패_목록에_출처·대상·사유가_있다(store, admin):
    run(store, reviewed_day(failures={(Source.SEC_FILINGS, MSFT.cik): FailurePlan("access_denied")}))

    [(finished, failed, summary)] = run_rows(admin)
    assert (finished, failed) == (True, True)
    assert summary["failures"] == [{"stage": "sec_filings", "subject": MSFT.cik, "reason": "access_denied", "error": None}]
    assert summary["access_denied"] == ["sec_filings"]
    assert summary["llm"]["calls"] == 4  # MSFT 공시를 못 받아 분류 → AAPL 초안 → AAPL 판정, 남은 응답은 쓰지 않는다


def test_죽은_실행은_실행_기록의_끝_시각·실패_여부·실행_요약이_모두_비어_있다(store, admin):
    crash = reviewed_day()
    with pytest.raises(Killed):
        run_with(store, crash, prices=CrashingPrices(FakePriceSource(crash)))  # AAPL 저장 뒤 MSFT에서 죽는다

    assert run_rows(admin) == [(False, None, None)]


# 종목 예외 격리 층 1(#17 D5): 외부 호출 하나의 예상 못 한 예외는 그 대상만 지연
class BrokenFor:
    """inner를 감싸 subject(티커)에서 error를 낸다."""

    def __init__(self, inner, subject, error):
        self._inner, self._subject, self._error = inner, subject, error

    def daily_bars(self, ticker, start, end):
        if ticker == self._subject:
            raise self._error
        return self._inner.daily_bars(ticker, start, end)


def test_시세_어댑터가_예상_못_한_예외를_내면_그_종목만_등락률과_세_번째_줄이_지연이고_실행은_끝까지_간다(store, admin):
    day = reviewed_day()

    ran = run_with(store, day, prices=BrokenFor(FakePriceSource(day), "MSFT", RuntimeError("bug")))

    cards = cards_by_ticker(store, FRI)
    assert [(t, c.change_status, c.price_fact_line.status) for t, c in cards.items()] == [
        ("AAPL", LineStatus.CHECKED_FOUND, LineStatus.CHECKED_NONE),
        ("MSFT", LineStatus.DELAYED, LineStatus.DELAYED),
        ("NVDA", LineStatus.DELAYED, LineStatus.DELAYED),  # 원래 시세 없음
    ]
    assert cards["MSFT"].news_line.status is LineStatus.CHECKED_FOUND  # 다른 줄은 그대로
    assert ran.summary.failures == (SourceFailure(Source.PRICES, "MSFT", FailureReason.UNEXPECTED, "RuntimeError"),)
    assert run_failed(ran.summary) is True
    [(finished, failed, summary)] = run_rows(admin)
    assert (finished, failed) == (True, True)
    assert summary["failures"] == [{"stage": "prices", "subject": "MSFT", "reason": "unexpected", "error": "RuntimeError"}]


class BrokenDraftLLM:
    """inner를 감싸 두 번째 요청(AAPL 첫 번째 줄 초안)에서 error를 낸다. 그 요청에는 inner 응답을 쓰지 않는다."""

    def __init__(self, inner, error):
        self._inner, self._error, self.calls = inner, error, 0

    def complete(self, request):
        self.calls += 1
        if self.calls == 2:
            raise self._error
        return self._inner.complete(request)


AAPL_8K_1 = "0000320193-26-000001"


@pytest.mark.parametrize(
    "error, rule, failures",
    [
        (KeyError("bug"), "1 draft: llm_failed", (SourceFailure(Source.LLM, AAPL_8K_1, FailureReason.UNEXPECTED, "KeyError"),)),
        (LLMCallLimitReached(), "1 draft: call_limit", ()),  # 상한은 출처 실패가 아니다: 지금 경로 그대로
    ],
    ids=["KeyError", "호출_상한"],
)
def test_LLM_어댑터가_예상_못_한_예외를_내면_그_초안만_대체_줄이고_호출_상한은_원래_경로로_간다(store, error, rule, failures):
    day = dataclasses.replace(reviewed_day(), llm_replies=[r for i, r in enumerate(reviewed_day().llm_replies) if i not in (1, 3)])

    ran = run_with(store, day, llm=BrokenDraftLLM(FakeLLM(day), error))

    aapl = cards_by_ticker(store, FRI)["AAPL"]
    assert (aapl.news_line.text, aapl.news_line.status) == ("Apple filed a company update (SEC filing)", LineStatus.CHECKED_FOUND)
    assert [(h.ticker, h.rules) for h in store.list_hold_items(FRI)] == [("AAPL", (rule,))]
    assert ran.summary.failures == failures
    assert ran.summary.reviews["MSFT"].stage is None  # 다른 종목은 그대로 검수를 통과했다


def test_LLM_대역의_AssertionError는_격리하지_않고_실행을_멈춘다(store, admin):
    day = reviewed_day()

    with pytest.raises(AssertionError, match="must not be called"):
        run_with(store, day, llm=BrokenDraftLLM(FakeLLM(day), AssertionError("LLM must not be called")))

    assert run_rows(admin) == [(False, None, None)]


# 종목 예외 격리 층 2(#17 D5): 카드 만들기·저장의 예외는 그 종목 카드만 전 줄 지연
MSFT_BARS = [bar("2026-10-14", 300), bar("2026-10-15", 303)]
ALL_DELAYED = {"news": ("Update delayed", LineStatus.DELAYED, "SEC filings"),
               "event": ("Update delayed", LineStatus.DELAYED, "Earnings and dividend calendar"),
               "price": ("Update delayed", LineStatus.DELAYED, "Daily prices")}


def card_lines(card):
    return {name: (line.text, line.status, line.source_scope)
            for name, line in (("news", card.news_line), ("event", card.event_line), ("price", card.price_fact_line))}


def msft_day(**replies):
    """reviewed_day + MSFT 봉이 AAPL과 다르다(계산 함수가 MSFT를 알아본다)."""
    day = reviewed_day()
    return dataclasses.replace(day, prices=day.prices | {"MSFT": MSFT_BARS}, **replies)


def test_카드_만들기에서_종목_하나가_예외를_내면_그_카드만_전_줄_지연이고_보류함_행은_그대로다(store, admin, monkeypatch):
    still_buy = json.dumps({"sentence": "Microsoft agreed to buy a startup"})
    first = msft_day()
    run(store, dataclasses.replace(first, llm_replies=first.llm_replies[:4] + [still_buy]))  # MSFT 재생성도 걸림 → 보류함 행
    holds = store.list_hold_items(FRI)
    assert [h.ticker for h in holds] == ["MSFT"]
    real = morning.change_pct

    def change_pct(bars):
        if bars[-1].close == 303:
            raise ZeroDivisionError("bug")
        return real(bars)

    monkeypatch.setattr(morning, "change_pct", change_pct)

    summary = run(store, msft_day())  # 이번에는 MSFT가 재생성 뒤 통과하지만 카드 만들기에서 예외

    cards = cards_by_ticker(store, FRI)
    msft = cards["MSFT"]
    assert (msft.status, msft.change_pct, msft.change_status, msft.news_line_accession) == (
        CardStatus.NORMAL, None, LineStatus.DELAYED, None)
    assert card_lines(msft) == ALL_DELAYED
    assert msft.previous_trading_day == THU
    assert store.list_hold_items(FRI) == holds  # 대체 카드는 보류함을 건드리지 않는다
    assert (cards["AAPL"].change_pct, cards["AAPL"].news_line.status) == (Decimal("1.3"), LineStatus.CHECKED_FOUND)
    assert cards["NVDA"].news_line.status is LineStatus.UNSUPPORTED
    assert summary.ticker_errors == (TickerError("MSFT", "ZeroDivisionError"),)
    assert (summary.cards_saved, summary.change_delayed, summary.failures) == (3, ("MSFT", "NVDA"), ())
    assert run_failed(summary) is True
    _, (finished, failed, record) = run_rows(admin)
    assert (finished, failed) == (True, True)
    assert record["failures"] == [{"stage": "card", "subject": "MSFT", "reason": "unexpected", "error": "ZeroDivisionError"}]
    assert record["lines"]["news"] == statuses(checked_found=1, delayed=1, unsupported=1)


class Unsaved(Exception):
    """save_card 대역이 내는 예외."""


def fail_msft_saves(store, monkeypatch, times):
    """store.save_card가 MSFT 카드에서 times번 Unsaved를 낸다."""
    real, left = store.save_card, [times]

    def save_card(card, holds):
        if card.ticker == "MSFT" and left[0]:
            left[0] -= 1
            raise Unsaved
        real(card, holds)

    monkeypatch.setattr(store, "save_card", save_card)


def test_카드_저장이_종목_하나에서_실패하면_그_종목은_전_줄_지연_카드로_저장한다(store, monkeypatch):
    fail_msft_saves(store, monkeypatch, 1)

    summary = run(store, msft_day())

    assert [c.ticker for c in store.list_cards(FRI)] == ["AAPL", "MSFT", "NVDA"]
    assert card_lines(cards_by_ticker(store, FRI)["MSFT"]) == ALL_DELAYED
    assert summary.ticker_errors == (TickerError("MSFT", "Unsaved"),)


def test_전_줄_지연_카드마저_저장하지_못하면_실행이_죽고_이어_하기가_받는다(store, admin, monkeypatch):
    fail_msft_saves(store, monkeypatch, 2)

    with pytest.raises(Unsaved):
        run(store, msft_day())

    assert [c.ticker for c in store.list_cards(FRI)] == ["AAPL"]
    assert run_rows(admin) == [(False, None, None)]
