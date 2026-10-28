"""DB 픽스처. 로컬 Supabase만 쓴다. 테스트마다 public 테이블을 비운다."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

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


def _wipe(conn) -> None:
    tables = [
        r[0]
        for r in conn.execute("select format('%I.%I', schemaname, tablename) from pg_tables where schemaname = 'public'")
    ]
    if tables:
        conn.execute(f"truncate {', '.join(tables)} cascade")
    conn.execute("delete from auth.users")  # 테스트 유저(make_user). settings가 로컬 DB만 받는다


@pytest.fixture
def admin(settings):
    """마이그레이션 소유자(postgres) 연결. 스키마 검사·역할 전환용. 시작 전과 끝난 뒤 public 테이블을 비운다
    (끝난 뒤: 마지막 테스트의 카드·실행 기록이 남으면 웹 테스트·로컬 화면이 그 데이터를 본다)."""
    with connect(settings) as conn:
        conn.execute("reset role")  # 비밀번호 숨김은 connect가 맡는다. 관리자 연결이라 service_role만 되돌린다
        _wipe(conn)
        yield conn
        conn.execute("reset role")  # 테스트가 role을 바꾼 채 끝났을 수 있다
        _wipe(conn)


@pytest.fixture
def make_user(admin) -> Callable[..., UUID]:
    """make_user(plan="free", timezone="America/Los_Angeles") -> user id.
    auth.users(id)는 admin, user_profile은 service_role로 넣는다."""
    def make(plan: str = "free", timezone: str = "America/Los_Angeles") -> UUID:
        [uid] = admin.execute("insert into auth.users (id) values (gen_random_uuid()) returning id").fetchone()
        with admin.transaction():
            admin.execute("set local role service_role")
            admin.execute("insert into public.user_profile (user_id, plan, timezone) values (%s, %s, %s)", (uid, plan, timezone))
        return uid

    return make


@pytest.fixture
def store(settings, admin):
    with connect(settings) as conn:
        yield CardStore(conn)


@pytest.fixture
def first_card():
    return SCENARIOS / "first_card.json"


@pytest.fixture
def lookback_window():
    """AAPL: 거래일 전 봉 5개. MSFT: 거래일 당일(10-16)·그 뒤(10-19) 봉이 섞여 있다."""
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
def etf_lite():
    """거래일 FRI 2026-10-16 ETF 카드(#10). SPY 편입 AAPL·MSFT(+못 찾은 회사 2), QQQ 편입 MSFT·AVGO, TQQQ(3배) → QQQ 편입.
    공시 중요도 AAPL 5 > AVGO 4 > MSFT 3(MSFT는 본문 없음 → 대체 줄). AVGO가 생성 대상이든 아니든 LLM 응답 순서가 같다."""
    return SCENARIOS / "etf_lite.json"


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
