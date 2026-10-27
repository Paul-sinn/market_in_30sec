"""python -m m30.pipeline 2026-10-16 --scenario scenarios/first_card.json   로컬 개발: 가짜 출처, 로컬 DB만
python -m m30.pipeline --production [YYYY-MM-DD]                          운영: 실제·미연결 출처, 원격 DB 허용, 비우면 오늘(ET)"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from m30.adapters.edgar import EdgarClient
from m30.adapters.tiingo import TiingoPriceSource
from m30.adapters.unavailable import NoPriceSource
from m30.config import (
    DB_URL_VAR,
    ET,
    ConfigError,
    is_local_db,
    load_edgar_settings,
    load_llm_settings,
    load_settings,
    load_tiingo_settings,
)
from m30.db.store import CardStore, DBConnectError, connect
from m30.llm.anthropic import AnthropicLLM
from m30.pipeline.collect import filing_window
from m30.pipeline.morning import MorningPipeline, RunSummary
from m30.pipeline.production import run_failed, run_production


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m m30.pipeline", description="아침 파이프라인 실행")
    parser.add_argument("trading_day", nargs="?", type=date.fromisoformat, help="거래일 YYYY-MM-DD (동부 기준)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", type=Path, help="가짜 시나리오 JSON 경로 (로컬 DB만)")
    mode.add_argument("--production", action="store_true", help="실제 출처로 실행. 원격 DB를 쓸 수 있는 유일한 모드")
    args = parser.parse_args(argv)
    if args.production:
        return _production(args.trading_day)
    if args.trading_day is None:
        parser.error("trading_day is required with --scenario")

    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"{e}. 레포 루트에서 supabase start 후 README의 export 줄을 실행하세요", file=sys.stderr)
        return 2
    if not is_local_db(settings.database_url):
        # 가짜 카드를 쓰므로 원격 DB면 실험 데이터를 오염시킨다. 주소는 출력하지 않는다
        print(f"{DB_URL_VAR}이 로컬 DB가 아니라 중단합니다", file=sys.stderr)
        return 2

    # 운영 프로세스가 가짜 출처를 불러오지 않게 시나리오 모드에서만 import한다
    from m30.adapters.fake import (
        FakeEventSource,
        FakeFilingSource,
        FakeIndicatorSource,
        FakeLLM,
        FakePriceSource,
        load_scenario,
    )

    scenario = load_scenario(args.scenario)
    with connect(settings) as conn:
        store = CardStore(conn)
        store.upsert_coverage(scenario.coverage)
        summary = MorningPipeline(
            prices=FakePriceSource(scenario),
            events=FakeEventSource(scenario),
            filings=FakeFilingSource(scenario),
            indicators=FakeIndicatorSource(scenario),
            llm=FakeLLM(scenario),
            store=store,
        ).run(args.trading_day)
    _print_summary(summary)
    return 0


def _print_summary(summary: RunSummary) -> None:
    """결과 코드·건수·티커만. 레포가 공개라 Actions 로그도 공개다: 카드 문장·가격·URL·키·환경 변수 값을 찍지 않는다."""
    # 예외 메시지·URL·키는 찍지 않는다. 401·403은 맨 위(터미널 강조·Discord는 #17)
    if summary.access_denied:
        print(f"ACCESS DENIED (not retried): {', '.join(summary.access_denied)}")
    if summary.rate_limited:
        print(f"RATE LIMITED (429, retried): {', '.join(summary.rate_limited)}")
    delayed = ", ".join(summary.change_delayed) or "-"
    print(f"{summary.trading_day} cards_saved={summary.cards_saved} change_delayed={delayed}")
    skipped = ", ".join(f"{b.number}:{b.reason}" for b in summary.skipped_batches) or "-"
    print(
        f"filings={summary.filings_collected} unclassified={summary.filings_unclassified}"
        f" batches={summary.classify_batches} skipped={skipped} llm_calls={summary.llm_calls}/{summary.llm_call_limit}"
    )
    print("news: " + " ".join(f"{ticker}={n.status}" for ticker, n in summary.news.items()))
    # 문장은 찍지 않는다(통과한 줄은 카드에, 걸린 줄은 보류함에 있다). 종목별 결과 코드만
    drafts = " ".join(f"{ticker}={d.problem or 'ok'}" for ticker, d in summary.drafts.items()) or "-"
    print(f"drafts: {drafts}")
    reviews = " ".join(
        f"{ticker}={'pass' if r.stage is None else f'hold:{r.stage}'}{'+retry' if r.retried else ''}"
        for ticker, r in summary.reviews.items()
    ) or "-"
    print(f"review: {reviews}")
    if summary.failures:
        print("failed: " + ", ".join(
            f"{f.source}/{f.subject}={f.reason}" if f.subject else f"{f.source}={f.reason}" for f in summary.failures
        ))


def _production(requested: date | None) -> int:
    """날짜 확인 → 설정 → DB 연결 → CIK 갱신·파이프라인(SEC·Anthropic·Tiingo) → 요약 → exit 코드. 외부 출처는 DB 연결 뒤에만 부른다.
    시세: TIINGO_API_KEY가 있으면 Tiingo, 없으면(유료 구독 전) 시세 없이(등락률·세 번째 줄 지연)."""
    now = datetime.now(ET)
    day = requested or now.date()
    if day.weekday() >= 5:  # 휴장일 달력은 #16이 같은 규칙(exit 0)으로 넓힌다
        print(f"{day}은 주말이라 카드를 만들지 않습니다")
        return 0
    if now < filing_window(day)[1]:  # 미래 날짜 오타·밤늦은 PT 실행이 원격에 카드를 만들지 않게
        print(f"{day} 공시 기간은 그날 04:00 ET에 닫힙니다. 그 뒤에 실행하거나 지난 거래일을 넣으세요", file=sys.stderr)
        return 2
    try:  # DB·외부 출처에 닿기 전에 모두 확인한다. 메시지에는 변수 이름만 있다
        settings, llm_settings, edgar_settings = load_settings(), load_llm_settings(), load_edgar_settings()
        tiingo_settings = load_tiingo_settings()
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        with connect(settings) as conn:
            summary, refreshed = run_production(
                CardStore(conn),
                day,
                get=EdgarClient(edgar_settings).get,
                llm=AnthropicLLM(llm_settings),
                prices=TiingoPriceSource(tiingo_settings) if tiingo_settings else NoPriceSource(),
            )
    except (ConfigError, DBConnectError) as e:  # 우리가 쓴 문구(변수 이름·포트만): 6543 거부, 연결 실패
        print(e, file=sys.stderr)
        return 2 if isinstance(e, ConfigError) else 1
    except Exception as e:
        # 공개 로그: str(e)·traceback에는 서버 오류 DETAIL(행 내용 = 검수 전 문장)이나 라이브러리가 넣은 키가 섞일 수 있다
        sqlstate = getattr(e, "sqlstate", None)
        print(f"RUN FAILED: {type(e).__name__}" + (f" sqlstate={sqlstate}" if sqlstate else ""), file=sys.stderr)
        return 1
    _print_summary(summary)
    print("coverage: refreshed" if refreshed else "coverage: NOT REFRESHED (sec ticker list failed), stored rows used")
    print("prices=tiingo" if tiingo_settings else "prices=none")  # none = TIINGO_API_KEY 없음(구독 전)
    return 1 if run_failed(summary) else 0


if __name__ == "__main__":
    sys.exit(main())
