"""python -m m30.pipeline 2026-10-16 --scenario scenarios/first_card.json   로컬 개발: 가짜 출처, 로컬 DB만
python -m m30.pipeline --production [YYYY-MM-DD]                          운영: 실제·미연결 출처, 원격 DB 허용, 비우면 오늘(ET)
python -m m30.pipeline --quarterly                                        분기 작업(#60·#64·#66): 새 10-K 원문·업종 코드·연관 종목·알아두기. 실제 SEC·Sonnet, 원격 DB 허용
둘 다 --quality: 실제 Haiku로 돌리고 카드 문장·초안·보류함·분류를 찍는다. 로컬 DB만(#14)"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

from m30.adapters.edgar import (
    ANNUAL_REPORT_FILE_MAX,
    QUARTERLY_INTERVAL,
    CountedGet,
    EdgarAnnualReportSource,
    EdgarClient,
    Throttle,
)
from m30.adapters.gov import GovClient
from m30.adapters.tiingo import TiingoPriceSource
from m30.adapters.unavailable import NoPriceSource
from m30.config import (
    CLASSIFY_MODEL,
    DB_URL_VAR,
    ET,
    GLANCE_MODEL,
    NEWSLINE_MODEL,
    REVIEW_MODEL,
    ConfigError,
    is_local_db,
    load_discord_settings,
    load_edgar_settings,
    load_llm_settings,
    load_settings,
    load_tiingo_settings,
    price_display_on,
)
from m30.db.store import CardStore, DBConnectError, RunLocked, connect
from m30.llm.anthropic import AnthropicLLM
from m30.models import LineStatus, NewsKind
from m30.notify import discord_content, send_discord
from m30.pipeline.collect import FailureReason, error_name, filing_window
from m30.pipeline.morning import MorningPipeline, RunSummary
from m30.pipeline.production import CoverageRefresh, run_failed, run_production
from m30.pipeline.quarterly import QuarterlySummary, quarterly_failed, run_quarterly
from m30.trading_day import CalendarError, is_trading_day


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m m30.pipeline", description="아침 파이프라인 실행")
    parser.add_argument("trading_day", nargs="?", type=date.fromisoformat, help="거래일 YYYY-MM-DD (동부 기준)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", type=Path, help="가짜 시나리오 JSON 경로 (로컬 DB만)")
    mode.add_argument("--production", action="store_true", help="실제 출처로 실행. 원격 DB를 쓸 수 있는 모드(분기 작업과 함께)")
    mode.add_argument("--quarterly", action="store_true",
                      help="분기 작업: 커버 범위 회사의 새 10-K 원문·업종 코드. 실제 SEC, 원격 DB 허용")
    parser.add_argument("--quality", action="store_true",
                        help="실제 Haiku로 돌리고 카드 문장·초안·보류함·분류를 찍는다. 로컬 DB만")
    args = parser.parse_args(argv)
    if args.quarterly:
        if args.trading_day is not None or args.quality:
            parser.error("--quarterly takes no trading_day or --quality")
        return _quarterly()
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
        FakeEarningsFilingSource,
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
    prices_on = price_display_on()  # off(#56): 가짜 시세도 만들지 않는다
    try:
        with connect(settings) as conn:
            store = CardStore(conn)
            store.upsert_coverage(scenario.coverage)
            store.add_default_tickers(args.trading_day, [c.ticker for c in scenario.coverage])  # 유저 없음 → 시나리오 커버 범위 전체가 대상
            summary = MorningPipeline(
                prices=FakePriceSource(scenario) if prices_on else None,
                events=FakeEventSource(scenario),
                earnings=FakeEarningsFilingSource(scenario),
                filings=FakeFilingSource(scenario),
                indicators=FakeIndicatorSource(scenario),
                holdings=FakeHoldingsSource(scenario),
                market_news=FakeMarketNewsSource(scenario),
                llm=AnthropicLLM(llm_settings) if args.quality else FakeLLM(scenario),  # 품질 확인은 llm_replies를 쓰지 않는다
                store=store,
            ).run(args.trading_day)
            quality = _quality_lines(summary, store, "scenario" if prices_on else "off") if args.quality else []
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
    # 문장은 찍지 않는다(통과한 줄은 카드에, 걸린 줄은 보류함에 있다). 종목별 결과 코드만. 세 번째 줄(#67)도 같은 모양
    def drafts(found: dict) -> str:
        return " ".join(f"{ticker}={d.problem or 'ok'}" for ticker, d in found.items()) or "-"

    def reviews(found: dict) -> str:
        return " ".join(
            f"{ticker}={'pass' if r.stage is None else f'hold:{r.stage}'}{'+retry' if r.retried else ''}"
            for ticker, r in found.items()
        ) or "-"

    say(f"drafts: {drafts(summary.drafts)}")
    say(f"review: {reviews(summary.reviews)}")
    say(f"related_drafts: {drafts(summary.related_drafts)}")
    say(f"related_review: {reviews(summary.related_reviews)}")
    if (g := summary.glance) is None:  # 시장 한눈에(#11): 줄 상태와 검수 코드만. 문장·지표 이름·등락률은 찍지 않는다
        say("glance: resumed")
    else:
        say(f"glance: close={g.close_line.status} indicator={g.indicator_line.status}"
            f" market_news={g.market_news_line.status} review={summary.glance_review}")


def _coverage_line(refresh: CoverageRefresh) -> str:
    """커버 범위 갱신(#58 D8). 이유 코드·건수·기준일만(공개 로그: 회사 이름·문장 없음)."""
    if refresh.reason is not None:
        return f"coverage: NOT REFRESHED reason={refresh.reason}, stored rows used"
    return (f"coverage: refreshed etfs={refresh.etfs} stocks={refresh.stocks} added={refresh.added} unmatched={refresh.unmatched}"
            f" sp500={refresh.sp500_period_end or 'none'}")


def _failure(stage: str, subject: str | None, reason: str, error: str | None) -> str:
    """{stage}/{subject}={reason}, 예상 못 한 예외는 =unexpected:{예외 이름}. 대상이 없으면(지표) {stage}={reason}."""
    code = f"{reason}:{error}" if error else reason
    return f"{stage}/{subject}={code}" if subject else f"{stage}={code}"


QUALITY_LINES = (("news", "news_line"), ("event", "event_line"), ("price", "price_fact_line"),
                 ("related", "related_line"))  # 품질 블록 줄 이름 → 카드 필드


def _quality_lines(summary: RunSummary, store: CardStore, prices: str) -> list[str]:
    """--quality 품질 블록(#14 D5). DB 연결이 열린 동안 부른다(카드·보류함·분류를 읽는다). 로컬 DB 전용이라 카드 문장·검수 전 초안을
    찍는 유일한 출력이다. 글자 필드는 json.dumps: 한 줄 유지, 제어 문자(터미널 이스케이프) 무력화. prices: "scenario" | "none" | "off"(#56)."""
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


def _glance_quality_lines(summary: RunSummary, store: CardStore) -> list[str]:
    """운영 --quality의 시장 한눈에 블록(#50: 실제 기관 출처 live 확인용). 시나리오 품질 블록(test_newsline이 고정)에는 넣지 않는다.
    글자 필드는 _quality_lines와 같이 json.dumps. 저장된 행을 읽는다(이어 하기로 건너뛴 실행도 그날 행)."""
    def text(value: str | None) -> str:
        return "-" if value is None else json.dumps(value, ensure_ascii=False)

    out = [f"glance model={GLANCE_MODEL}"]
    if (glance := store.get_market_glance(summary.trading_day)) is None:
        return out + ["glance -"]
    for name, line in (("close", glance.close_line), ("indicator", glance.indicator_line), ("market_news", glance.market_news_line)):
        out.append(f"glance {name} {line.status} {text(line.text)}")
    out.append(f"glance review {summary.glance_review}")
    out.append(f"glance hold {text(glance.market_news_hold_draft)} {' | '.join(glance.market_news_hold_rules) or '-'}")
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
    """거래일·날짜 확인 → 설정 → DB 연결 → 커버 범위 갱신·파이프라인(SEC·정부 기관·Anthropic·Tiingo) → 요약 → exit 코드. 외부 출처는 DB 연결 뒤에만 부른다.
    시세: 가격 표시 플래그(PRICE_DISPLAY, #56)가 꺼져 있으면 시세 어댑터를 만들지 않고 TIINGO_API_KEY도 읽지 않는다(등락률·어제 마감 미지원).
    켜져 있으면 TIINGO_API_KEY가 있으면 Tiingo, 없으면(유료 구독 전) 시세 없이(등락률·세 번째 줄 지연).
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
        prices_on = price_display_on()
        tiingo_settings = load_tiingo_settings() if prices_on else None  # off: 키를 읽지 않는다(형식이 틀려도 막지 않음)
    except ConfigError as e:
        say(str(e), file=sys.stderr)
        return 2
    if quality and not is_local_db(settings.database_url):  # 카드 문장을 찍으므로 공개 로그(Actions = 원격 DB)에서 돌지 않게
        say("--quality는 로컬 DB에서만 씁니다", file=sys.stderr)
        return 2
    tiingo = tiingo_settings is not None and not quality
    price_code = "off" if not prices_on else "tiingo" if tiingo else "none"  # 출력 코드. --quality면 off|none
    error = None
    try:
        with connect(settings) as conn:
            store = CardStore(conn)
            # GitHub 예약 실행은 늦게 오는 예비(#43): 그 거래일을 실패 없이 끝낸 실행이 있으면 카드·LLM 없이 끝낸다. 수동·dispatch는 다시 만든다
            if os.environ.get("RUN_TRIGGER") == "schedule":
                if store.has_finished_run(day):
                    say(f"ALREADY_DONE {day}")
                    say.notify = False
                    return 0
                say(BACKUP_RUN)  # 정시 dispatch가 오지 않았다는 신호(#17 D7). Discord에도 들어간다
            sec = CountedGet(EdgarClient(edgar_settings).get)  # 실행 요약 edgar 줄(#67 D9): SEC 요청 수·쓴 시간
            started = time.monotonic()
            summary, refresh = run_production(
                store,
                day,
                get=sec,
                gov_get=GovClient(edgar_settings).get,  # 연락처는 BLS 요청에만(#50 U1)
                llm=AnthropicLLM(llm_settings),
                prices=None if not prices_on else TiingoPriceSource(tiingo_settings) if tiingo else NoPriceSource(),
            )
            run_seconds = time.monotonic() - started  # 커버 범위 갱신 + 파이프라인
            lines = _quality_lines(summary, store, price_code) + _glance_quality_lines(summary, store) if quality else []
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
    say(_coverage_line(refresh))
    say(f"prices={price_code}")  # off = 가격 표시 꺼짐(#56), none = TIINGO_API_KEY 없음(구독 전) 또는 --quality
    # 07:45 마감 판단용(#67 U4): 8-K 단계 CIK 수·그중 연관 종목 몫, SEC 요청 수·초, 실행 초. 주소·회사 이름 없음
    say(f"edgar: ciks={summary.filing_ciks} related_ciks={summary.related_ciks} requests={sec.requests}"
        f" seconds={round(sec.seconds)} run_seconds={round(run_seconds)}")
    for line in lines:
        print(line)
    return 1 if run_failed(summary) else 0


def _quarterly() -> int:
    """분기 작업(#60·#64·#66): 설정 → DB 연결 → run_quarterly(실제 SEC 초당 1회, 연관 종목·알아두기는 실제 Anthropic) → 요약 → exit 코드.
    아침 실행 잠금·실행 기록·Discord 없음. 운영 가드는 _run_production과 같다: 설정 누락 2(ANTHROPIC_API_KEY 포함: 키 없이 돌면
    연관 종목이 조용히 멈추므로 시작하지 않는다), 6543 2, 연결 실패 1(이유 코드), 그 밖 예외 RUN FAILED 1."""
    try:  # DB·SEC·LLM에 닿기 전에. 메시지에는 변수 이름만 있다
        settings, edgar_settings, llm_settings = load_settings(), load_edgar_settings(), load_llm_settings()
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    error = None
    try:
        with connect(settings) as conn:
            get = EdgarClient(edgar_settings, throttle=Throttle(QUARTERLY_INTERVAL), max_bytes=ANNUAL_REPORT_FILE_MAX).get
            summary = run_quarterly(CardStore(conn), reports=EdgarAnnualReportSource(get), llm=AnthropicLLM(llm_settings))
    except (ConfigError, DBConnectError) as e:  # 우리가 쓴 문구(변수 이름·포트만): 6543 거부, 연결 실패
        print(e, file=sys.stderr)
        return 2 if isinstance(e, ConfigError) else 1
    except Exception as e:
        error = error_name(e)  # 공개 로그: str(e)·traceback에는 행 내용·라이브러리가 넣은 값이 섞일 수 있다
    if error is not None:
        print(f"RUN FAILED: {error}", file=sys.stderr)
        return 1
    _print_quarterly(summary)
    return 1 if quarterly_failed(summary) else 0


def _print_quarterly(summary: QuarterlySummary) -> None:
    """결과 코드·건수·CIK만(공개 로그): 10-K 글자·회사 이름·근거 문장·알아두기 문장·LLM 응답·URL·연락처·예외 메시지를 찍지 않는다.
    형식은 _print_summary와 같다. 실패·차단 줄은 10-K 수집·연관 종목·알아두기(둘 다 LLM)를 합친다(단계마다 따로 남긴다)."""
    relations, quiet = summary.relations, summary.quiet_facts
    failures = summary.failures + relations.failures + quiet.failures
    if quarterly_failed(summary):
        print(f"!!! FAILED: failures={len(failures)} companies={summary.companies} !!!")
        if failures:
            print("failed: " + ", ".join(_failure(f.source, f.subject, f.reason, f.error) for f in failures))
    if denied := sorted(set(summary.access_denied) | set(relations.access_denied) | set(quiet.access_denied)):
        print(f"ACCESS DENIED (not retried): {', '.join(denied)}")
    if limited := sorted(set(summary.rate_limited) | set(relations.rate_limited) | set(quiet.rate_limited)):
        print(f"RATE LIMITED (429, retried): {', '.join(limited)}")
    print(f"quarterly companies={summary.companies} new={summary.new} unchanged={summary.unchanged}"
          f" no_annual_report={summary.no_annual_report} sic={summary.sic} sic_missing={summary.sic_missing}")
    tokens = relations.llm_tokens
    print(f"relations: extracted={relations.extracted} deferred={relations.deferred}"
          f" json_invalid={','.join(relations.json_invalid) or '-'} no_item1={relations.no_item1} no_section={relations.no_section}"
          f" truncated={relations.truncated} invalid_mentions={relations.invalid_mentions}"
          f" llm_calls={relations.llm_calls}/{relations.llm_call_limit} tokens=in:{tokens['input_tokens']},out:{tokens['output_tokens']}"
          f",cache_read:{tokens['cache_read_tokens']},cache_write:{tokens['cache_write_tokens']}")
    rows = sum(relations.basis.values())
    share = " ".join(f"{b}={n}({round(100 * n / rows)}%)" if rows else f"{b}={n}(-)" for b, n in relations.basis.items())
    m = relations.matches
    print(f"relations: tickers={relations.tickers} changed={relations.changed} rows={rows} {share} under3={relations.under3}"
          f" mentions={m.mentions} matched={m.matched} unmatched={m.unmatched} ambiguous={m.ambiguous} self={m.self_named}")
    tokens = quiet.llm_tokens
    print(f"quiet_facts: made={quiet.made} facts={quiet.facts} deferred={quiet.deferred} json_invalid={','.join(quiet.json_invalid) or '-'}"
          f" no_item1={quiet.no_item1} empty={quiet.empty}"
          f" dropped=format:{quiet.dropped_format},rules:{quiet.dropped_rules},check:{quiet.dropped_check}"
          f" llm_calls={quiet.llm_calls}/{quiet.llm_call_limit} tokens=in:{tokens['input_tokens']},out:{tokens['output_tokens']}"
          f",cache_read:{tokens['cache_read_tokens']},cache_write:{tokens['cache_write_tokens']} pools={quiet.pools}/{quiet.tickers}")


if __name__ == "__main__":
    sys.exit(main())
