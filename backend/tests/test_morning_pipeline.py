"""입구 1: 시나리오 → MorningPipeline.run → 저장소 읽기 함수로 확인."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from m30.adapters.events import Earnings, EarningsTiming
from m30.adapters.fake import (
    FakeEventSource,
    FakeFilingSource,
    FakeIndicatorSource,
    FakeLLM,
    FakePriceSource,
    Scenario,
    load_scenario,
)
from m30.adapters.prices import DailyBar
from m30.config import ET
from m30.models import CardStatus, Coverage, LineStatus
from m30.pipeline.morning import MorningPipeline

TUE = date(2026, 10, 13)
THU = date(2026, 10, 15)
FRI = date(2026, 10, 16)


def run(store, scenario, day=FRI):
    """scenario: 시나리오 JSON 경로 또는 코드로 만든 Scenario."""
    if not isinstance(scenario, Scenario):
        scenario = load_scenario(scenario)
    store.upsert_coverage(scenario.coverage)
    return MorningPipeline(
        prices=FakePriceSource(scenario),
        events=FakeEventSource(scenario),
        filings=FakeFilingSource(scenario),
        indicators=FakeIndicatorSource(scenario),
        llm=FakeLLM(scenario),
        store=store,
        sleep=lambda seconds: None,  # 실제로 기다리지 않는다
    ).run(day)


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
    changed.write_text(first_card.read_text().replace('"close": 202.50', '"close": 204.00'))
    run(store, changed)

    cards = store.list_cards(FRI)
    assert len(cards) == 3
    assert cards[0].ticker == "AAPL" and cards[0].change_pct == Decimal("2.0")


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
    ],
    ids=["봉_날짜가_직전_거래일_아님", "전일_종가_누락", "조정가_아님", "앞_봉만_조정가_아님", "전일_종가_0", "시가_0", "고가_0",
         "저가_0"],
)
def test_봉을_믿을_수_없으면_등락률과_세_번째_줄이_지연이고_없음이_아니다(store, bars):
    summary = run(store, aapl_only(bars), FRI)

    [card] = store.list_cards(FRI)
    assert (card.change_pct, card.change_status) == (None, LineStatus.DELAYED)
    line = card.price_fact_line
    assert (line.text, line.status, line.source_scope) == ("Update delayed", LineStatus.DELAYED, PRICE_SCOPE)
    assert summary.change_delayed == ("AAPL",)


def closes(*day_close):
    return [bar(f"2026-{d}", c) for d, c in day_close]


def year(*changed):
    """2025-10-10~2026-10-15 평일 봉 전부 O=H=L=C=100. changed 봉은 같은 날짜 봉을 바꾼다."""
    by_day = {b.day: b for b in changed}
    first, last = date(2025, 10, 10), date(2026, 10, 15)
    days = (first + timedelta(days=i) for i in range((last - first).days + 1))
    return [by_day.get(d, bar(d.isoformat(), 100)) for d in days if d.weekday() < 5]


LOW_80 = bar("2026-03-02", 80)  # 52주 저점을 멀리 둔다(저점 = 종가면 At 52-week low가 먼저 나온다)
HIGH_120 = bar("2026-03-02", 120)  # 52주 고점을 멀리 둔다(고점 대비 16.7% 이상 아래)
AT_HIGH = year(LOW_80, bar("2026-10-15", 110, open=Decimal(100), low=Decimal(100)))
HIGH_JUNE = bar("2026-06-01", 120)  # LOW_80과 함께: 마지막 종가 100은 고점에서 16.7% 아래, 저점에서 25.0% 위, 마지막 날 보합


def test_가격_데이터가_정상인데_사실이_없으면_No_additional_price_highlights이고_데이터가_빠지거나_틀리면_Update_delayed다(store):
    quiet = year(LOW_80, HIGH_JUNE)
    prices = {
        "QUIET": quiet,
        "UNADJ": year(LOW_80, HIGH_JUNE, bar("2026-10-15", 100, adjusted=False)),
        "STALE": [b for b in quiet if b.day != date(2026, 10, 15)],  # 마지막 봉이 직전 거래일이 아님
        "NOPREV": [b for b in quiet if b.day != date(2026, 10, 14)],  # 전일 종가 누락
        "ZERO": year(LOW_80, HIGH_JUNE, bar("2026-10-14", 0)),
    }
    run(store, Scenario(coverage=[Coverage(t, t) for t in prices], prices=prices), FRI)

    lines = {t: c.price_fact_line for t, c in cards_by_ticker(store, FRI).items()}
    assert {t: (line.text, line.status) for t, line in lines.items()} == {
        "QUIET": ("No additional price highlights", LineStatus.CHECKED_NONE),
        "UNADJ": ("Update delayed", LineStatus.DELAYED),
        "STALE": ("Update delayed", LineStatus.DELAYED),
        "NOPREV": ("Update delayed", LineStatus.DELAYED),
        "ZERO": ("Update delayed", LineStatus.DELAYED),
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
