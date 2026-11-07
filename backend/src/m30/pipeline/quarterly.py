"""분기 작업(#60, HANDOFF 3-6 "분기마다" 행): 아침 실행과 따로 돈다(quarterly.yml, 매주 일요일).
아침 실행 잠금·pipeline_run을 쓰지 않는다: 쓰는 곳은 sec_annual_report(추가만)·coverage.sic 한 열·연관 종목 두 표(#64)뿐이다.
단계: 10-K 수집 + 업종 코드 → 연관 종목(#64). #66(알아두기)이 단계를 더한다."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from m30.adapters import Source, SourceError
from m30.adapters.filings import AnnualReportSource
from m30.db.store import CardStore
from m30.llm import LLM
from m30.pipeline.collect import SourceCalls, SourceFailure, valid_annual_report, valid_annual_report_listing
from m30.pipeline.relations import RelationSummary, map_relations

QUARTERLY_LLM_CALL_LIMIT = 200  # #64 U3: 실행당 Sonnet 호출 상한. 첫 채우기(약 500개 회사)는 실행 3번. #66이 알아두기 몫을 정할 때 같이 본다


@dataclass(frozen=True)
class QuarterlySummary:
    companies: int  # 대상 회사 수 = 커버 범위에서 cik가 있고 holdings_ticker가 없는 행의 서로 다른 CIK
    new: int  # 이번에 저장한 10-K 수
    unchanged: int  # 최신 10-K가 이미 저장돼 있어 받지 않았거나, 받았지만 이미 있던 회사 수
    no_annual_report: int  # submissions recent에 10-K가 없는 회사 수(실패 아님)
    sic: int  # sic를 쓴 회사 수(같은 값으로 다시 쓴 것 포함)
    sic_missing: int  # submissions를 받았지만 쓸 수 있는 sic가 없던 회사 수(실패 아님, 지난 값 유지)
    failures: tuple[SourceFailure, ...]  # 회사 단위(대상 = CIK), 회사당 최대 1건
    access_denied: tuple[Source, ...]
    rate_limited: tuple[Source, ...]
    relations: RelationSummary  # #64. 위 9개는 10-K 수집만 센다
    # 늘 성립: companies == new + unchanged + no_annual_report + len(failures)


def run_quarterly(
    store: CardStore, *, reports: AnnualReportSource, llm: LLM, sleep: Callable[[float], None] = time.sleep,
    llm_call_limit: int = QUARTERLY_LLM_CALL_LIMIT,
) -> QuarterlySummary:
    """대상 회사를 CIK 순으로: listing → sic 있으면 set_coverage_sic(없으면 지난 값 유지) → 10-K 없으면 no_annual_report
    → 저장된 최신 접수번호와 같으면 받지 않음 → annual_report → save_annual_report. 회사 하나의 실패는 그 회사만 건너뛴다.
    그다음 map_relations(10-K 수집 실패가 있어도 저장된 것으로 돈다). DB 오류·AssertionError는 그대로 올린다. 잠금·실행 기록 없음."""
    calls = SourceCalls(sleep)
    ciks = sorted({c.cik for c in store.list_coverage() if c.cik is not None and c.holdings_ticker is None})
    stored = store.latest_annual_reports()
    new = unchanged = none = sic = sic_missing = 0
    for cik in ciks:
        try:
            listing = calls.call(Source.ANNUAL_REPORT, cik, lambda: reports.listing(cik), valid_annual_report_listing)
        except SourceError:
            continue
        if listing.sic is None:
            sic_missing += 1
        else:
            store.set_coverage_sic(cik, listing.sic)
            sic += 1
        if listing.accession is None:
            none += 1
            continue
        if stored.get(cik) == listing.accession:
            unchanged += 1
            continue
        try:
            report = calls.call(
                Source.ANNUAL_REPORT, cik, lambda: reports.annual_report(cik, listing.accession),
                lambda r: valid_annual_report(r, cik, listing.accession),
            )
        except SourceError:
            continue
        if store.save_annual_report(report):
            new += 1
        else:
            unchanged += 1
    relations = map_relations(store, llm, limit=llm_call_limit, sleep=sleep)
    return QuarterlySummary(len(ciks), new, unchanged, none, sic, sic_missing, calls.failures, calls.access_denied,
                            calls.rate_limited, relations)


def quarterly_failed(summary: QuarterlySummary) -> bool:
    """워크플로를 실패로 끝낼 실행: 회사 실패가 있거나 대상 회사가 0개(빈·잘못된 DB), 또는 LLM 전송 실패(#64).
    아침 실행의 '카드 0장 = 실패'와 같은 뜻. json_invalid·deferred·no_item1은 실패가 아니다(다음 실행이 다시 본다)."""
    return bool(summary.failures) or summary.companies == 0 or bool(summary.relations.failures)
