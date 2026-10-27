"""운영 모드(#26). 네트워크 없음, 로컬 DB.
입구 1: run_production. SEC는 기록용 get(test_edgar.RecordedGet), LLM은 부르면 실패하는 객체.
입구 3: 운영 CLI를 하위 프로세스(production_probe)로 돌려 exit 코드·출력을 본다. 바꾸는 것은 전송 층 둘(SEC get·LLM)뿐."""

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
from m30.models import LineStatus
from m30.pipeline.lines import NEWS_SCOPE, NO_FILINGS, NOT_COVERED, PRICE_SCOPE, UPDATE_DELAYED
from m30.pipeline.production import run_failed, run_production
from production_probe import COMPANY_CIKS, DRAFT_CANARY, ETFS, NoCallLLM, quiet_day
from test_edgar import RecordedGet
from test_tiingo import body, row, source

FRI = date(2026, 10, 16)


def lines(card):
    return {
        name: (line.text, line.status, line.source_scope)
        for name, line in (("news", card.news_line), ("event", card.event_line), ("price", card.price_fact_line))
    }


def test_운영_실행은_실제_공시와_미연결_출처만_써서_가짜_데이터_없이_카드를_만든다(store):
    get = RecordedGet(quiet_day())

    summary, refreshed = run_production(store, FRI, get=get, llm=NoCallLLM(), prices=NoPriceSource())

    assert refreshed is True
    assert {c.ticker: c.cik for c in store.list_coverage()} == COMPANY_CIKS | dict.fromkeys(ETFS)
    cards = store.list_cards(FRI)
    assert len(cards) == summary.cards_saved == 15
    for card in cards:
        assert (card.change_pct, card.change_status) == (None, LineStatus.DELAYED)  # 시세 출처 없음(#18 전)
        news = (NOT_COVERED, LineStatus.UNSUPPORTED, None) if card.ticker in ETFS else (NO_FILINGS, LineStatus.CHECKED_NONE, NEWS_SCOPE)
        assert lines(card) == {
            "news": news,
            "event": (NOT_COVERED, LineStatus.UNSUPPORTED, None),  # 일정 출처 없음(#21 전) = 미지원
            "price": (UPDATE_DELAYED, LineStatus.DELAYED, PRICE_SCOPE),
        }, card.ticker
    assert summary.failures == ()
    assert summary.llm_calls == 0
    assert run_failed(summary) is False
    assert store.list_raw_indicators(FRI) == []
    assert get.urls == [TICKERS_URL] + [SUBMISSIONS_URL.format(cik=cik) for cik in sorted(COMPANY_CIKS.values())]


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


def run_probe(settings, situation, tiingo_key=None):
    """tiingo_key가 없으면 TIINGO_API_KEY를 뺀 환경(구독 전). 셸에 진짜 키가 있어도 하위 프로세스로 넘기지 않는다."""
    env = {k: v for k, v in os.environ.items() if k != "TIINGO_API_KEY"} | {
        "SUPABASE_DB_URL": settings.database_url, "ANTHROPIC_API_KEY": KEY_CANARY, "SEC_USER_AGENT": UA_CANARY
    } | ({"TIINGO_API_KEY": tiingo_key} if tiingo_key else {})
    r = subprocess.run([sys.executable, "tests/production_probe.py", situation, "--production", "2026-10-16"],
                       cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    assert KEY_CANARY not in out and UA_CANARY not in out and TIINGO_CANARY not in out
    assert out.endswith("fake_modules=[]\n")  # 실행한 운영 경로 어디서도(함수 안 import 포함) 가짜 어댑터를 불러오지 않았다
    return r.returncode, out


@pytest.mark.parametrize(
    "situation, exit_code, lines",
    [
        ("quiet", 0, ["2026-10-16 cards_saved=15 ", "coverage: refreshed", "prices=none"]),
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
        ("tiingo_quiet", 0, ["2026-10-16 cards_saved=15 change_delayed=-", "prices=tiingo"]),
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


def test_운영_CLI는_TIINGO_API_KEY가_한_줄_ASCII가_아니면_DB에_붙기_전에_변수_이름만_찍고_2로_끝난다(settings, admin):
    code, out = run_probe(settings, "quiet", tiingo_key=f"{TIINGO_CANARY}\n")

    assert code == 2
    assert out == "TIINGO_API_KEY must be one line of printable ASCII without spaces\nfake_modules=[]\n"
