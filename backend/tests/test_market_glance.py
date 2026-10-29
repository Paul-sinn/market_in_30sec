"""입구 1: 시장 한눈에(#11). 시나리오 market_glance.json + 가짜 출처·LLM → MorningPipeline.run → store.get_market_glance·가짜 LLM 요청.
시나리오(거래일 FRI 10-16, 직전 거래일 THU 10-15): SPY +0.4%, QQQ −1.2%, AAPL. 지표 일정 오늘 3건(8:30 둘, 10:00) + 다음 거래일 1건.
시장 전체 소식: 기간 [10-15 04:00, 10-16 04:00) 안 2건(연준 16:30 = 본문에 지시문, 노동통계국 08:30 = 0.3%), 기간 밖 1건(03:59).
LLM 응답: 소식 줄(노동통계국 항목) → 판정 fact. 공시가 없어 분류·첫 번째 줄 호출은 없다."""

import dataclasses
import json
from decimal import Decimal

import pytest

from m30 import config
from m30.adapters import Source
from m30.adapters.fake import FailurePlan, load_scenario
from m30.models import LineStatus
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.pipeline.glance import GLANCE_SYSTEM
from m30.pipeline.review import FACTCHECK_SYSTEM
from conftest import SCENARIOS
from test_collect_classify import FRI, run

GLANCE = SCENARIOS / "market_glance.json"
CLOSE = "Thu 10/15 close: S&P 500 (SPY) +0.4%, Nasdaq (QQQ) −1.2%"


def shown(line):
    return line.text, line.status, line.source_scope


def test_어제_마감_줄은_그날_SPY·QQQ_카드의_등락률로_코드가_만든다(store):
    run(store, GLANCE)

    cards = {c.ticker: c for c in store.list_cards(FRI)}
    glance = store.get_market_glance(FRI)
    assert shown(glance.close_line) == (CLOSE, LineStatus.CHECKED_FOUND, "Daily prices")  # 지수 값이 아니라 ETF 등락률
    assert (cards["SPY"].change_pct, cards["QQQ"].change_pct) == (Decimal("0.4"), Decimal("-1.2"))
    assert glance.close_line.checked_at == cards["SPY"].price_fact_line.checked_at  # 같은 실행의 확인 시각


def without_spy_bars(sc):
    return dataclasses.replace(sc, prices={**sc.prices, "SPY": []})


def without_spy(sc):
    return dataclasses.replace(sc, coverage=[c for c in sc.coverage if c.ticker != "SPY"])


@pytest.mark.parametrize("change", [without_spy_bars, without_spy], ids=["SPY_봉_없음", "SPY가_생성_대상이_아님"])
def test_SPY·QQQ_중_하나라도_등락률이_없으면_어제_마감_줄_전체가_지연이다(store, change):
    run(store, change(load_scenario(GLANCE)))

    assert shown(store.get_market_glance(FRI).close_line) == ("Update delayed", LineStatus.DELAYED, "Daily prices")


@pytest.mark.parametrize(
    "indicators, line",
    [
        ("scenario", ("CPI 8:30 AM ET · Jobless claims 8:30 AM ET +1 more", LineStatus.CHECKED_FOUND, "Economic calendar")),
        ([], ("No economic releases found", LineStatus.CHECKED_NONE, "Economic calendar")),
        (None, ("Not covered yet", LineStatus.UNSUPPORTED, None)),  # 출처 없음 = 미지원(가짜 "없음"을 만들지 않는다)
    ],
    ids=["거래일_발표_3건", "확인함_없음", "미지원"],
)
def test_오늘_지표_일정_줄은_거래일_발표를_시각·이름_순으로_두_개와_나머지_수로_코드가_쓴다(store, indicators, line):
    sc = load_scenario(GLANCE)
    run(store, sc if indicators == "scenario" else dataclasses.replace(sc, indicators=indicators))

    # 같은 8:30이면 이름 순, 다음 거래일(10-19) 발표는 빠진다
    assert shown(store.get_market_glance(FRI).indicator_line) == line


def test_지표_출처가_실패하면_지표_줄만_지연이고_요약_실패에_남는다(store):
    ran = run(store, dataclasses.replace(load_scenario(GLANCE), failures={(Source.INDICATORS, None): FailurePlan("error")}))

    glance = store.get_market_glance(FRI)
    assert shown(glance.indicator_line) == ("Update delayed", LineStatus.DELAYED, "Economic calendar")  # "없음"으로 쓰지 않는다
    assert glance.close_line.status is LineStatus.CHECKED_FOUND
    assert ran.summary.failures == (SourceFailure(Source.INDICATORS, None, FailureReason.ERROR),)


def news_block(request):
    """소식 요청 user의 데이터 블록(<news>와 </news> 사이)을 JSON으로 읽는다."""
    return json.loads(request.user.split("<news>\n", 1)[1].rsplit("\n</news>", 1)[0])


def test_시장_전체_소식_줄은_LLM_문장이_숫자·금지어·판정을_통과하면_그대로_저장된다(store):
    ran = run(store, GLANCE)

    glance = store.get_market_glance(FRI)
    assert shown(glance.market_news_line) == (NEWS_LINE, LineStatus.CHECKED_FOUND, "Official releases")  # 출처 꼬리표 없음
    assert (glance.market_news_hold_draft, glance.market_news_hold_rules) == (None, ())
    assert ran.summary.glance_review == "pass"
    write, check = ran.llm.requests
    assert (write.system, write.model) == (GLANCE_SYSTEM, config.GLANCE_MODEL)
    assert config.GLANCE_MODEL == "claude-haiku-5-5"  # 개발 중. 출시 전 opus로 상수 하나만 바꾼다
    assert (check.system, check.model) == (FACTCHECK_SYSTEM, config.REVIEW_MODEL)
