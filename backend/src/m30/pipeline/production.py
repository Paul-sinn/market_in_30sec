"""운영 모드(#26): 실제 출처(EDGAR·정부 기관·Anthropic·시세) + 미연결 출처. 원격 DB로 가는 유일한 길(CLI --production).
가짜 어댑터·시나리오를 import하지 않는다(테스트가 sys.modules로 확인)."""

from datetime import date

from m30.adapters import SourceError
from m30.adapters.edgar import EdgarFilingSource, Get, ticker_ciks
from m30.adapters.gov import GovIndicatorSource
from m30.adapters.gov_news import GovNewsSource
from m30.adapters.nport import EdgarHoldingsSource
from m30.adapters.prices import PriceSource
from m30.adapters.unavailable import NoEventSource
from m30.db.store import CardStore
from m30.experiment import EXPERIMENT_DEFAULT_TICKERS, experiment_coverage
from m30.llm import LLM
from m30.pipeline.morning import MorningPipeline, RunSummary, run_failed  # noqa: F401 (run_failed: 호출부가 여기서 import)


def run_production(
    store: CardStore, trading_day: date, *, get: Get, gov_get: Get, llm: LLM, prices: PriceSource
) -> tuple[RunSummary, bool]:
    """(실행 요약, CIK를 갱신했는지). CIK 갱신이 실패하면(SourceError) 다시 시도하지 않고 지난 행을 쓴다(#19 U2).
    ETF 편입 종목은 SEC N-PORT(#10). 편입 어댑터는 티커 목록을 자기 인스턴스에서 따로 받는다(갱신이 필요한 날만 요청 1회 더).
    커버 범위는 upsert만 한다(행을 지우지 않는다). 그 분기 기본 종목에 실험 15종목을 더한다(#8, 멱등).
    prices: Tiingo, 키가 없으면(구독 전) NoPriceSource(#18). gov_get: 정부 기관 창구(GovClient.get, #50). SEC get과 따로 둔다."""
    try:
        store.upsert_coverage(experiment_coverage(ticker_ciks(get)))
        refreshed = True
    except SourceError:
        refreshed = False
    store.add_default_tickers(trading_day, EXPERIMENT_DEFAULT_TICKERS)  # 빈 DB 첫 실행 + 티커 목록 실패면 0개 → 카드 0장
    summary = MorningPipeline(
        prices=prices,
        events=NoEventSource(),
        filings=EdgarFilingSource(get),
        indicators=GovIndicatorSource(gov_get),  # #50: BLS·BEA 일정 + FOMC 표
        holdings=EdgarHoldingsSource(get),  # #10 B: live 게이트(test_holdings_live) 통과 뒤 연결
        market_news=GovNewsSource(gov_get),  # #50: BLS·BEA·Census·연준 발표
        llm=llm,
        store=store,
    ).run(trading_day)
    return summary, refreshed
