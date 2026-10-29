"""카드 저장소. 파이프라인은 DB를 이 모듈로만 만진다. 줄(CardLine) ↔ 컬럼 변환도 여기서만."""

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime

from decimal import Decimal

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from m30.adapters.filings import Filing
from m30.adapters.holdings import Holding, HoldingsReport
from m30.adapters.indicators import IndicatorRelease
from m30.config import DB_URL_VAR, ET, ConfigError, Settings, is_local_db
from m30.models import (
    AMENDED_RULE,
    CardLine,
    CardStatus,
    Classification,
    Coverage,
    HoldItem,
    HoldStage,
    HoldState,
    LineStatus,
    NewsKind,
    StockCard,
    UnclassifiedReason,
)

LINES = ("news_line", "event_line", "price_fact_line")
LINE_ATTRS = ("text", "status", "checked_at", "source_scope")
CARD_COLUMNS = (
    "ticker",
    "trading_day",
    "status",
    "change_pct",
    "change_status",
    *(f"{line}_{attr}" for line in LINES for attr in LINE_ATTRS),
    "leverage_tag",
    "news_line_accession",
    "previous_trading_day",  # publish_suspended는 넣지 않는다: 재실행이 사람이 켠 발행 중단을 덮지 않게
)
_UPSERT_CARD = (
    f"insert into public.stock_card ({', '.join(CARD_COLUMNS)}) values ({', '.join(['%s'] * len(CARD_COLUMNS))})"
    " on conflict (ticker, trading_day) do update set "
    + ", ".join(f"{c} = excluded.{c}" for c in CARD_COLUMNS[2:])
    + ", updated_at = now()"
)


LOCK_CLASS = 16  # advisory lock 첫 키 = 거래일 실행 잠금. 둘째 키 = YYYYMMDD (pg_locks의 classid·objid로 보인다)


class RunLocked(Exception):
    """같은 거래일 실행이 잠금을 쥐고 있다. 메시지에는 날짜만."""


class DBConnectError(psycopg.OperationalError):
    """connect()가 다시 던지는 연결 실패. 문구는 이 모듈이 쓴 것뿐(주소·비밀번호 없음)이라 공개 로그에 찍어도 된다."""


# 연결 실패 이유 코드(목록 순서로 처음 맞는 것). (E…) 형식은 최신 Supavisor 문구 추정(확인 못 함)
_CONNECT_REASONS = (
    ("auth_blocked", ("circuit breaker", "ecircuitbreaker")),  # Supavisor: 비밀번호를 여러 번 틀려 잠김
    ("auth_failed", ("password authentication failed",)),
    ("tenant_not_found", ("tenant or user not found", "tenant/user")),  # Supavisor: 사용자 이름의 프로젝트 ref·리전 호스트·일시정지
    ("host_not_found", ("failed to resolve host", "could not translate host name", "nodename nor servname",
                        "name or service not known")),
    ("network_unreachable", ("network is unreachable", "no route to host")),  # 예: IPv6 전용 Direct connection
    ("refused", ("connection refused",)),
    ("timeout", ("timeout expired",)),
)


def connect_failure_reason(message: str) -> str:
    """psycopg 연결 실패 메시지 → 고정 이유 코드. 메시지(호스트·사용자)는 공개 로그에 찍지 않고 코드만 찍는다."""
    message = message.lower()
    return next((code for code, marks in _CONNECT_REASONS if any(m in message for m in marks)), "other")


def _connect_error(reason: str) -> DBConnectError:
    return DBConnectError(
        f"{DB_URL_VAR}로 DB에 연결하지 못했습니다. 로컬이면 supabase start와 README의 export 줄을,"
        f" 운영이면 세션 풀러(포트 5432) 주소와 비밀번호를 확인하세요 (reason={reason})"
    )


def connect(settings: Settings) -> psycopg.Connection:
    """autocommit 연결 후 service_role로 권한을 낮춘다(서버 코드는 DDL을 못 한다).
    비로컬: 트랜잭션 풀러(6543)는 거부(문장마다 서버 연결이 바뀌어 set role이 유지되지 않는다), sslmode=require로 덮어쓴다.
    shortcut: require는 서버 인증서를 검증하지 않는다, 검증이 필요하면 Supabase CA 인증서 + verify-full."""
    local = is_local_db(settings.database_url)
    # URI에는 공백이 올 수 없다(secret 붙여넣기 앞뒤 공백·줄바꿈). 키=값 형식은 공백이 구분자라 제외
    if "://" in settings.database_url and any(c.isspace() for c in settings.database_url):
        raise _connect_error("bad_url")
    # 원래 예외를 끊고(from None, 지역 변수에서도 지움) 다시 던진다: psycopg 프레임 인자(conninfo)·주소 파싱 오류 메시지에 비밀번호가 있다
    try:
        ports = (conninfo_to_dict(settings.database_url).get("port") or "").split(",")  # 여러 호스트면 "5432,6543"
    except psycopg.Error:
        raise _connect_error("bad_url") from None  # 파싱 메시지는 비밀번호를 담을 수 있어 읽지 않고 실패 위치로 정한다
    if not local and any(p.strip().isdigit() and int(p) == 6543 for p in ports):
        raise ConfigError(
            f"{DB_URL_VAR}이 트랜잭션 풀러(포트 6543)입니다. 세션 풀러(포트 5432) 주소를 쓰세요: set role이 연결 내내 유지돼야 합니다"
        )
    try:
        conn = psycopg.connect(settings.database_url, autocommit=True, **({} if local else {"sslmode": "require"}))
    except psycopg.Error as e:
        reason = connect_failure_reason(str(e))
        del e
        raise _connect_error(reason) from None
    try:
        conn.execute("set role service_role")
    except BaseException:
        conn.close()
        raise
    return conn


def _line_values(line: CardLine | None) -> tuple:
    if line is None:
        return (None, None, None, None)
    return (line.text, line.status.value, line.checked_at, line.source_scope)


def _line(row: dict, line: str) -> CardLine | None:
    if row[f"{line}_status"] is None:
        return None
    return CardLine(
        text=row[f"{line}_text"],
        status=LineStatus(row[f"{line}_status"]),
        checked_at=row[f"{line}_checked_at"].astimezone(ET),
        source_scope=row[f"{line}_source_scope"],
    )


class CardStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    @contextmanager
    def run_lock(self, trading_day: date) -> Iterator[None]:
        """세션 advisory lock(LOCK_CLASS, YYYYMMDD). 못 잡으면 기다리지 않고 RunLocked. 나갈 때 푼다.
        프로세스가 죽으면 연결이 끊기며 DB가 푼다. 연결이 이미 끊겨 unlock이 실패해도 원래 예외를 가리지 않는다."""
        key = (LOCK_CLASS, int(trading_day.strftime("%Y%m%d")))
        if not self._conn.execute("select pg_try_advisory_lock(%s::int, %s::int)", key).fetchone()[0]:
            raise RunLocked(str(trading_day))
        try:
            yield
        finally:
            try:
                self._conn.execute("select pg_advisory_unlock(%s::int, %s::int)", key)
            except psycopg.Error:
                pass  # 연결이 끊겼으면 잠금도 이미 풀렸다

    def start_run(self, trading_day: date) -> tuple[int, datetime | None]:
        """run_lock 안에서. pipeline_run 행을 넣고 (id, resume_since).
        resume_since = 이 거래일의 마지막 완료 실행(없으면 -infinity)보다 뒤에 시작한 미완료 실행들의 가장 이른 started_at. 없으면 None."""
        [since] = self._conn.execute(
            "select min(started_at) from public.pipeline_run where trading_day = %(day)s and finished_at is null"
            " and started_at > coalesce((select max(started_at) from public.pipeline_run"
            "  where trading_day = %(day)s and finished_at is not null), '-infinity')",
            {"day": trading_day},
        ).fetchone()
        [run_id] = self._conn.execute(
            "insert into public.pipeline_run (trading_day) values (%s) returning id", (trading_day,)
        ).fetchone()
        return run_id, since and since.astimezone(ET)

    def finish_run(self, run_id: int) -> None:
        self._conn.execute("update public.pipeline_run set finished_at = now() where id = %s", (run_id,))

    def has_finished_run(self, trading_day: date) -> bool:
        """이 거래일에 끝까지 간 실행(finished_at 있음)이 있는지. 진행 중·죽은 실행은 세지 않는다."""
        return self._conn.execute(
            "select exists (select from public.pipeline_run where trading_day = %s and finished_at is not null)", (trading_day,)
        ).fetchone()[0]

    def save_card(self, card: StockCard, holds: Sequence[HoldItem] | None) -> None:
        """한 트랜잭션: upsert_card(card) 다음, holds가 None이 아니면 replace_hold_items(card.ticker, card.trading_day, holds).
        None = 이번에 첫 번째 줄을 만들지 않았다(재발행 유지, CIK 실패 시 이전 값 유지) → 그 카드의 보류함 행을 건드리지 않는다."""
        with self._conn.transaction():
            self.upsert_card(card)
            if holds is not None:
                self.replace_hold_items(card.ticker, card.trading_day, holds)

    def upsert_coverage(self, rows: Iterable[Coverage]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "insert into public.coverage (ticker, name, leverage, cik, holdings_ticker) values (%s, %s, %s, %s, %s)"
                " on conflict (ticker) do update set name = excluded.name, leverage = excluded.leverage, cik = excluded.cik,"
                " holdings_ticker = excluded.holdings_ticker",
                [(r.ticker, r.name, r.leverage, r.cik, r.holdings_ticker) for r in rows],
            )

    def upsert_card(self, card: StockCard) -> None:
        """(종목, 거래일) 카드를 통째로 덮어쓴다. 한 문장 upsert라 동시 실행에도 카드는 하나다. card.updated_at은 무시."""
        values = (
            card.ticker,
            card.trading_day,
            card.status.value,
            card.change_pct,
            card.change_status.value,
            *_line_values(card.news_line),
            *_line_values(card.event_line),
            *_line_values(card.price_fact_line),
            card.leverage_tag,
            card.news_line_accession,
            card.previous_trading_day,
        )
        self._conn.execute(_UPSERT_CARD, values)

    def list_coverage(self) -> list[Coverage]:
        rows = self._conn.execute("select ticker, name, leverage, cik, holdings_ticker from public.coverage order by ticker")
        return [Coverage(*row) for row in rows]

    def add_default_tickers(self, day: date, tickers: Iterable[str]) -> None:
        """day가 속한 분기(첫날)의 기본 종목에 tickers를 더한다. 이미 있으면 그대로, 지우지 않는다. 커버 범위에 없는 티커는 넣지 않는다."""
        self._conn.execute(
            "insert into public.default_ticker (quarter, ticker)"
            " select date_trunc('quarter', %s::timestamp)::date, ticker from public.coverage where ticker = any(%s)"
            " on conflict do nothing",
            (day, list(tickers)),
        )

    def list_generation_targets(self, trading_day: date) -> list[Coverage]:
        """생성 대상 = 활성 종목(잠기지 않은 내 종목 행이 있는 티커) ∪ trading_day가 속한 분기의 기본 종목. list_coverage와 같은 모양·순서."""
        rows = self._conn.execute(
            "select c.ticker, c.name, c.leverage, c.cik, c.holdings_ticker from public.coverage c"
            " where exists (select from public.my_stock s where s.ticker = c.ticker and not s.locked)"
            " or exists (select from public.default_ticker d"
            "  where d.ticker = c.ticker and d.quarter = date_trunc('quarter', %s::timestamp)::date)"
            " order by c.ticker",
            (trading_day,),
        )
        return [Coverage(*row) for row in rows]

    def save_filings(self, trading_day: date, filings: Iterable[Filing]) -> frozenset[str]:
        """공시 원본 저장. 이미 있는 접수번호는 건드리지 않는다(처음 받은 원본·거래일 유지).
        돌려주는 값: 넘긴 접수번호 중 처음 받은 거래일이 trading_day인 것 = 이번 카드의 새 소식."""
        rows = [
            (f.accession, f.cik, f.form.value, f.accepted_at, list(f.items), trading_day, f.raw, f.report_date) for f in filings
        ]
        if not rows:
            return frozenset()
        with self._conn.cursor() as cur:
            cur.executemany(
                "insert into public.sec_filing (accession, cik, form, accepted_at, items, trading_day, payload, report_date)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (accession) do nothing",
                rows,
            )
            found = cur.execute(
                "select accession from public.sec_filing where accession = any(%s) and trading_day = %s",
                ([r[0] for r in rows], trading_day),
            ).fetchall()
        return frozenset(r[0] for r in found)

    def save_indicator_releases(self, trading_day: date, releases: Iterable[IndicatorRelease]) -> None:
        """(이름, 발표 시각)으로 중복 제거. 이미 있는 원본은 건드리지 않는다."""
        with self._conn.cursor() as cur:
            cur.executemany(
                "insert into public.indicator_release (name, released_at, trading_day, payload)"
                " values (%s, %s, %s, %s) on conflict (name, released_at) do nothing",
                [(r.name, r.released_at, trading_day, r.raw) for r in releases],
            )

    def save_holdings(self, report: HoldingsReport) -> None:
        """편입 종목 보고 저장. 이미 있는 접수번호는 건드리지 않는다(처음 받은 원본 유지). pct는 Decimal 그대로 문자열로."""
        rows = [{"name": h.name, "cik": h.cik, "pct": str(h.pct), "asset_category": h.asset_category} for h in report.holdings]
        self._conn.execute(
            "insert into public.fund_holdings (accession, fund, period_end, holdings, payload) values (%s, %s, %s, %s, %s)"
            " on conflict (accession) do nothing",
            (report.accession, report.fund, report.period_end, Jsonb(rows), report.raw),
        )

    def latest_holdings(self, fund: str) -> HoldingsReport | None:
        """fund의 저장된 보고 중 기준일이 가장 늦은 것(같으면 늦게 받은 것). 없으면 None."""
        row = self._conn.execute(
            "select accession, period_end, holdings, payload from public.fund_holdings where fund = %s"
            " order by period_end desc, received_at desc limit 1",
            (fund,),
        ).fetchone()
        if row is None:
            return None
        accession, period_end, holdings, payload = row
        return HoldingsReport(
            fund, accession, period_end,
            tuple(Holding(h["name"], h["cik"], Decimal(h["pct"]), h["asset_category"]) for h in holdings), payload,
        )

    def replace_classifications(self, trading_day: date, tickers: Iterable[str], rows: Iterable[Classification]) -> None:
        """한 트랜잭션: trading_day 공시(처음 받은 거래일 기준)의 분류 행 중 ticker ∈ tickers인 것만 지우고 rows를 넣는다."""
        values = [
            (r.accession, r.ticker, r.kind and r.kind.value, r.importance, r.is_opinion, r.unclassified and r.unclassified.value)
            for r in rows
        ]
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "delete from public.filing_classification c using public.sec_filing f"
                " where f.accession = c.accession and f.trading_day = %s and c.ticker = any(%s)",
                (trading_day, list(tickers)),
            )
            cur.executemany(
                "insert into public.filing_classification (accession, ticker, kind, importance, is_opinion, unclassified)"
                " values (%s, %s, %s, %s, %s, %s)",
                values,
            )

    def list_classifications(self, trading_day: date) -> list[Classification]:
        """trading_day 공시의 분류 행, (접수번호, 티커) 순."""
        rows = self._conn.execute(
            "select c.accession, c.ticker, c.kind, c.importance, c.is_opinion, c.unclassified::text"
            " from public.filing_classification c join public.sec_filing f on f.accession = c.accession"
            " where f.trading_day = %s order by c.accession, c.ticker",
            (trading_day,),
        )
        return [
            Classification(acc, ticker, kind and NewsKind(kind), importance, is_opinion, reason and UnclassifiedReason(reason))
            for acc, ticker, kind, importance, is_opinion, reason in rows
        ]

    def list_raw_filings(self, trading_day: date) -> dict[str, str]:
        """접수번호 → payload (처음 받은 거래일이 trading_day인 공시)."""
        rows = self._conn.execute(
            "select accession, payload from public.sec_filing where trading_day = %s order by accession", (trading_day,)
        )
        return dict(rows.fetchall())

    def list_raw_indicators(self, trading_day: date) -> list[str]:
        """payload 목록, (발표 시각, 이름) 순."""
        rows = self._conn.execute(
            "select payload from public.indicator_release where trading_day = %s order by released_at, name",
            (trading_day,),
        )
        return [r[0] for r in rows]

    def list_cards(self, trading_day: date) -> list[StockCard]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                f"select {', '.join(CARD_COLUMNS)}, updated_at from public.stock_card"
                " where trading_day = %s order by ticker",
                (trading_day,),
            ).fetchall()
        return [
            StockCard(
                ticker=r["ticker"],
                trading_day=r["trading_day"],
                status=CardStatus(r["status"]),
                change_pct=r["change_pct"],
                change_status=LineStatus(r["change_status"]),
                news_line=_line(r, "news_line"),
                event_line=_line(r, "event_line"),
                price_fact_line=_line(r, "price_fact_line"),
                leverage_tag=r["leverage_tag"],
                updated_at=r["updated_at"].astimezone(ET),
                news_line_accession=r["news_line_accession"],
                previous_trading_day=r["previous_trading_day"],
            )
            for r in rows
        ]

    def republished_news(self, trading_day: date) -> dict[str, tuple[str, str | None]]:
        """티커 → (카드 첫 번째 줄 문구, news_line_accession): trading_day 카드 중 republished 보류함 행이 있는 카드의 현재 값.
        카드 루프 전에 읽는다(재실행이 사람이 재발행한 줄을 덮지 않게)."""
        rows = self._conn.execute(
            "select c.ticker, c.news_line_text, c.news_line_accession from public.stock_card c"
            " where c.trading_day = %s and exists (select from public.hold_queue h where h.ticker = c.ticker"
            " and h.trading_day = c.trading_day and h.state = 'republished')",
            (trading_day,),
        )
        return {ticker: (text, accession) for ticker, text, accession in rows}

    def replace_hold_items(self, ticker: str, trading_day: date, rows: Iterable[HoldItem]) -> None:
        """한 트랜잭션: (ticker, trading_day)의 pending이면서 amended_filing이 아닌 행을 지우고 rows를 넣는다.
        on conflict do nothing: 사람이 손댄 행·정정 행과 키가 겹치면 그 행을 그대로 둔다. 같은 입력이면 같은 행."""
        values = [
            (r.ticker, r.trading_day, r.accession, r.stage.value, r.draft_text, list(r.rules), r.replacement_text,
             r.state.value, r.edited_text)
            for r in rows
        ]
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "delete from public.hold_queue"
                " where ticker = %s and trading_day = %s and state = 'pending' and stage <> 'amended_filing'",
                (ticker, trading_day),
            )
            cur.executemany(
                "insert into public.hold_queue"
                " (ticker, trading_day, accession, stage, draft_text, rules, replacement_text, state, edited_text)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s) on conflict do nothing",
                values,
            )

    def flag_amended_cards(self, trading_day: date, amendments: Iterable[Filing]) -> None:
        """8-K/A마다(report_date 없으면 건너뜀) 같은 CIK·같은 report_date의 다른 공시를 첫 번째 줄로 쓴 trading_day 이전 카드에
        (그 카드의 종목·거래일, 8-K/A 접수번호, amended_filing, [AMENDED_RULE]) 행을 넣는다(있으면 그대로). 카드는 건드리지 않는다.
        shortcut: 보고 기준일을 주지 않는 출처면 원래 공시를 못 찾는다, #19가 EDGAR reportDate를 채우면 해소."""
        values = [
            (a.accession, [AMENDED_RULE], a.cik, a.report_date, a.accession, trading_day)
            for a in amendments
            if a.report_date is not None
        ]
        with self._conn.cursor() as cur:
            cur.executemany(
                "insert into public.hold_queue (ticker, trading_day, accession, stage, rules)"
                " select c.ticker, c.trading_day, %s, 'amended_filing', %s"
                " from public.stock_card c join public.sec_filing f on f.accession = c.news_line_accession"
                " where f.cik = %s and f.report_date = %s and f.accession <> %s and c.trading_day < %s"
                " on conflict do nothing",
                values,
            )

    def list_hold_items(self, trading_day: date) -> list[HoldItem]:
        """trading_day 행, (종목, 접수번호) 순."""
        rows = self._conn.execute(
            "select ticker, trading_day, accession, stage::text, draft_text, rules, replacement_text, state::text, edited_text"
            " from public.hold_queue where trading_day = %s order by ticker, accession",
            (trading_day,),
        )
        return [
            HoldItem(ticker, day, accession, HoldStage(stage), draft, tuple(rules), replacement, HoldState(state), edited)
            for ticker, day, accession, stage, draft, rules, replacement, state, edited in rows
        ]
