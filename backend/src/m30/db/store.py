"""카드 저장소. 파이프라인은 DB를 이 모듈로만 만진다. 줄(CardLine) ↔ 컬럼 변환도 여기서만."""

from collections.abc import Iterable
from datetime import date

import psycopg
from psycopg.rows import dict_row

from m30.adapters.filings import Filing
from m30.adapters.indicators import IndicatorRelease
from m30.config import DB_URL_VAR, ET, Settings
from m30.models import CardLine, CardStatus, Classification, Coverage, LineStatus, NewsKind, StockCard, UnclassifiedReason

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
)
_UPSERT_CARD = (
    f"insert into public.stock_card ({', '.join(CARD_COLUMNS)}) values ({', '.join(['%s'] * len(CARD_COLUMNS))})"
    " on conflict (ticker, trading_day) do update set "
    + ", ".join(f"{c} = excluded.{c}" for c in CARD_COLUMNS[2:])
    + ", updated_at = now()"
)


def connect(settings: Settings) -> psycopg.Connection:
    """autocommit 연결 후 service_role로 권한을 낮춘다(서버 코드는 DDL을 못 한다)."""
    try:
        conn = psycopg.connect(settings.database_url, autocommit=True)
    except psycopg.Error:
        # psycopg 프레임 인자(conninfo)·주소 파싱 오류 메시지에 비밀번호가 있어 원래 예외를 끊고 다시 던진다
        raise psycopg.OperationalError(
            f"{DB_URL_VAR}로 DB에 연결하지 못했습니다. 로컬이면 supabase start와 README의 export 줄을 확인하세요"
        ) from None
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

    def upsert_coverage(self, rows: Iterable[Coverage]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "insert into public.coverage (ticker, name, leverage, cik) values (%s, %s, %s, %s)"
                " on conflict (ticker) do update set name = excluded.name, leverage = excluded.leverage, cik = excluded.cik",
                [(r.ticker, r.name, r.leverage, r.cik) for r in rows],
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
        )
        self._conn.execute(_UPSERT_CARD, values)

    def list_coverage(self) -> list[Coverage]:
        rows = self._conn.execute("select ticker, name, leverage, cik from public.coverage order by ticker")
        return [Coverage(ticker=t, name=n, leverage=lev, cik=cik) for t, n, lev, cik in rows]

    def save_filings(self, trading_day: date, filings: Iterable[Filing]) -> frozenset[str]:
        """공시 원본 저장. 이미 있는 접수번호는 건드리지 않는다(처음 받은 원본·거래일 유지).
        돌려주는 값: 넘긴 접수번호 중 처음 받은 거래일이 trading_day인 것 = 이번 카드의 새 소식."""
        rows = [(f.accession, f.cik, f.form.value, f.accepted_at, list(f.items), trading_day, f.raw) for f in filings]
        if not rows:
            return frozenset()
        with self._conn.cursor() as cur:
            cur.executemany(
                "insert into public.sec_filing (accession, cik, form, accepted_at, items, trading_day, payload)"
                " values (%s, %s, %s, %s, %s, %s, %s) on conflict (accession) do nothing",
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

    def replace_classifications(self, trading_day: date, rows: Iterable[Classification]) -> None:
        """한 트랜잭션: trading_day 공시(처음 받은 거래일 기준)의 분류 행을 지우고 rows를 넣는다."""
        values = [
            (r.accession, r.ticker, r.kind and r.kind.value, r.importance, r.is_opinion, r.unclassified and r.unclassified.value)
            for r in rows
        ]
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "delete from public.filing_classification c using public.sec_filing f"
                " where f.accession = c.accession and f.trading_day = %s",
                (trading_day,),
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
            )
            for r in rows
        ]
