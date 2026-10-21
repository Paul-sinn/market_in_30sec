"""DB 픽스처. 로컬 Supabase만 쓴다. 테스트마다 public 테이블을 비운다."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from m30.config import ET, ConfigError, is_local_db, load_settings
from m30.db.store import CardStore, connect
from m30.models import CardLine, CardStatus, LineStatus, StockCard

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"


@pytest.fixture(scope="session")
def settings():
    try:
        s = load_settings()
    except ConfigError as e:
        pytest.fail(f"{e}. 레포 루트에서 supabase start 후 README의 export 줄을 실행하세요", pytrace=False)
    if not is_local_db(s.database_url):
        pytest.fail("SUPABASE_DB_URL이 로컬 DB가 아닙니다. 테스트는 데이터를 지우므로 로컬에서만 돈다", pytrace=False)
    return s


@pytest.fixture
def admin(settings):
    """마이그레이션 소유자(postgres) 연결. 스키마 검사·역할 전환용. 시작 전에 public 테이블을 비운다."""
    with connect(settings) as conn:
        conn.execute("reset role")  # 비밀번호 숨김은 connect가 맡는다. 관리자 연결이라 service_role만 되돌린다
        tables = [
            r[0]
            for r in conn.execute(
                "select format('%I.%I', schemaname, tablename) from pg_tables where schemaname = 'public'"
            )
        ]
        if tables:
            conn.execute(f"truncate {', '.join(tables)} cascade")
        yield conn


@pytest.fixture
def store(settings, admin):
    with connect(settings) as conn:
        yield CardStore(conn)


@pytest.fixture
def first_card():
    return SCENARIOS / "first_card.json"


@pytest.fixture
def lookback_window():
    """AAPL: 거래일 전 봉 4개. MSFT: 거래일 당일(10-16)·그 뒤(10-19) 봉이 섞여 있다."""
    return SCENARIOS / "lookback_window.json"


@pytest.fixture
def events_and_tags():
    """거래일 TUE 2026-10-13 기준 일정·레버리지 태그. 시세는 비어 있다."""
    return SCENARIOS / "events_and_tags.json"


@pytest.fixture
def filings_day():
    """거래일 FRI 2026-10-16 공시·지표 일정·분류 응답. 공시 기간 [10-15 04:00, 10-16 04:00) ET. 시세는 비어 있다."""
    return SCENARIOS / "filings_day.json"


@pytest.fixture
def full_card():
    """세 줄을 다 채운 정상 카드. 커버 범위에 AAPL이 있어야 저장된다."""
    checked = datetime(2026, 10, 16, 7, 30, tzinfo=ET)
    return StockCard(
        ticker="AAPL",
        trading_day=date(2026, 10, 16),
        status=CardStatus.NORMAL,
        change_pct=Decimal("1.3"),
        change_status=LineStatus.CHECKED_FOUND,
        news_line=CardLine("Apple announced quarterly results (Company)", LineStatus.CHECKED_FOUND, checked, "SEC filings"),
        event_line=CardLine("No confirmed events found", LineStatus.CHECKED_NONE, checked, "Company calendar"),
        price_fact_line=CardLine("Not covered yet", LineStatus.UNSUPPORTED, checked, None),
    )
