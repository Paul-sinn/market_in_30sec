"""운영 모드(#26). 네트워크 없음, 로컬 DB.
입구 1: run_production. SEC는 기록용 get(test_edgar.RecordedGet), LLM은 부르면 실패하는 객체.
입구 3: 운영 CLI를 하위 프로세스(production_probe)로 돌려 exit 코드·출력을 본다. 바꾸는 것은 전송 층 둘(SEC get·LLM)뿐."""

import dataclasses
import os
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
from production_probe import COMPANY_CIKS, DRAFT_CANARY, ETFS, NoCallLLM, quiet_day
from test_edgar import RecordedGet
from test_nport import OTHER_SERIES, QQQ_8, QQQ_CIK, SCHD_8, SCHWAB_CIK, SPY_8, SPY_CIK, txt_url
from test_tiingo import body, row, source

FRI = date(2026, 10, 16)


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

    summary, refreshed = run_production(store, FRI, get=get, llm=NoCallLLM(), prices=NoPriceSource())

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


def test_운영_실행은_그_분기_기본_종목으로_실험_15종목을_저장한다(store):
    assert {"SPY", "QQQ"} <= set(EXPERIMENT_DEFAULT_TICKERS)  # 지수 대신 SPY·QQQ(부모 스펙: 선정 시 보장)
    experiment = sorted(COMPANY_CIKS | dict.fromkeys(ETFS))

    for _ in range(2):  # 재실행해도 그대로
        run_production(store, FRI, get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

        assert [c.ticker for c in store.list_generation_targets(date(2026, 10, 1))] == experiment  # 유저 0명 = 기본 종목
        assert [c.ticker for c in store.list_generation_targets(date(2026, 12, 31))] == experiment  # 2026Q4 끝까지
        assert store.list_generation_targets(date(2026, 9, 30)) == []  # 2026Q3에는 넣지 않았다


def test_운영_실행에_Tiingo_시세를_넣으면_15종목_모두_등락률과_세_번째_줄을_계산한다(store, monkeypatch):
    day = body(row("2026-10-14", 100), row("2026-10-15", 101))
    prices, opener = source(monkeypatch, dict.fromkeys(COMPANY_CIKS | dict.fromkeys(ETFS), day))

    summary, _ = run_production(store, FRI, get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=prices)

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
    run_production(store, FRI, get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())
    coverage, cards = store.list_coverage(), [content(c) for c in store.list_cards(FRI)]

    summary, _ = run_production(store, FRI, get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

    assert store.list_coverage() == coverage
    assert len(coverage) == 15
    assert [content(c) for c in store.list_cards(FRI)] == cards
    assert summary.cards_saved == 15


def test_첫_실행에서_SEC_티커_목록을_못_받으면_카드_0장이라_실패한_실행이다(store):
    get = RecordedGet({TICKERS_URL: SourceError("sec tickers shape")})

    summary, refreshed = run_production(store, FRI, get=get, llm=NoCallLLM(), prices=NoPriceSource())

    assert refreshed is False
    assert summary.cards_saved == 0
    assert run_failed(summary) is True
    assert get.urls == [TICKERS_URL]  # 다시 시도하지 않는다


def test_죽은_앞_실행이_카드를_모두_저장했으면_이어_한_실행은_카드_0장이어도_실패가_아니다(store):
    summary, _ = run_production(store, FRI, get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

    assert run_failed(dataclasses.replace(summary, cards_saved=0, resumed=("AAPL",))) is False
    assert run_failed(dataclasses.replace(summary, cards_saved=0, resumed=())) is True


def test_SEC_티커_목록을_못_받으면_지난_CIK로_카드를_만들고_실패로_치지_않는다(store):
    run_production(store, FRI, get=RecordedGet(quiet_day()), llm=NoCallLLM(), prices=NoPriceSource())

    summary, refreshed = run_production(
        store, FRI, get=RecordedGet(quiet_day(**{TICKERS_URL: TransientSourceError("sec timeout")})), llm=NoCallLLM(),
        prices=NoPriceSource(),
    )

    assert refreshed is False
    assert {c.ticker: c.cik for c in store.list_coverage()} == COMPANY_CIKS | dict.fromkeys(ETFS)
    assert summary.cards_saved == 15
    assert run_failed(summary) is False


def test_SEC가_403으로_막아도_카드는_나가지만_실패한_실행이다(store):
    get = RecordedGet(quiet_day(**{SUBMISSIONS_URL.format(cik=COMPANY_CIKS["AAPL"]): AccessDeniedError("sec http 403")}))

    summary, _ = run_production(store, FRI, get=get, llm=NoCallLLM(), prices=NoPriceSource())

    assert summary.access_denied == (Source.SEC_FILINGS,)
    cards = {c.ticker: c for c in store.list_cards(FRI)}
    assert len(cards) == summary.cards_saved == 15  # 가용성은 열린 쪽
    assert cards["AAPL"].news_line.status is LineStatus.DELAYED  # 못 받은 것을 "없음"으로 두지 않는다
    assert run_failed(summary) is True


# 입구 3: 운영 CLI 하위 프로세스. 비밀값 자리는 캐너리(전송 층을 바꿨으니 어디로도 가지 않는다)
BACKEND = Path(__file__).resolve().parent.parent
KEY_CANARY, UA_CANARY = "sk-ant-KeyCanary93", "M30 Canary uaCanary41@example.invalid"
TIINGO_CANARY = "tiingoKeyCanary57"


def run_probe(settings, situation, tiingo_key=None, extra=(), trigger=None):
    """tiingo_key가 없으면 TIINGO_API_KEY를 뺀 환경(구독 전). 셸에 진짜 키가 있어도 하위 프로세스로 넘기지 않는다. extra = 덧붙일 CLI 인자.
    trigger = 워크플로가 넘기는 RUN_TRIGGER(github.event_name). 없으면 변수 없이(로컬 실행)."""
    env = {k: v for k, v in os.environ.items() if k not in ("TIINGO_API_KEY", "RUN_TRIGGER")} | {
        "SUPABASE_DB_URL": settings.database_url, "ANTHROPIC_API_KEY": KEY_CANARY, "SEC_USER_AGENT": UA_CANARY
    } | ({"TIINGO_API_KEY": tiingo_key} if tiingo_key else {}) | ({"RUN_TRIGGER": trigger} if trigger else {})
    r = subprocess.run([sys.executable, "tests/production_probe.py", situation, "--production", "2026-10-16", *extra],
                       cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    assert KEY_CANARY not in out and UA_CANARY not in out and TIINGO_CANARY not in out
    assert out.endswith("fake_modules=[]\n")  # 실행한 운영 경로 어디서도(함수 안 import 포함) 가짜 어댑터를 불러오지 않았다
    return r.returncode, out


@pytest.mark.parametrize(
    "situation, exit_code, lines",
    [
        ("quiet", 0, ["2026-10-16 cards_saved=15 resumed=- ", "coverage: refreshed", "prices=none",
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

    code, out = run_probe(settings, "quiet", trigger="schedule")

    assert code == 0
    assert "2026-10-16 cards_saved=15 resumed=- " in out
    assert "ALREADY_DONE" not in out


def test_예약_실행은_같은_거래일_실행이_진행_중이면_ALREADY_DONE이_아니라_LOCKED로_끝난다(settings, admin):
    admin.execute("insert into public.pipeline_run (trading_day) values ('2026-10-16')")  # 진행 중: finished_at 없음 + 잠금
    with connect(settings) as conn, CardStore(conn).run_lock(FRI):
        code, out = run_probe(settings, "quiet", trigger="schedule")

    assert code == 1
    assert out == "LOCKED: 2026-10-16 같은 거래일 실행이 이미 돌고 있어 종료합니다\nfake_modules=[]\n"


@pytest.mark.parametrize("trigger", ["workflow_dispatch", None], ids=["dispatch", "변수_없음"])
def test_dispatch·수동_실행은_완료된_실행이_있어도_카드를_다시_만든다(settings, admin, trigger):
    admin.execute("insert into public.pipeline_run (trading_day, finished_at) values ('2026-10-16', now())")

    code, out = run_probe(settings, "quiet", trigger=trigger)

    assert code == 0
    assert "2026-10-16 cards_saved=15 resumed=- " in out
    assert "ALREADY_DONE" not in out
