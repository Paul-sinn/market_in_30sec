"""운영 모드(#26): 실제 출처(EDGAR·Anthropic·시세) + 미연결 출처. 원격 DB로 가는 유일한 길(CLI --production).
가짜 어댑터·시나리오를 import하지 않는다(테스트가 sys.modules로 확인)."""

from datetime import date

from m30.adapters import SourceError
from m30.adapters.edgar import EdgarFilingSource, Get, ticker_ciks
from m30.adapters.prices import PriceSource
from m30.adapters.unavailable import NoEventSource, NoIndicatorSource
from m30.db.store import CardStore
from m30.experiment import EXPERIMENT_DEFAULT_TICKERS, experiment_coverage
from m30.llm import LLM
from m30.pipeline.morning import MorningPipeline, RunSummary


def run_production(
    store: CardStore, trading_day: date, *, get: Get, llm: LLM, prices: PriceSource
) -> tuple[RunSummary, bool]:
    """(실행 요약, CIK를 갱신했는지). CIK 갱신이 실패하면(SourceError) 다시 시도하지 않고 지난 행을 쓴다(#19 U2).
    커버 범위는 upsert만 한다(행을 지우지 않는다). 그 분기 기본 종목에 실험 15종목을 더한다(#8, 멱등).
    prices: Tiingo, 키가 없으면(구독 전) NoPriceSource(#18)."""
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
        indicators=NoIndicatorSource(),
        llm=llm,
        store=store,
    ).run(trading_day)
    return summary, refreshed


def run_failed(summary: RunSummary) -> bool:
    """워크플로를 실패로 끝낼 실행: 재시도 뒤에도 실패한 호출(401·403 포함)이 있거나 카드 0장(이어 하기로 건너뛴 카드도 0장).
    미연결 출처는 실패를 남기지 않는다. 429 뒤 성공·건너뛴 분류 묶음·보류함은 실패가 아니다."""
    return bool(summary.failures) or summary.cards_saved + len(summary.resumed) == 0
