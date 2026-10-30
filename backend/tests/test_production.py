"""운영 모드(#26). 네트워크 없음, 로컬 DB.
입구 1: run_production. SEC는 기록용 get(test_edgar.RecordedGet), LLM은 부르면 실패하는 객체.
입구 3: 운영 CLI를 하위 프로세스(production_probe)로 돌려 exit 코드·출력을 본다. 바꾸는 것은 전송 층 둘(SEC get·LLM)뿐."""

import dataclasses
import json
import os
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from m30.adapters import AccessDeniedError, Source, SourceError, TransientSourceError
from m30.adapters.edgar import SUBMISSIONS_URL, TICKERS_URL
from m30.adapters.unavailable import NoPriceSource
from m30.db.store import CardStore, connect
from m30.experiment import EXPERIMENT_DEFAULT_TICKERS
from m30.models import FundHoldings, LineStatus
from m30.adapters.nport import MF_TICKERS_URL
from m30.pipeline.lines import NEWS_SCOPE, NO_FILINGS, NOT_COVERED, PRICE_SCOPE, UPDATE_DELAYED
from m30.pipeline.production import run_failed, run_production
from m30.adapters.gov import BEA_ICS_URL, BLS_ICS_URL
from m30.adapters.gov_news import FED_RSS_URL
from m30.pipeline import collect
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.pipeline.glance import GLANCE_SYSTEM
from m30.pipeline.review import FACTCHECK_SYSTEM
from production_probe import COMPANY_CIKS, DRAFT_CANARY, ETFS, GOV_CANARY, GlanceLLM, NoCallLLM, gov_day, quiet_day, quiet_gov
from test_gov import BEA, BEA_GDP, BEA_INCOME, FEED_URLS
from test_edgar import RecordedGet
from test_nport import OTHER_SERIES, QQQ_8, QQQ_CIK, SCHD_8, SCHWAB_CIK, SPY_8, SPY_CIK, txt_url
from test_tiingo import body, row, source

FRI = date(2026, 10, 16)


def glance_lines(glance):
    return {name: (line.text, line.status, line.source_scope) for name, line in (
        ("close", glance.close_line), ("indicator", glance.indicator_line), ("news", glance.market_news_line))}


def lines(card):
    return {
        name: (line.text, line.status, line.source_scope)
        for name, line in (("news", card.news_line), ("event", card.event_line), ("price", card.price_fact_line))
    }


# 녹화 N-PORT 보고(test_nport) 상위 10개 회사 중 실험 커버 범위에 있는 것. 손으로 센 값
QQQ_TOP = FundHoldings(LineStatus.CHECKED_FOUND, ("AAPL", "AMZN", "GOOGL", "MSFT", "NVDA", "TSLA"), 6, 4)  # Micron·AMD·Intel·Broadcom
ETF_FUNDS = {
    "QQQ": QQQ_TOP,
    "SCHD": FundHoldings(LineStatus.CHECKED_FOUND, ("KO",), 1, 9),
    "SPY": FundHoldings(LineStatus.CHECKED_FOUND, ("AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA"), 7, 3),  # Broadcom·Micron·Lilly
    "TQQQ": QQQ_TOP,
}
ETF_SCOPES = {"QQQ": "SEC filings of 6 top holdings", "SCHD": "SEC filings of 1 top holding",
              "SPY": "SEC filings of 7 top holdings", "TQQQ": "SEC filings of 6 top holdings"}


def test_운영_실행은_실제_공시·편입_보고와_미연결_출처만_써서_가짜_데이터_없이_카드를_만든다(store):
    get = RecordedGet(quiet_day())

    summary, refreshed = run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=get, llm=NoCallLLM(), prices=NoPriceSource())

    assert refreshed is True
    assert {c.ticker: c.cik for c in store.list_coverage()} == COMPANY_CIKS | dict.fromkeys(ETFS)
    # 편입 종목을 읽을 ETF(#10 D2). TQQQ는 QQQ의 편입 종목을 쓴다
    assert {c.ticker: c.holdings_ticker for c in store.list_coverage() if c.holdings_ticker} == {
        "SPY": "SPY", "QQQ": "QQQ", "TQQQ": "QQQ", "SCHD": "SCHD"}
    assert summary.funds == ETF_FUNDS
    cards = store.list_cards(FRI)
    assert len(cards) == summary.cards_saved == 15
    for card in cards:
        assert (card.change_pct, card.change_status) == (None, LineStatus.DELAYED)  # 시세 출처 없음(#18 전)
        news = (NO_FILINGS, LineStatus.CHECKED_NONE, ETF_SCOPES.get(card.ticker, NEWS_SCOPE))  # 편입 종목 공시도 없는 날
        assert lines(card) == {
            "news": news,
            "event": (NOT_COVERED, LineStatus.UNSUPPORTED, None),  # 일정 출처 없음(#21 전) = 미지원
            "price": (UPDATE_DELAYED, LineStatus.DELAYED, PRICE_SCOPE),
        }, card.ticker
    assert summary.failures == ()
    assert summary.llm_calls == 0
    assert run_failed(summary) is False
    assert store.list_raw_indicators(FRI) == []
    # 편입 보고는 fund 순(QQQ·SCHD·SPY, TQQQ는 QQQ)으로 한 번씩. 편입 어댑터는 두 목록을 자기 인스턴스에서 처음 필요할 때 받는다
    assert get.urls == [
        TICKERS_URL,
        MF_TICKERS_URL, SUBMISSIONS_URL.format(cik=QQQ_CIK), txt_url(QQQ_CIK, QQQ_8), TICKERS_URL,
        SUBMISSIONS_URL.format(cik=SCHWAB_CIK), txt_url(SCHWAB_CIK, OTHER_SERIES), txt_url(SCHWAB_CIK, SCHD_8),
        SUBMISSIONS_URL.format(cik=SPY_CIK), txt_url(SPY_CIK, SPY_8),
    ] + [SUBMISSIONS_URL.format(cik=cik) for cik in sorted(COMPANY_CIKS.values())]


def test_운영_실행의_시장_한눈에는_발표가_없는_날_두_줄_모두_확인한_기관_범위로_없음이다(store):
    summary, _ = run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day()), llm=NoCallLLM(),
                                prices=NoPriceSource())

    assert glance_lines(store.get_market_glance(FRI)) == {
        "close": (UPDATE_DELAYED, LineStatus.DELAYED, PRICE_SCOPE),  # SPY·QQQ 등락률 없음(#18 전)
        "indicator": ("No Fed decision or major BLS or BEA releases scheduled", LineStatus.CHECKED_NONE, "BLS, BEA and Fed calendars"),
        "news": ("No new major BLS, BEA, Census or Fed releases", LineStatus.CHECKED_NONE, "BLS, BEA, Census and Fed releases"),
    }
    assert (summary.llm_calls, summary.glance_review) == (0, "-")  # 쓸 소식이 없으면 LLM을 부르지 않는다
    assert store.list_raw_market_news(FRI) == [] and store.list_raw_indicators(FRI) == []


THU = date(2026, 10, 29)


def test_운영_실행은_BLS·BEA_일정과_FOMC_표로_지표_일정_줄을_쓰고_기관_발표로_소식_줄을_쓰며_원본을_저장한다(store):
    gov, sec, llm = RecordedGet(gov_day()), RecordedGet(quiet_day()), GlanceLLM()

    summary, _ = run_production(store, THU, get=sec, gov_get=gov, llm=llm, prices=NoPriceSource())

    assert glance_lines(store.get_market_glance(THU)) == {
        "close": (UPDATE_DELAYED, LineStatus.DELAYED, PRICE_SCOPE),
        "indicator": ("GDP 8:30 AM ET · Income and spending 8:30 AM ET", LineStatus.CHECKED_FOUND, "BLS, BEA and Fed calendars"),
        "news": ("Federal Reserve issued its policy statement", LineStatus.CHECKED_FOUND, "BLS, BEA, Census and Fed releases"),
    }
    gdp, income = store.list_raw_indicators(THU)  # 원본 = VEVENT 그대로
    assert gdp.startswith("BEGIN:VEVENT") and "SUMMARY:GDP (Advance Estimate)\\, 3rd Quarter 2026" in gdp
    assert income.startswith("BEGIN:VEVENT") and "SUMMARY:Personal Income and Outlays\\, September 2026" in income
    [fomc] = store.list_raw_market_news(THU)  # 10/28 FOMC 성명(18:00 GMT)
    assert "monetary20261028a.htm" in fomc
    assert summary.failures == () and summary.glance_review == "pass"
    assert [r.system for r in llm.requests] == [GLANCE_SYSTEM, FACTCHECK_SYSTEM]  # 소식 하나: 초안 + 판정
    assert gov.urls == [BLS_ICS_URL, BEA_ICS_URL, *FEED_URLS]  # 기관 요청은 SEC 창구와 따로
    assert TICKERS_URL in sec.urls and not [u for u in sec.urls if "sec.gov" not in u]


FRI30 = date(2026, 10, 30)


def test_같은_거래일을_두_번_운영_실행해도_공식_발표_원본은_기간_안_항목만_한_번씩_추가된다(store, admin):
    for _ in range(2):
        summary, _ = run_production(store, FRI30, get=RecordedGet(quiet_day()), gov_get=RecordedGet(gov_day()),
                                    llm=GlanceLLM("Bureau of Economic Analysis released new data"), prices=NoPriceSource())

    # 기간 [10/29 04:00, 10/30 04:00) 안 BEA GDP·소득지출(08:30)만. 피드의 나머지 수십 건은 저장하지 않는다
    assert admin.execute("select source, key, trading_day from public.market_news_item order by key").fetchall() == [
        (BEA, BEA_GDP, FRI30), (BEA, BEA_INCOME, FRI30)]
    assert glance_lines(store.get_market_glance(FRI30))["indicator"] == (
        "Labor costs 8:30 AM ET", LineStatus.CHECKED_FOUND, "BLS, BEA and Fed calendars")
    assert summary.failures == ()


def test_연준_피드가_깨지면_소식_줄만_지연이고_LLM을_부르지_않으며_앞_실행이_확인한_소식_줄은_그대로_둔다(store):
    broken = {FED_RSS_URL: b"<rss><channel><item>"}

    def run(gov, llm):
        summary, _ = run_production(store, THU, get=RecordedGet(quiet_day()), gov_get=RecordedGet(gov), llm=llm,
                                    prices=NoPriceSource())
        return summary, store.get_market_glance(THU)

    summary, delayed = run(gov_day(**broken), NoCallLLM())
    _, checked = run(gov_day(), GlanceLLM())
    again_summary, again = run(gov_day(**broken), NoCallLLM())

    assert glance_lines(delayed)["news"] == (UPDATE_DELAYED, LineStatus.DELAYED, "BLS, BEA, Census and Fed releases")
    assert delayed.indicator_line.status is LineStatus.CHECKED_FOUND  # 지표 일정 줄은 그대로
    assert summary.failures == again_summary.failures == (SourceFailure(Source.MARKET_NEWS, None, FailureReason.ERROR),)
    assert summary.llm_calls == again_summary.llm_calls == 0
    assert checked.market_news_line.status is LineStatus.CHECKED_FOUND
    assert again.market_news_line == checked.market_news_line  # 기간이 고정이라 실패는 새 정보가 아니다(#11)


def test_BLS_일정이_503을_계속_내면_지표_일정_줄만_지연이고_다시_시도_뒤_실패로_남는다(store, monkeypatch):
    monkeypatch.setattr(collect, "RETRY_DELAYS", (0.0, 0.0, 0.0))
    gov = RecordedGet(quiet_gov(**{BLS_ICS_URL: TransientSourceError("bls http 503")}))

    summary, _ = run_production(store, FRI, get=RecordedGet(quiet_day()), gov_get=gov, llm=NoCallLLM(), prices=NoPriceSource())

    shown = glance_lines(store.get_market_glance(FRI))
    assert shown["indicator"] == (UPDATE_DELAYED, LineStatus.DELAYED, "BLS, BEA and Fed calendars")  # "없음"으로 쓰지 않는다
    assert shown["news"] == (  # 소식 어댑터는 따로 성공
        "No new major BLS, BEA, Census or Fed releases", LineStatus.CHECKED_NONE, "BLS, BEA, Census and Fed releases")
    assert summary.failures == (SourceFailure(Source.INDICATORS, None, FailureReason.RETRIES_EXHAUSTED),)
    assert gov.urls.count(BLS_ICS_URL) == 4 and BEA_ICS_URL not in gov.urls  # 어댑터 호출 전체를 다시 한다
    assert store.list_raw_indicators(FRI) == []


def test_운영_실행은_그_분기_기본_종목으로_실험_15종목을_저장한다(store):
    assert {"SPY", "QQQ"} <= set(EXPERIMENT_DEFAULT_TICKERS)  # 지수 대신 SPY·QQQ(부모 스펙: 선정 시 보장)
    experiment = sorted(COMPANY_CIKS | dict.fromkeys(ETFS))

    for _ in range(2):  # 재실행해도 그대로
        run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

        assert [c.ticker for c in store.list_generation_targets(date(2026, 10, 1))] == experiment  # 유저 0명 = 기본 종목
        assert [c.ticker for c in store.list_generation_targets(date(2026, 12, 31))] == experiment  # 2026Q4 끝까지
        assert store.list_generation_targets(date(2026, 9, 30)) == []  # 2026Q3에는 넣지 않았다


def test_운영_실행에_Tiingo_시세를_넣으면_15종목_모두_등락률과_세_번째_줄을_계산한다(store, monkeypatch):
    day = body(row("2026-10-14", 100), row("2026-10-15", 101))
    prices, opener = source(monkeypatch, dict.fromkeys(COMPANY_CIKS | dict.fromkeys(ETFS), day))

    summary, _ = run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=prices)

    cards = store.list_cards(FRI)
    assert len(cards) == 15 and len(opener.requests) == 15  # 종목마다 한 번
    for card in cards:
        assert (card.change_pct, card.change_status) == (Decimal("1.0"), LineStatus.CHECKED_FOUND), card.ticker
        assert card.price_fact_line.status is LineStatus.CHECKED_NONE, card.ticker  # 봉 2개: 연속·52주 사실 없음
    assert summary.change_delayed == ()
    assert run_failed(summary) is False


def content(card):
    """확인 시각·갱신 시각을 뺀 카드 내용."""
    return (card.ticker, card.status, card.change_pct, card.change_status, card.leverage_tag, card.news_line_accession,
            lines(card))


def test_같은_거래일을_다시_운영_실행해도_커버_범위와_카드가_중복_없이_그대로다(store):
    run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())
    coverage, cards = store.list_coverage(), [content(c) for c in store.list_cards(FRI)]

    summary, _ = run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

    assert store.list_coverage() == coverage
    assert len(coverage) == 15
    assert [content(c) for c in store.list_cards(FRI)] == cards
    assert summary.cards_saved == 15


def test_첫_실행에서_SEC_티커_목록을_못_받으면_카드_0장이라_실패한_실행이다(store):
    get = RecordedGet({TICKERS_URL: SourceError("sec tickers shape")})

    summary, refreshed = run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=get, llm=NoCallLLM(), prices=NoPriceSource())

    assert refreshed is False
    assert summary.cards_saved == 0
    assert run_failed(summary) is True
    assert get.urls == [TICKERS_URL]  # 다시 시도하지 않는다


def test_죽은_앞_실행이_카드를_모두_저장했으면_이어_한_실행은_카드_0장이어도_실패가_아니다(store):
    summary, _ = run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

    assert run_failed(dataclasses.replace(summary, cards_saved=0, resumed=("AAPL",))) is False
    assert run_failed(dataclasses.replace(summary, cards_saved=0, resumed=())) is True


def test_SEC_티커_목록을_못_받으면_지난_CIK로_카드를_만들고_실패로_치지_않는다(store):
    run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

    summary, refreshed = run_production(
        store, FRI, gov_get=RecordedGet(quiet_gov()), get=RecordedGet(quiet_day(**{TICKERS_URL: TransientSourceError("sec timeout")})), llm=NoCallLLM(),
        prices=NoPriceSource(),
    )

    assert refreshed is False
    assert {c.ticker: c.cik for c in store.list_coverage()} == COMPANY_CIKS | dict.fromkeys(ETFS)
    assert summary.cards_saved == 15
    assert run_failed(summary) is False


def test_SEC가_403으로_막아도_카드는_나가지만_실패한_실행이다(store):
    get = RecordedGet(quiet_day(**{SUBMISSIONS_URL.format(cik=COMPANY_CIKS["AAPL"]): AccessDeniedError("sec http 403")}))

    summary, _ = run_production(store, FRI, gov_get=RecordedGet(quiet_gov()), get=get, llm=NoCallLLM(), prices=NoPriceSource())

    assert summary.access_denied == (Source.SEC_FILINGS,)
    cards = {c.ticker: c for c in store.list_cards(FRI)}
    assert len(cards) == summary.cards_saved == 15  # 가용성은 열린 쪽
    assert cards["AAPL"].news_line.status is LineStatus.DELAYED  # 못 받은 것을 "없음"으로 두지 않는다
    assert run_failed(summary) is True


# 입구 3: 운영 CLI 하위 프로세스. 비밀값 자리는 캐너리(전송 층을 바꿨으니 어디로도 가지 않는다)
BACKEND = Path(__file__).resolve().parent.parent
KEY_CANARY, UA_CANARY = "sk-ant-KeyCanary93", "M30 Canary uaCanary41@example.invalid"
TIINGO_CANARY = "tiingoKeyCanary57"
WEBHOOK_CANARY = "https://discord.com/api/webhooks/123456789012345678/WebhookCanary88" + "x" * 60
BACKUP_LINE = "BACKUP RUN: no finished run when the GitHub schedule backup started (check pg_cron dispatch)"


def run_probe(settings, situation, tiingo_key=None, extra=(), trigger=None, webhook=None, day="2026-10-16"):
    """tiingo_key가 없으면 TIINGO_API_KEY를 뺀 환경(구독 전). 셸에 진짜 키가 있어도 하위 프로세스로 넘기지 않는다. extra = 덧붙일 CLI 인자.
    trigger = 워크플로가 넘기는 RUN_TRIGGER(github.event_name). 없으면 변수 없이(로컬 실행).
    webhook = DISCORD_WEBHOOK_URL. 없으면 변수 없이(셸의 진짜 웹훅을 넘기지 않는다)."""
    env = {k: v for k, v in os.environ.items() if k not in ("TIINGO_API_KEY", "RUN_TRIGGER", "DISCORD_WEBHOOK_URL")} | {
        "SUPABASE_DB_URL": settings.database_url, "ANTHROPIC_API_KEY": KEY_CANARY, "SEC_USER_AGENT": UA_CANARY
    } | ({"TIINGO_API_KEY": tiingo_key} if tiingo_key else {}) | ({"RUN_TRIGGER": trigger} if trigger else {}) | (
        {"DISCORD_WEBHOOK_URL": webhook} if webhook else {})
    r = subprocess.run([sys.executable, "tests/production_probe.py", situation, "--production", day, *extra],
                       cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    leaked = [c for c in (KEY_CANARY, UA_CANARY, TIINGO_CANARY, "WebhookCanary88", settings.database_url) if c in out]
    assert not leaked  # 키·연락처·시세 토큰·웹훅 주소·DB 접속 문자열(로컬이라 비밀번호는 캐너리가 아니다)
    assert out.endswith("fake_modules=[]\n")  # 실행한 운영 경로 어디서도(함수 안 import 포함) 가짜 어댑터를 불러오지 않았다
    return r.returncode, out


def webhook_message(out):
    """탐침이 받은 Discord 메시지(한 번만 보냈다)."""
    [content] = [json.loads(line.removeprefix("webhook_content=")) for line in out.splitlines() if line.startswith("webhook_content=")]
    return content


@pytest.mark.parametrize(
    "situation, exit_code, lines",
    [
        ("quiet", 0, ["2026-10-16 cards_saved=15 resumed=- ", "coverage: refreshed", "prices=none",
                      "glance: close=delayed indicator=checked_none market_news=checked_none review=-",
                      "holdings: QQQ=checked_found(unmatched 4) SCHD=checked_found(unmatched 9)"
                      " SPY=checked_found(unmatched 3) TQQQ=checked_found(unmatched 4)"]),
        ("denied", 1, ["ACCESS DENIED (not retried): sec_filings", "cards_saved=15", "coverage: refreshed"]),
        ("no_tickers", 1, ["cards_saved=0", "coverage: NOT REFRESHED (sec ticker list failed), stored rows used"]),
    ],
    ids=["정상", "SEC_403", "빈_DB에_티커_목록_실패"],
)
def test_운영_CLI는_실행_요약과_CIK_갱신_여부를_찍고_실패한_실행이면_1로_끝난다(settings, admin, situation, exit_code, lines):
    code, out = run_probe(settings, situation)

    assert code == exit_code
    for line in lines:
        assert line in out, line


GOV_HOSTS_SHOWN = ("bls.gov", "bea.gov", "census.gov", "federalreserve.gov")  # 기관 주소 일부


@pytest.mark.parametrize(
    "situation, day, exit_code, lines",
    [
        ("gov_canary", "2026-10-16", 0,  # BLS PPI(본문에 캐너리)가 기간 안
         ["glance: close=delayed indicator=checked_none market_news=checked_found review=pass"]),
        ("gov_canary", "2026-10-29", 0,  # 연준 FOMC 성명(제목에 캐너리)이 기간 안
         ["glance: close=delayed indicator=checked_found market_news=checked_found review=pass"]),
        ("gov_denied", "2026-10-16", 1,  # 차단은 출처 단위: 소식 어댑터도 BLS 피드에서 403을 받는다
         ["failed: indicators=access_denied, market_news=access_denied", "ACCESS DENIED (not retried): indicators, market_news",
          "glance: close=delayed indicator=delayed market_news=delayed review=-"]),
        ("gov_down", "2026-10-16", 1,
         ["failed: indicators=retries_exhausted", "glance: close=delayed indicator=delayed market_news=checked_none review=-"]),
    ],
    ids=["캐너리_BLS", "캐너리_연준", "BLS_403", "BLS_503"],
)
def test_운영_CLI·Discord·실행_기록은_기관_출처의_줄_상태와_실패_코드만_남기고_원문·주소·연락처는_남기지_않는다(
        settings, admin, situation, day, exit_code, lines):
    code, out = run_probe(settings, situation, webhook=WEBHOOK_CANARY, day=day)  # 연락처(UA)·키 캐너리 검사는 run_probe

    assert code == exit_code
    for line in lines:
        assert line in out.splitlines(), line
        assert line in webhook_message(out).splitlines(), line
    [(summary,)] = admin.execute("select summary from public.pipeline_run").fetchall()
    recorded = json.dumps(summary)
    assert [c for c in (GOV_CANARY, *GOV_HOSTS_SHOWN) if c in out + recorded] == []
    if situation == "gov_canary":  # 캐너리가 실제로 원본과 줄에 들어간 실행이다
        [(payloads, news_line)] = admin.execute(
            "select (select string_agg(payload, '') from public.market_news_item), market_news_line_text from public.market_glance"
        ).fetchall()
        assert GOV_CANARY in payloads and GOV_CANARY in news_line


def test_실패한_운영_실행은_요약_맨_위에_실패_배너와_실패_목록을_찍는다(settings, admin):
    code, out = run_probe(settings, "denied")

    assert code == 1
    # 403 뒤 이번 실행은 SEC를 더 부르지 않는다: AAPL과 CIK 순으로 그 뒤 6개(MSFT·AMZN·NVDA·TSLA·META·GOOGL)가 차단으로 남는다
    denied = ["0000320193", "0000789019", "0001018724", "0001045810", "0001318605", "0001326801", "0001652044"]
    assert out.splitlines()[:3] == [
        "!!! FAILED: failures=7 cards=15 !!!",
        "failed: " + ", ".join(f"sec_filings/{cik}=access_denied" for cik in denied),
        "ACCESS DENIED (not retried): sec_filings",
    ]


def test_정상_운영_실행은_배너_없이_LLM_토큰과_줄_상태별_카드_수를_찍는다(settings, admin):
    code, out = run_probe(settings, "quiet")

    assert code == 0
    lines = out.splitlines()
    assert not [line for line in lines if "!!!" in line or line.startswith("failed:")]
    assert "filings=0 unclassified=0 batches=0 skipped=- llm_calls=0/60 tokens=in:0,out:0,cache_read:0,cache_write:0" in lines
    # 0인 상태는 뺀다. 시세 키 없음 = 등락률·세 번째 줄 지연, 일정 출처 없음 = 미지원, 공시 없는 날 = 15장 모두 확인함·없음
    assert "lines: change[delayed=15] news[checked_none=15] event[unsupported=15] price[delayed=15]" in lines


def test_운영_실행_중_DB_오류는_예외_이름과_SQLSTATE만_찍고_행_내용은_공개_로그에_남기지_않는다(settings, admin):
    code, out = run_probe(settings, "db_error")

    assert code == 1
    assert "RUN FAILED: CheckViolation sqlstate=23514" in out
    assert DRAFT_CANARY.split()[0] not in out  # 서버 오류 DETAIL(Failing row contains …)의 검수 전 문장
    assert "Failing row" not in out and "Traceback" not in out


def test_운영_실행_중_예상_못_한_예외는_메시지에_키가_있어도_예외_이름만_찍고_실패한다(settings, admin):
    code, out = run_probe(settings, "crash")  # 라이브러리가 키를 예외 메시지에 넣는 경우. 캐너리 검사는 run_probe

    assert code == 1
    assert "RUN FAILED: ValueError" in out
    assert "Traceback" not in out


@pytest.mark.parametrize(
    "situation, exit_code, lines",
    [
        ("tiingo_quiet", 0, ["2026-10-16 cards_saved=15 resumed=- change_delayed=-", "prices=tiingo"]),
        # 응답 오류(주소·사유·본문)에 받은 Authorization 값을 그대로 넣어도 출력에는 출처·티커·사유 코드만
        ("tiingo_denied", 1, ["ACCESS DENIED (not retried): prices", "failed: prices/AAPL=access_denied", "prices=tiingo"]),
    ],
    ids=["Tiingo_정상", "Tiingo_401"],
)
def test_운영_CLI는_TIINGO_API_KEY가_있으면_Tiingo_시세를_쓰고_토큰을_출력하지_않는다(settings, admin, situation, exit_code, lines):
    code, out = run_probe(settings, situation, tiingo_key=TIINGO_CANARY)

    assert code == exit_code
    for line in lines:
        assert line in out, line


def test_운영_CLI는_같은_거래일_실행이_돌고_있으면_LOCKED_한_줄만_찍고_1로_끝난다(settings, admin):
    with connect(settings) as conn, CardStore(conn).run_lock(FRI):
        code, out = run_probe(settings, "quiet")

    assert code == 1
    assert out == "LOCKED: 2026-10-16 같은 거래일 실행이 이미 돌고 있어 종료합니다\nfake_modules=[]\n"  # RUN FAILED 아님


def test_운영_CLI는_TIINGO_API_KEY가_한_줄_ASCII가_아니면_DB에_붙기_전에_변수_이름만_찍고_2로_끝난다(settings, admin):
    code, out = run_probe(settings, "quiet", tiingo_key=f"{TIINGO_CANARY}\n")

    assert code == 2
    assert out == "TIINGO_API_KEY must be one line of printable ASCII without spaces\nfake_modules=[]\n"


def test_운영_품질_확인은_TIINGO_API_KEY가_있어도_시세를_부르지_않고_요약_뒤에_품질_블록을_찍는다(settings, admin):
    code, out = run_probe(settings, "quiet", tiingo_key=TIINGO_CANARY, extra=["--quality"])  # 탐침 Tiingo는 불리면 RUN FAILED

    assert code == 0
    lines = out.splitlines()
    assert "prices=none" in lines  # 무료 키 시간당 50회 보호: 품질 확인 대상은 첫 번째 줄
    assert lines.index("prices=none") < lines.index(
        "quality 2026-10-16 classify=claude-haiku-5-5 newsline=claude-haiku-5-5 review=claude-haiku-5-5 prices=none")
    assert "lines news checked_found=0 checked_none=15 delayed=0 unsupported=0" in lines  # ETF 4개도 편입 종목 확인함·없음
    assert "hold -" in lines and "classify -" in lines


@pytest.mark.parametrize(
    "situation, day, block",
    [
        ("quiet", "2026-10-16", [
            'glance close delayed "Update delayed"',
            'glance indicator checked_none "No Fed decision or major BLS or BEA releases scheduled"',
            'glance market_news checked_none "No new major BLS, BEA, Census or Fed releases"',
            "glance review -",
            "glance hold - -",
        ]),
        ("gov_canary", "2026-10-29", [
            'glance close delayed "Update delayed"',
            'glance indicator checked_found "GDP 8:30 AM ET · Income and spending 8:30 AM ET"',
            f'glance market_news checked_found "Federal Reserve issued its {GOV_CANARY} statement"',
            "glance review pass",
            "glance hold - -",
        ]),
    ],
    ids=["발표_없는_날", "발표_있는_날"],
)
def test_운영_품질_확인은_품질_블록_끝에_시장_한눈에_세_줄·검수·보류를_모델과_함께_찍는다(settings, admin, situation, day, block):
    code, out = run_probe(settings, situation, extra=["--quality"], day=day)  # 로컬 DB 전용: 문장을 찍는 유일한 출력

    assert code == 0
    lines = out.splitlines()
    start = lines.index("glance model=claude-haiku-5-5")
    assert lines[start + 1:start + 6] == block
    assert lines.index("classify_counts kinds - importance - opinion=0 unclassified=0") < start


def test_예약_실행은_그_거래일에_완료된_실행이_있으면_카드·LLM_없이_ALREADY_DONE만_찍고_0으로_끝난다(settings, admin, store):
    admin.execute("insert into public.pipeline_run (trading_day, finished_at) values ('2026-10-16', now())")

    code, out = run_probe(settings, "quiet", trigger="schedule")  # 탐침 LLM은 불리면 RUN FAILED

    assert code == 0
    assert out == "ALREADY_DONE 2026-10-16\nfake_modules=[]\n"
    assert store.list_cards(FRI) == []
    assert admin.execute("select count(*) from public.pipeline_run").fetchone()[0] == 1  # 새 실행 기록 없음


@pytest.mark.parametrize("finished_at, day", [("null", "2026-10-16"), ("now()", "2026-10-15")], ids=["죽은_실행", "다른_거래일만_완료"])
def test_예약_실행은_그_거래일에_완료된_실행이_없으면_건너뛰지_않고_카드를_만든다(settings, admin, finished_at, day):
    admin.execute(f"insert into public.pipeline_run (trading_day, finished_at) values ('{day}', {finished_at})")

    code, out = run_probe(settings, "quiet", trigger="schedule", webhook=WEBHOOK_CANARY)

    assert code == 0
    assert "2026-10-16 cards_saved=15 resumed=- " in out
    assert "ALREADY_DONE" not in out
    # 정시 dispatch(pg_cron)가 그 거래일을 끝내지 못했다는 신호(#17 D7): 터미널과 Discord 메시지 첫 줄
    assert out.splitlines()[0] == webhook_message(out).splitlines()[2] == BACKUP_LINE


def test_예약_실행은_같은_거래일_실행이_진행_중이면_ALREADY_DONE이_아니라_LOCKED로_끝난다(settings, admin):
    admin.execute("insert into public.pipeline_run (trading_day) values ('2026-10-16')")  # 진행 중: finished_at 없음 + 잠금
    with connect(settings) as conn, CardStore(conn).run_lock(FRI):
        code, out = run_probe(settings, "quiet", trigger="schedule")

    assert code == 1
    # 끝난 실행이 없어 예비 실행이 돌기 시작했다(BACKUP RUN). GitHub 실행끼리는 concurrency로 줄을 서므로 잠금은 GitHub 밖 실행이다
    assert out == ("BACKUP RUN: no finished run when the GitHub schedule backup started (check pg_cron dispatch)\n"
                   "LOCKED: 2026-10-16 같은 거래일 실행이 이미 돌고 있어 종료합니다\nfake_modules=[]\n")


@pytest.mark.parametrize("trigger", ["workflow_dispatch", None], ids=["dispatch", "변수_없음"])
def test_dispatch·수동_실행은_완료된_실행이_있어도_카드를_다시_만든다(settings, admin, trigger):
    admin.execute("insert into public.pipeline_run (trading_day, finished_at) values ('2026-10-16', now())")

    code, out = run_probe(settings, "quiet", trigger=trigger)

    assert code == 0
    assert "2026-10-16 cards_saved=15 resumed=- " in out
    assert "ALREADY_DONE" not in out and BACKUP_LINE not in out


# Discord 실패 알림(#17 D3): 탐침이 notify._OPENER만 바꾼다. 실제 Discord를 부르지 않는다
def test_운영_실행은_Discord로_터미널과_같은_요약을_보내고_보냈다고_찍는다(settings, admin):
    code, out = run_probe(settings, "quiet", webhook=WEBHOOK_CANARY)

    assert code == 0
    lines = out.splitlines()
    content = webhook_message(out)
    assert content.splitlines()[:2] == ["OK morning 2026-10-16 exit=0", "```text"]
    summary = lines[:lines.index(next(line for line in lines if line.startswith("webhook_content=")))]
    assert content == "OK morning 2026-10-16 exit=0\n```text\n" + "\n".join(summary) + "\n```"  # 터미널 줄 그대로
    assert "prices=none" in summary
    assert lines[-2:] == ["discord: sent", "fake_modules=[]"]  # 상태 줄은 메시지를 만든 뒤라 메시지에 없다


def test_실패한_운영_실행의_Discord_메시지는_머리줄과_첫_줄에서_실패를_강조한다(settings, admin):
    code, out = run_probe(settings, "denied", webhook=WEBHOOK_CANARY)

    assert code == 1
    assert webhook_message(out).splitlines()[:3] == ["**FAILED** morning 2026-10-16 exit=1", "```text",
                                                    "!!! FAILED: failures=7 cards=15 !!!"]
    assert "discord: sent" in out.splitlines()


def test_Discord_보내기가_실패해도_실행_결과는_그대로이고_이유_코드만_찍는다(settings, admin):
    code, out = run_probe(settings, "webhook_down", webhook=WEBHOOK_CANARY)  # 오류의 주소·사유에 웹훅 주소. 캐너리 검사는 run_probe

    assert code == 0
    assert "2026-10-16 cards_saved=15 resumed=- " in out
    assert out.splitlines()[-2:] == ["discord: not sent (reason=http_500)", "fake_modules=[]"]


def test_Discord_웹훅_주소가_틀리면_보내지_않고_bad_url만_찍는다(settings, admin):
    code, out = run_probe(settings, "quiet", webhook=WEBHOOK_CANARY.replace("https://", "http://"))

    assert code == 0
    assert "webhook_content=" not in out
    assert out.splitlines()[-2:] == ["discord: not sent (reason=bad_url)", "fake_modules=[]"]


@pytest.mark.parametrize(
    "situation, day, tiingo_key, exit_code, block",
    [
        ("quiet", "2026-10-16", f"{TIINGO_CANARY}\n", 2, ["TIINGO_API_KEY must be one line of printable ASCII without spaces"]),
        ("db_lost", "2026-10-16", None, 1, ["RUN FAILED: OperationalError"]),
        ("quiet", "2099-10-16", None, 2, ["거래일 달력(trading_day.py)에 2099년 NYSE 휴장일이 없습니다. 표를 갱신하세요"]),
    ],
    ids=["설정_오류", "실행_중_DB_끊김", "달력_표_밖"],
)
def test_카드를_만들지_못하고_끝난_운영_실행도_Discord로_그_줄을_보낸다(settings, admin, situation, day, tiingo_key, exit_code, block):
    code, out = run_probe(settings, situation, tiingo_key=tiingo_key, webhook=WEBHOOK_CANARY, day=day)

    assert code == exit_code
    assert webhook_message(out) == f"**FAILED** morning {day} exit={exit_code}\n```text\n" + "\n".join(block) + "\n```"


def test_운영_실행이_LOCKED로_끝나면_Discord로_그_한_줄을_보낸다(settings, admin):
    with connect(settings) as conn, CardStore(conn).run_lock(FRI):
        code, out = run_probe(settings, "quiet", webhook=WEBHOOK_CANARY)

    assert code == 1
    assert webhook_message(out) == ("**FAILED** morning 2026-10-16 exit=1\n```text\n"
                                    "LOCKED: 2026-10-16 같은 거래일 실행이 이미 돌고 있어 종료합니다\n```")


@pytest.mark.parametrize("day, line", [("2026-11-26", "2026-11-26은 거래일이 아니라(주말·휴장일) 카드를 만들지 않습니다"),
                                       ("2026-10-16", "ALREADY_DONE 2026-10-16")], ids=["휴장일", "ALREADY_DONE"])
def test_휴장일과_이미_끝난_예비_실행은_Discord로_보내지_않는다(settings, admin, day, line):
    admin.execute("insert into public.pipeline_run (trading_day, finished_at) values ('2026-10-16', now())")

    code, out = run_probe(settings, "quiet", trigger="schedule", webhook=WEBHOOK_CANARY, day=day)

    assert code == 0
    assert out == f"{line}\nfake_modules=[]\n"  # 매일 오는 예비 실행 소음을 보내지 않는다


def test_품질_확인은_Discord로_보내지_않는다(settings, admin):
    code, out = run_probe(settings, "quiet", extra=["--quality"], webhook=WEBHOOK_CANARY)

    assert code == 0
    assert "webhook_content=" not in out and "discord:" not in out


def test_종목_하나의_예상_못_한_예외는_그_종목만_지연이고_Discord_실패_알림에_출처·대상·예외_이름이_간다(settings, admin):
    code, out = run_probe(settings, "ticker_crash", webhook=WEBHOOK_CANARY)  # 예외 메시지에 키. 캐너리 검사는 run_probe

    assert code == 1
    assert "2026-10-16 cards_saved=15 resumed=- " in out
    failed = "failed: sec_filings/0000320193=unexpected:ValueError"
    assert failed in out.splitlines()
    assert failed in webhook_message(out).splitlines()


def test_가짜_어댑터를_불러오는_운영_코드는_시나리오_모드_CLI_하나뿐이다():
    # fake_modules=[] 검사는 그 실행이 지난 경로만 본다: 공시가 있는 날에만 도는 함수 안 import는 놓친다(#26 R2)
    src = BACKEND / "src" / "m30"
    found = sorted(
        path.relative_to(src).as_posix() for path in src.rglob("*.py")
        if path != src / "adapters" / "fake.py" and re.search(r"adapters\.fake|adapters import[^\n]*\bfake\b", path.read_text())
    )
    assert found == ["pipeline/__main__.py"]
