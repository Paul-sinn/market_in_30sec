"""가격 표시 플래그(#56, GLOSSARY PriceDisplay). 기본 off: 시세 어댑터를 만들지도 부르지도 않는다.
입구 1(아침 파이프라인 실행, prices=None = off)과 입구 3(프로세스 출력, CLI가 플래그를 읽는다). 값 해석은 순수 함수 경계값."""

import os
import subprocess
import sys

import pytest

from m30.adapters.fake import Scenario
from m30.config import price_display_on
from m30.models import LineStatus
from m30.pipeline.morning import TickerError
from m30.pipeline.production import run_failed
from conftest import SCENARIOS
from test_collect_classify import AAPL, FRI, MSFT
from test_collect_classify import run as run_with  # 출처를 바꿔 넣는 run: prices=None = 가격 표시 off
from test_morning_notice import QUIET, UP_5, user_with
from test_morning_pipeline import TWO_BARS, fail_msft_saves, msft_day
from test_production import TIINGO_CANARY, run_probe

GLANCE = SCENARIOS / "market_glance.json"  # SPY·QQQ·AAPL 봉 있음, 지표 일정·시장 소식 있음


def first_two(card):
    """첫·두 번째 줄 (문구, 상태, 범위). 확인 시각은 실행마다 다르다."""
    return [(line.text, line.status, line.source_scope) for line in (card.news_line, card.event_line)]


@pytest.mark.parametrize("env, on", [
    ({}, False), ({"PRICE_DISPLAY": ""}, False), ({"PRICE_DISPLAY": "off"}, False), ({"PRICE_DISPLAY": "OFF"}, False),
    ({"PRICE_DISPLAY": "true"}, False), ({"PRICE_DISPLAY": "1"}, False), ({"PRICE_DISPLAY": "yes"}, False),
    ({"PRICE_DISPLAY": "onn"}, False),
    ({"PRICE_DISPLAY": "on"}, True), ({"PRICE_DISPLAY": "ON"}, True), ({"PRICE_DISPLAY": " on\n"}, True),
])
def test_가격_표시_플래그는_on일_때만_켜지고_없거나_이상한_값이면_꺼진다(env, on):
    assert price_display_on(env) is on


def test_가격_표시가_꺼지면_카드는_등락률_미지원이고_가격_사실_줄_열이_전부_null이다(store, admin):
    run_with(store, GLANCE)  # on: 가격 열에 값이 들어간 뒤 off 재실행이 지우는지도 본다
    on = {c.ticker: first_two(c) for c in store.list_cards(FRI)}

    summary = run_with(store, GLANCE, prices=None).summary

    cards = store.list_cards(FRI)
    assert [c.ticker for c in cards] == ["AAPL", "QQQ", "SPY"]
    assert [(c.change_pct, c.change_status, c.price_fact_line) for c in cards] == [(None, LineStatus.UNSUPPORTED, None)] * 3
    assert {c.ticker: first_two(c) for c in cards} == on  # 첫·두 번째 줄은 on과 같다
    [(priced, not_unsupported)] = admin.execute(
        "select count(*) filter (where change_pct is not null or price_fact_line_status is not null"
        " or price_fact_line_text is not null or price_fact_line_checked_at is not null"
        " or price_fact_line_source_scope is not null),"
        " count(*) filter (where change_status <> 'unsupported') from public.stock_card").fetchall()
    assert (priced, not_unsupported) == (0, 0)
    assert summary.change_delayed == ()  # 미지원은 "등락률 지연"으로 세지 않는다
    assert summary.line_counts["change"] == {"checked_found": 0, "checked_none": 0, "delayed": 0, "unsupported": 3}
    assert summary.line_counts["price"] == {"checked_found": 0, "checked_none": 0, "delayed": 0, "unsupported": 0}
    assert run_failed(summary) is False


def shown(line):
    return line.text, line.status, line.source_scope


def test_가격_표시가_꺼지면_시장_한눈에_어제_마감_줄은_미지원으로_저장되고_나머지_두_줄은_그대로다(store, admin):
    run_with(store, GLANCE, prices=None)

    glance = store.get_market_glance(FRI)
    assert shown(glance.close_line) == ("Not covered yet", LineStatus.UNSUPPORTED, None)
    assert shown(glance.indicator_line) == (  # test_market_glance의 on 기댓값과 같다
        "CPI 8:30 AM ET · Jobless claims 8:30 AM ET +1 more", LineStatus.CHECKED_FOUND, "BLS, BEA and Fed calendars")
    assert shown(glance.market_news_line) == (
        "Bureau of Labor Statistics reported consumer prices rose 0.3% in September", LineStatus.CHECKED_FOUND,
        "BLS, BEA, Census and Fed releases")
    [(summary,)] = admin.execute("select summary from public.pipeline_run").fetchall()
    assert summary["glance"]["close"] == "unsupported"


def test_가격_표시가_꺼지면_종목_예외_대체_카드도_등락률_미지원이고_가격_사실_줄이_없다(store, monkeypatch):
    fail_msft_saves(store, monkeypatch, 1)

    summary = run_with(store, msft_day(), prices=None).summary

    msft = {c.ticker: c for c in store.list_cards(FRI)}["MSFT"]
    assert (msft.change_pct, msft.change_status, msft.price_fact_line) == (None, LineStatus.UNSUPPORTED, None)
    assert first_two(msft) == [("Update delayed", LineStatus.DELAYED, "SEC filings"),
                               ("Update delayed", LineStatus.DELAYED, "Earnings and dividend calendar")]
    assert summary.ticker_errors == (TickerError("MSFT", "Unsaved"),)
    assert summary.change_delayed == ()


def test_가격_표시가_꺼지면_Plus_유저의_아침_알림에_가격_사실이_없다(store, admin, make_user):
    day = Scenario(coverage=[AAPL, MSFT], prices={"AAPL": TWO_BARS, "MSFT": UP_5})  # on이면 "MSFT: Up 5 days in a row"
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"], "plus")

    run_with(store, day, prices=None)

    assert store.list_notices(FRI) == {uid: QUIET}


@pytest.mark.parametrize("tiingo_key", [TIINGO_CANARY, f"{TIINGO_CANARY}\n"], ids=["키_있음", "형식_틀린_키"])
def test_운영_CLI는_가격_표시가_꺼져_있으면_TIINGO_API_KEY가_있어도_시세를_만들지도_부르지도_않는다(settings, admin, tiingo_key):
    # 탐침 Tiingo는 "quiet"에서 불리면 RUN FAILED. 형식 틀린 키도 막지 않는다 = 시세 설정을 읽지도 않는다
    code, out = run_probe(settings, "quiet", tiingo_key=tiingo_key, price_display=None)

    assert code == 0
    lines = out.splitlines()
    assert "RUN FAILED" not in out
    assert "2026-10-16 cards_saved=15 resumed=- change_delayed=-" in lines
    assert "lines: change[unsupported=15] news[checked_none=15] event[unsupported=15] price[] related[unsupported=15]" in lines
    assert "glance: close=unsupported indicator=checked_none market_news=checked_none review=-" in lines
    assert "prices=off" in lines


def test_시나리오_CLI는_가격_표시가_꺼져_있으면_가짜_시세도_쓰지_않는다(admin, first_card):
    env = {k: v for k, v in os.environ.items() if k != "PRICE_DISPLAY"}  # conftest의 on을 빼면 기본 off
    r = subprocess.run([sys.executable, "-m", "m30.pipeline", "2026-10-16", "--scenario", str(first_card)],
                       cwd=SCENARIOS.parent, env=env, capture_output=True, text=True, timeout=60)

    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()  # first_card는 AAPL·MSFT 봉이 있다: on이면 change[checked_found=2 delayed=1]
    assert "2026-10-16 cards_saved=3 resumed=- change_delayed=-" in lines
    assert "lines: change[unsupported=3] news[unsupported=3] event[unsupported=3] price[] related[unsupported=3]" in lines
    assert "glance: close=unsupported indicator=unsupported market_news=unsupported review=-" in lines
