"""카드 저장소. 파이프라인은 DB를 이 모듈로만 만진다. 줄(CardLine) ↔ 컬럼 변환도 여기서만."""

from collections.abc import Iterable
from datetime import date

import psycopg
from psycopg.rows import dict_row

from m30.config import DB_URL_VAR, ET, Settings
from m30.models import CardLine, CardStatus, Coverage, LineStatus, StockCard

LINES = ("news_line", "event_line", "price_fact_line")
LINE_ATTRS = ("text", "status", "checked_at", "source_scope")
CARD_COLUMNS = (
    "ticker",
    "trading_day",
    "status",
    "change_pct",
    "change_status",
    *(f"{line}_{attr}" for line in LINES for attr in LINE_ATTRS),
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
                "insert into public.coverage (ticker, name) values (%s, %s)"
                " on conflict (ticker) do update set name = excluded.name",
                [(r.ticker, r.name) for r in rows],
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
        )
        self._conn.execute(_UPSERT_CARD, values)

    def list_coverage(self) -> list[Coverage]:
        rows = self._conn.execute("select ticker, name from public.coverage order by ticker")
        return [Coverage(ticker=t, name=n) for t, n in rows]

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
                updated_at=r["updated_at"].astimezone(ET),
            )
            for r in rows
        ]
