"""운영 모드(#26): 실제 출처(EDGAR·정부 기관·Anthropic·시세) + 미연결 출처. 원격 DB로 가는 길은 CLI --production(이 모듈)과 --quarterly(분기 작업) 둘뿐이다.
가짜 어댑터·시나리오를 import하지 않는다(테스트가 sys.modules로 확인)."""

from dataclasses import dataclass, replace
from datetime import date
from functools import cache
from importlib.resources.abc import Traversable
from pathlib import Path

from m30.adapters import SourceError
from m30.adapters.edgar import EdgarEarningsFilingSource, EdgarFilingSource, Get, ticker_ciks
from m30.adapters.gov import GovIndicatorSource
from m30.adapters.gov_news import GovNewsSource
from m30.adapters.nport import EdgarHoldingsSource, issuer_ciks, issuer_key
from m30.adapters.prices import PriceSource
from m30.adapters.unavailable import NoEventSource
from m30.db.store import CardStore
from m30.coverage import DEFAULT_TICKERS, ETF_LIST, SP500_FUND, load_etfs, sp500_stocks
from m30.llm import LLM
from m30.pipeline.morning import MorningPipeline, RunSummary, run_failed  # noqa: F401 (run_failed: 호출부가 여기서 import)


@dataclass(frozen=True)
class CoverageRefresh:
    reason: str | None = None  # None = 갱신함. "etf_list_invalid" | "sec_tickers_failed" = 아무 행도 쓰지 않음(지난 행 그대로)
    etfs: int = 0  # upsert한 ETF 행 수
    stocks: int = 0  # SPY 보고로 만든 주식 행 수(ETF와 겹친 티커 제외)
    added: int = 0  # 그중 새로 넣은 행 수
    unmatched: int = 0  # SPY 보통주 회사 중 티커를 못 찾은 수
    sp500_period_end: date | None = None  # 쓴 SPY 보고 기준일. None = 저장된 보고 없음(주식 행 안 건드림)


def refresh_coverage(store: CardStore, get: Get, etf_list: Traversable | Path = ETF_LIST) -> CoverageRefresh:
    """커버 범위 갱신(#58 D6). ETF 목록 읽기 → SEC 티커 목록(요청 1회) → ETF 행 upsert → 저장된 SPY 최신 보고 → 주식 행 추가만.
    보고의 보유 회사 CIK는 저장된 값을 쓰지 않고 같은 티커 목록에서 이름(issuer_key)으로 다시 맞춘다: 저장 시점의 이름 규칙과
    무관하게 지금 규칙 한 벌. 못 맞추면 CIK 없음(못 찾음). 저장된 보고 행은 고치지 않는다.
    ETF 목록이 틀리면(ValueError·OSError) etf_list_invalid, 티커 목록 SourceError면 sec_tickers_failed: 둘 다 아무 행도 쓰지 않고
    다시 시도하지 않는다(#19 U2). 주식 티커가 ETF 목록 티커와 같으면 ETF가 이긴다. 거래일과 무관하다(같은 입력이면 같은 행).
    DB 오류는 잡지 않는다."""
    try:
        etfs = load_etfs(etf_list)
    except (ValueError, OSError):
        return CoverageRefresh("etf_list_invalid")
    listing = cache(get)  # 티커·이름 두 규칙이 응답 하나를 같이 쓴다
    try:
        ciks, issuers = ticker_ciks(listing), issuer_ciks(listing)
    except SourceError:
        return CoverageRefresh("sec_tickers_failed")
    store.upsert_coverage(etfs)
    if (report := store.latest_holdings(SP500_FUND)) is None:  # 빈 DB 첫 실행: 파이프라인 편입 단계가 저장한 뒤 다음 실행부터
        return CoverageRefresh(etfs=len(etfs))
    holdings = tuple(replace(h, cik=issuers.get(issuer_key(h.name))) for h in report.holdings)
    found, unmatched = sp500_stocks(replace(report, holdings=holdings), ciks)
    etf_tickers = {e.ticker for e in etfs}
    stocks = [s for s in found if s.ticker not in etf_tickers]
    return CoverageRefresh(None, len(etfs), len(stocks), store.add_coverage(stocks), unmatched, report.period_end)


def run_production(
    store: CardStore, trading_day: date, *, get: Get, gov_get: Get, llm: LLM, prices: PriceSource | None
) -> tuple[RunSummary, CoverageRefresh]:
    """(실행 요약, 커버 범위 갱신 결과). refresh_coverage → 그 분기 기본 종목에 DEFAULT_TICKERS를 더함(#8, 멱등) → 파이프라인.
    커버 범위는 추가만 한다(행을 지우지 않는다). 생성 대상(활성 종목 ∪ 기본 종목)은 커버 범위와 무관하다.
    ETF 편입 종목은 SEC N-PORT(#10). 편입 어댑터는 티커 목록을 자기 인스턴스에서 따로 받는다(갱신이 필요한 날만 요청 1회 더).
    prices: None = 가격 표시 off(#56). on이면 Tiingo, 키가 없으면(구독 전) NoPriceSource(#18). gov_get: 정부 기관 창구(GovClient.get, #50). SEC get과 따로 둔다."""
    refresh = refresh_coverage(store, get, ETF_LIST)  # 모듈 이름을 부를 때 읽는다(테스트가 목록 파일을 바꿔 끼운다)
    store.add_default_tickers(trading_day, DEFAULT_TICKERS)  # 빈 DB 첫 실행 + 갱신 실패면 0개 → 카드 0장
    summary = MorningPipeline(
        prices=prices,
        events=NoEventSource(),
        earnings=EdgarEarningsFilingSource(get),  # #57: 과거 실적 공시로 실적 추정일. 같은 SEC get·간격 조절
        filings=EdgarFilingSource(get),
        indicators=GovIndicatorSource(gov_get),  # #50: BLS·BEA 일정 + FOMC 표
        holdings=EdgarHoldingsSource(get),  # #10 B: live 게이트(test_holdings_live) 통과 뒤 연결
        market_news=GovNewsSource(gov_get),  # #50: BLS·BEA·Census·연준 발표
        llm=llm,
        store=store,
    ).run(trading_day)
    return summary, refresh
