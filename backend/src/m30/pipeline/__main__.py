"""python -m m30.pipeline 2026-10-16 --scenario scenarios/first_card.json   로컬 개발: 가짜 출처, 로컬 DB만
python -m m30.pipeline --production [YYYY-MM-DD]                          운영: 실제·미연결 출처, 원격 DB 허용, 비우면 오늘(ET)
둘 다 --quality: 실제 Haiku로 돌리고 카드 문장·초안·보류함·분류를 찍는다. 로컬 DB만(#14)"""

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

from m30.adapters.edgar import EdgarClient
from m30.adapters.tiingo import TiingoPriceSource
from m30.adapters.unavailable import NoPriceSource
from m30.config import (
    CLASSIFY_MODEL,
    DB_URL_VAR,
    ET,
    NEWSLINE_MODEL,
    REVIEW_MODEL,
    ConfigError,
    is_local_db,
    load_discord_settings,
    load_edgar_settings,
    load_llm_settings,
    load_settings,
    load_tiingo_settings,
)
from m30.db.store import CardStore, DBConnectError, RunLocked, connect
from m30.llm.anthropic import AnthropicLLM
from m30.models import LineStatus, NewsKind
from m30.notify import discord_content, send_discord
from m30.pipeline.collect import FailureReason, error_name, filing_window
from m30.pipeline.morning import MorningPipeline, RunSummary
from m30.pipeline.production import run_failed, run_production
from m30.trading_day import CalendarError, is_trading_day


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m m30.pipeline", description="아침 파이프라인 실행")
    parser.add_argument("trading_day", nargs="?", type=date.fromisoformat, help="거래일 YYYY-MM-DD (동부 기준)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", type=Path, help="가짜 시나리오 JSON 경로 (로컬 DB만)")
    mode.add_argument("--production", action="store_true", help="실제 출처로 실행. 원격 DB를 쓸 수 있는 유일한 모드")
    parser.add_argument("--quality", action="store_true",
                        help="실제 Haiku로 돌리고 카드 문장·초안·보류함·분류를 찍는다. 로컬 DB만")
    args = parser.parse_args(argv)
    if args.production:
        return _production(args.trading_day, args.quality)
    if args.trading_day is None:
        parser.error("trading_day is required with --scenario")
    if (code := _not_trading_day(args.trading_day)) is not None:
        return code

    if args.quality:  # DB 설정·연결보다 먼저. 메시지에는 변수 이름만 있다
        try:
            llm_settings = load_llm_settings()
        except ConfigError as e:
            print(e, file=sys.stderr)
            return 2
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
        FakeHoldingsSource,
        FakeIndicatorSource,
        FakeLLM,
        FakeMarketNewsSource,
        FakePriceSource,
        load_scenario,
    )

    scenario = load_scenario(args.scenario)
    try:
        with connect(settings) as conn:
            store = CardStore(conn)
            store.upsert_coverage(scenario.coverage)
            store.add_default_tickers(args.trading_day, [c.ticker for c in scenario.coverage])  # 유저 없음 → 시나리오 커버 범위 전체가 대상
            summary = MorningPipeline(
                prices=FakePriceSource(scenario),
                events=FakeEventSource(scenario),
                filings=FakeFilingSource(scenario),
                indicators=FakeIndicatorSource(scenario),
                holdings=FakeHoldingsSource(scenario),
                market_news=FakeMarketNewsSource(scenario),
                llm=AnthropicLLM(llm_settings) if args.quality else FakeLLM(scenario),  # 품질 확인은 llm_replies를 쓰지 않는다
                store=store,
            ).run(args.trading_day)
            quality = _quality_lines(summary, store, "scenario") if args.quality else []
    except RunLocked:
        print(LOCKED.format(args.trading_day), file=sys.stderr)
        return 1
    _print_summary(summary)
    for line in quality:
        print(line)
    return 0


LOCKED = "LOCKED: {} 같은 거래일 실행이 이미 돌고 있어 종료합니다"  # 공개 로그: 날짜만


def _not_trading_day(day: date, say: Callable[..., None] = print) -> int | None:
    """설정 읽기·DB 연결 전 거래일 확인. 거래일이면 None, 주말·휴장일이면 0(카드 없음이 정상), 달력 표 밖이면 2."""
    try:
        if is_trading_day(day):
            return None
    except CalendarError as e:
        say(f"거래일 달력(trading_day.py)에 {e.year}년 NYSE 휴장일이 없습니다. 표를 갱신하세요", file=sys.stderr)
        return 2
    say(f"{day}은 거래일이 아니라(주말·휴장일) 카드를 만들지 않습니다")
    return 0


def _print_summary(summary: RunSummary, say: Callable[[str], None] = print) -> None:
    """결과 코드·건수·티커만. 레포가 공개라 Actions 로그도 공개다: 카드 문장·가격·URL·키·환경 변수 값을 찍지 않는다.
    실패한 실행이면 맨 위에 배너와 실패 목록(#17 D4). Discord 메시지도 이 줄 그대로다."""
    if run_failed(summary):
        failures = len(summary.failures) + len(summary.ticker_errors)
        say(f"!!! FAILED: failures={failures} cards={summary.cards_saved + len(summary.resumed)} !!!")
        if failures:  # 예외 메시지·URL·키는 찍지 않는다. 코드와 예외 이름만
            say("failed: " + ", ".join(
                [_failure(f.source, f.subject, f.reason, f.error) for f in summary.failures]
                + [_failure("card", t.ticker, FailureReason.UNEXPECTED, t.error) for t in summary.ticker_errors]
            ))
    if summary.access_denied:
        say(f"ACCESS DENIED (not retried): {', '.join(summary.access_denied)}")
    if summary.rate_limited:
        say(f"RATE LIMITED (429, retried): {', '.join(summary.rate_limited)}")
    delayed = ", ".join(summary.change_delayed) or "-"
    resumed = ",".join(summary.resumed) or "-"  # 죽은 앞 실행이 저장해 이번에 건너뛴 카드
    say(f"{summary.trading_day} cards_saved={summary.cards_saved} resumed={resumed} change_delayed={delayed}")
    say(f"notices={summary.notices}")  # 아침 알림 문구 수만. 문구는 찍지 않는다
    skipped = ", ".join(f"{b.number}:{b.reason}" for b in summary.skipped_batches) or "-"
    tokens = summary.llm_tokens
    say(
        f"filings={summary.filings_collected} unclassified={summary.filings_unclassified}"
        f" batches={summary.classify_batches} skipped={skipped} llm_calls={summary.llm_calls}/{summary.llm_call_limit}"
        f" tokens=in:{tokens['input_tokens']},out:{tokens['output_tokens']},cache_read:{tokens['cache_read_tokens']}"
        f",cache_write:{tokens['cache_write_tokens']}"
    )
    say("lines: " + " ".join(
        f"{name}[{' '.join(f'{status}={n}' for status, n in counts.items() if n)}]" for name, counts in summary.line_counts.items()
    ))
    say("news: " + " ".join(f"{ticker}={n.status}" for ticker, n in summary.news.items()))
    if summary.funds:  # ETF 편입 종목: 상태 코드와 커버 범위에서 못 찾은 회사 수만(회사 이름은 찍지 않는다)
        say("holdings: " + " ".join(
            f"{ticker}={f.status}" + (f"(unmatched {f.unmatched})" if f.unmatched else "") for ticker, f in summary.funds.items()
        ))
    # 문장은 찍지 않는다(통과한 줄은 카드에, 걸린 줄은 보류함에 있다). 종목별 결과 코드만
    drafts = " ".join(f"{ticker}={d.problem or 'ok'}" for ticker, d in summary.drafts.items()) or "-"
    say(f"drafts: {drafts}")
    reviews = " ".join(
        f"{ticker}={'pass' if r.stage is None else f'hold:{r.stage}'}{'+retry' if r.retried else ''}"
        for ticker, r in summary.reviews.items()
    ) or "-"
    say(f"review: {reviews}")
    if (g := summary.glance) is None:  # 시장 한눈에(#11): 줄 상태와 검수 코드만. 문장·지표 이름·등락률은 찍지 않는다
        say("glance: resumed")
    else:
        say(f"glance: close={g.close_line.status} indicator={g.indicator_line.status}"
            f" market_news={g.market_news_line.status} review={summary.glance_review}")


def _failure(stage: str, subject: str | None, reason: str, error: str | None) -> str:
    """{stage}/{subject}={reason}, 예상 못 한 예외는 =unexpected:{예외 이름}. 대상이 없으면(지표) {stage}={reason}."""
    code = f"{reason}:{error}" if error else reason
    return f"{stage}/{subject}={code}" if subject else f"{stage}={code}"


QUALITY_LINES = (("news", "news_line"), ("event", "event_line"), ("price", "price_fact_line"))  # 품질 블록 줄 이름 → 카드 필드


def _quality_lines(summary: RunSummary, store: CardStore, prices: str) -> list[str]:
    """--quality 품질 블록(#14 D5). DB 연결이 열린 동안 부른다(카드·보류함·분류를 읽는다). 로컬 DB 전용이라 카드 문장·검수 전 초안을
    찍는 유일한 출력이다. 글자 필드는 json.dumps: 한 줄 유지, 제어 문자(터미널 이스케이프) 무력화. prices: "scenario" | "none"."""
    def text(value: str | None) -> str:
        return "-" if value is None else json.dumps(value, ensure_ascii=False)

    day = summary.trading_day
    out = [f"quality {day} classify={CLASSIFY_MODEL} newsline={NEWSLINE_MODEL} review={REVIEW_MODEL} prices={prices}"]
    cards = store.list_cards(day)
    for card in cards:
        out.append(f"card {card.ticker}")
        for name, attr in QUALITY_LINES:
            line = getattr(card, attr)
            out.append(f"  {name} " + ("- -" if line is None else f"{line.status} {text(line.text)}"))
        if draft := summary.drafts.get(card.ticker):
            out.append(f"  draft1 {draft.problem or 'ok'} {text(draft.sentence)}")
        if review := summary.reviews.get(card.ticker):
            if review.retried:
                out.append(f"  draft2 {text(review.draft_text)}")
            outcome = ("pass" if review.stage is None else f"hold:{review.stage}") + ("+retry" if review.retried else "")
            out.append(f"  review {outcome} {' | '.join(review.rules) or '-'}")
    for name, attr in QUALITY_LINES:
        counts = Counter(line.status for line in (getattr(c, attr) for c in cards) if line is not None)
        out.append(f"lines {name} " + " ".join(f"{status}={counts[status]}" for status in LineStatus))
    reviews = summary.reviews.values()
    out.append(f"review_counts pass_first={sum(r.stage is None and not r.retried for r in reviews)}"
               f" pass_retry={sum(r.stage is None and r.retried for r in reviews)}"
               f" replaced={sum(r.stage is not None for r in reviews)} retried={sum(r.retried for r in reviews)}")
    out += [f"hold {h.ticker} {h.stage} {h.state} {h.accession}" for h in store.list_hold_items(day)] or ["hold -"]
    rows = store.list_classifications(day)
    out += [
        f"classify {r.ticker} {r.accession} "
        + (f"unclassified={r.unclassified}" if r.unclassified else f"{r.kind}/{r.importance} opinion={str(r.is_opinion).lower()}")
        for r in rows
    ] or ["classify -"]
    kinds = Counter(r.kind for r in rows if r.kind)
    importance = Counter(r.importance for r in rows if r.kind)
    out.append("classify_counts kinds " + (" ".join(f"{k}={kinds[k]}" for k in NewsKind if kinds[k]) or "-")
               + " importance " + (" ".join(f"{i}={n}" for i, n in sorted(importance.items(), reverse=True)) or "-")
               + f" opinion={sum(bool(r.is_opinion) for r in rows)} unclassified={sum(r.unclassified is not None for r in rows)}")
    return out


class _Report:
    """운영 실행이 찍은 줄(stdout·stderr 순서대로). Discord 메시지는 이 줄 그대로다(#17 D3)."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.notify = True  # False: 휴장일 exit 0, ALREADY_DONE(매일 오는 예비 실행 소음)

    def __call__(self, line: str, file: TextIO | None = None) -> None:
        print(line, file=file)  # None = 부를 때의 sys.stdout(capsys 호환)
        self.lines.append(line)


BACKUP_RUN = "BACKUP RUN: no finished run when the GitHub schedule backup started (check pg_cron dispatch)"


def _production(requested: date | None, quality: bool = False) -> int:
    """실행 → (보낼 경우) Discord 실패 알림 → exit 코드. 품질 확인(로컬 전용)은 보내지 않는다."""
    now = datetime.now(ET)
    day = requested or now.date()
    report = _Report()
    code = _run_production(day, now, quality, report)
    if report.notify and not quality:
        _notify(day, code, report.lines)
    return code


def _notify(day: date, code: int, lines: Sequence[str]) -> None:
    """DISCORD_WEBHOOK_URL이 없으면 조용히. 형식이 틀렸거나 보내기에 실패하면 이유 코드 한 줄. exit 코드는 바꾸지 않는다."""
    try:
        settings = load_discord_settings()
    except ConfigError:
        print("discord: not sent (reason=bad_url)")
        return
    if settings is None:
        return
    reason = send_discord(settings, discord_content(day, code, lines))
    print("discord: sent" if reason is None else f"discord: not sent (reason={reason})")


def _run_production(day: date, now: datetime, quality: bool, say: _Report) -> int:
    """거래일·날짜 확인 → 설정 → DB 연결 → CIK 갱신·파이프라인(SEC·Anthropic·Tiingo) → 요약 → exit 코드. 외부 출처는 DB 연결 뒤에만 부른다.
    시세: TIINGO_API_KEY가 있으면 Tiingo, 없으면(유료 구독 전) 시세 없이(등락률·세 번째 줄 지연).
    quality(#14): 로컬 DB만, 시세는 항상 없이(무료 키 시간당 50회 보호. 품질 확인 대상은 첫 번째 줄), 끝에 품질 블록(say가 아니라 print:
    Discord 메시지에 넣지 않는다)."""
    if (code := _not_trading_day(day, say)) is not None:
        say.notify = code != 0
        return code
    if now < filing_window(day)[1]:  # 미래 날짜 오타·밤늦은 PT 실행이 원격에 카드를 만들지 않게
        say(f"{day} 공시 기간은 그날 04:00 ET에 닫힙니다. 그 뒤에 실행하거나 지난 거래일을 넣으세요", file=sys.stderr)
        return 2
    try:  # DB·외부 출처에 닿기 전에 모두 확인한다. 메시지에는 변수 이름만 있다
        settings, llm_settings, edgar_settings = load_settings(), load_llm_settings(), load_edgar_settings()
        tiingo_settings = load_tiingo_settings()
    except ConfigError as e:
        say(str(e), file=sys.stderr)
        return 2
    if quality and not is_local_db(settings.database_url):  # 카드 문장을 찍으므로 공개 로그(Actions = 원격 DB)에서 돌지 않게
        say("--quality는 로컬 DB에서만 씁니다", file=sys.stderr)
        return 2
    tiingo = tiingo_settings is not None and not quality
    error = None
    try:
        with connect(settings) as conn:
            store = CardStore(conn)
            # GitHub 예약 실행은 늦게 오는 예비(#43): 정시 dispatch가 그 거래일을 끝냈으면 카드·LLM 없이 끝낸다. 수동·dispatch는 다시 만든다
            if os.environ.get("RUN_TRIGGER") == "schedule":
                if store.has_finished_run(day):
                    say(f"ALREADY_DONE {day}")
                    say.notify = False
                    return 0
                say(BACKUP_RUN)  # 정시 dispatch가 오지 않았다는 신호(#17 D7). Discord에도 들어간다
            summary, refreshed = run_production(
                store,
                day,
                get=EdgarClient(edgar_settings).get,
                llm=AnthropicLLM(llm_settings),
                prices=TiingoPriceSource(tiingo_settings) if tiingo else NoPriceSource(),
            )
            lines = _quality_lines(summary, store, "none") if quality else []
    except RunLocked:  # 카드 0장과 같은 실패(exit 1). except Exception보다 먼저
        say(LOCKED.format(day), file=sys.stderr)
        return 1
    except (ConfigError, DBConnectError) as e:  # 우리가 쓴 문구(변수 이름·포트만): 6543 거부, 연결 실패
        say(str(e), file=sys.stderr)
        return 2 if isinstance(e, ConfigError) else 1
    except Exception as e:
        # 공개 로그: str(e)·traceback에는 서버 오류 DETAIL(행 내용 = 검수 전 문장)이나 라이브러리가 넣은 키가 섞일 수 있다
        error = error_name(e)
    if error is not None:
        say(f"RUN FAILED: {error}", file=sys.stderr)
        return 1
    _print_summary(summary, say)
    say("coverage: refreshed" if refreshed else "coverage: NOT REFRESHED (sec ticker list failed), stored rows used")
    say("prices=tiingo" if tiingo else "prices=none")  # none = TIINGO_API_KEY 없음(구독 전) 또는 --quality
    for line in lines:
        print(line)
    return 1 if run_failed(summary) else 0


if __name__ == "__main__":
    sys.exit(main())
