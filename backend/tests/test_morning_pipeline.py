"""입구 1: 시나리오 → MorningPipeline.run → 저장소 읽기 함수로 확인."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from m30.adapters.fake import FakePriceSource, load_scenario
from m30.config import ET
from m30.models import CardStatus, LineStatus
from m30.pipeline.morning import MorningPipeline

FRI = date(2026, 10, 16)


def run(store, scenario_path, day=FRI):
    scenario = load_scenario(scenario_path)
    store.upsert_coverage(scenario.coverage)
    return MorningPipeline(prices=FakePriceSource(scenario), store=store).run(day)


def test_시나리오로_실행하면_종목·거래일마다_카드가_하나_저장된다(store, first_card):
    summary = run(store, first_card)

    cards = store.list_cards(FRI)
    assert [(c.ticker, c.trading_day) for c in cards] == [("AAPL", FRI), ("MSFT", FRI), ("NVDA", FRI)]
    assert {c.ticker: c.change_pct for c in cards} == {"AAPL": Decimal("1.3"), "MSFT": Decimal("-1.3"), "NVDA": None}
    assert all(c.status is CardStatus.FALLBACK for c in cards)
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
    assert (nvda.news_line, nvda.event_line, nvda.price_fact_line) == (None, None, None)
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
