"""입구 2: 마이그레이션이 적용된 로컬 DB가 직접 막는 규칙. 관리자 연결로 카탈로그 조회·역할 전환."""

import pytest
from psycopg import errors

from m30.models import Coverage

CARD_SQL = (
    "insert into public.stock_card (ticker, trading_day, status, change_pct, change_status)"
    " values ('AAPL', '2026-10-16', 'fallback', 1.3, 'checked_found')"
)


@pytest.fixture
def aapl(admin):
    admin.execute("insert into public.coverage (ticker, name) values ('AAPL', 'Apple Inc.')")
    return admin


def test_같은_종목·거래일_카드는_DB가_거부한다(aapl):
    aapl.execute(CARD_SQL)
    with pytest.raises(errors.UniqueViolation):
        aapl.execute(CARD_SQL)


def test_커버_범위에_없는_종목의_카드는_DB가_거부한다(admin):
    with pytest.raises(errors.ForeignKeyViolation):
        admin.execute(CARD_SQL)  # coverage가 비어 있다


@pytest.mark.parametrize("ticker", ["aapl", "", "ABCDEFGHIJK", "BRK B"], ids=["소문자", "빈_값", "11자", "공백"])
def test_티커_형식이_아니면_커버_범위에_넣을_수_없다(admin, ticker):
    with pytest.raises(errors.CheckViolation):
        admin.execute("insert into public.coverage (ticker, name) values (%s, 'Bad Ticker Inc.')", (ticker,))


CARD_COLUMNS = [
    "ticker", "trading_day", "status", "change_pct", "change_status",
    "news_line_text", "news_line_status", "news_line_checked_at", "news_line_source_scope",
    "event_line_text", "event_line_status", "event_line_checked_at", "event_line_source_scope",
    "price_fact_line_text", "price_fact_line_status", "price_fact_line_checked_at", "price_fact_line_source_scope",
    "updated_at",
]


def enum_values(conn, name):
    return [r[0] for r in conn.execute(
        "select e.enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid"
        " join pg_namespace n on n.oid = t.typnamespace"
        " where n.nspname = 'public' and t.typname = %s order by e.enumsortorder", (name,))]


def test_카드_컬럼은_정해진_목록뿐이고_방향_의견_필드가_없다(admin):
    columns = [r[0] for r in admin.execute(
        "select column_name from information_schema.columns"
        " where table_schema = 'public' and table_name = 'stock_card' order by ordinal_position")]
    assert columns == CARD_COLUMNS  # 콜·토크·방향·판정 컬럼은 영원히 없다 (ADR-0001)
    assert len(columns) == 18
    assert enum_values(admin, "card_status") == ["normal", "fallback"]
    assert enum_values(admin, "line_status") == ["checked_found", "checked_none", "delayed", "unsupported"]


CARD_COLS = "ticker, trading_day, status, change_pct, change_status"


@pytest.mark.parametrize(
    "columns, values",
    [
        # 줄 일부만 채움 (상태만 있고 문장·확인 시각 없음)
        (f"{CARD_COLS}, event_line_status", "'AAPL', '2026-10-16', 'fallback', 1.3, 'checked_found', 'checked_none'"),
        # 확인함인데 출처 범위 없음 (출처 범위는 미지원일 때만 비울 수 있다)
        (f"{CARD_COLS}, event_line_text, event_line_status, event_line_checked_at",
         "'AAPL', '2026-10-16', 'fallback', 1.3, 'checked_found', 'No confirmed events found', 'checked_none', now()"),
        # 정상인데 첫 번째 줄 없음
        (CARD_COLS, "'AAPL', '2026-10-16', 'normal', 1.3, 'checked_found'"),
        # 등락률이 있는데 지연
        (CARD_COLS, "'AAPL', '2026-10-16', 'fallback', 1.3, 'delayed'"),
        # 등락률에 확인함·없음은 없다
        (CARD_COLS, "'AAPL', '2026-10-16', 'fallback', null, 'checked_none'"),
    ],
    ids=["줄_일부만", "출처_범위_없음", "정상인데_첫_번째_줄_없음", "등락률_있는데_지연", "등락률_확인함·없음"],
)
def test_줄_상태가_빠지거나_어긋난_카드는_DB가_거부한다(aapl, columns, values):
    with pytest.raises(errors.CheckViolation):
        aapl.execute(f"insert into public.stock_card ({columns}) values ({values})")


def public_tables(conn):
    """public의 일반·파티션 테이블. 다음 티켓이 테이블을 추가해도 자동으로 검사된다."""
    return [r[0] for r in conn.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind in ('r', 'p') order by c.relname")]


def test_RLS가_꺼진_테이블이_없다(admin):
    rls_off = [r[0] for r in admin.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity")]
    assert {"coverage", "stock_card"} <= set(public_tables(admin))  # 검사 대상이 비어서 통과하는 것을 막는다
    assert rls_off == []


@pytest.fixture
def stored_card(store, full_card):
    store.upsert_coverage([Coverage("AAPL", "Apple Inc.")])
    store.upsert_card(full_card)


def as_role(conn, role, sql):
    with conn.transaction(force_rollback=True):
        conn.execute(f"set local role {role}")
        return conn.execute(sql).fetchall()


def test_로그인_없이는_DB에서_카드를_직접_읽을_수_없다(admin, stored_card):
    with pytest.raises(errors.InsufficientPrivilege):
        as_role(admin, "anon", "select * from public.stock_card")


def all_ops(conn, table):
    first_col = conn.execute(
        "select column_name from information_schema.columns"
        " where table_schema = 'public' and table_name = %s order by ordinal_position limit 1", (table,)).fetchone()[0]
    t = f"public.{table}"
    return {
        "select": f"select * from {t}",
        "insert": f"insert into {t} default values",  # 권한 검사가 행 검사보다 먼저라 제약 위반이 아니라 권한 오류가 나야 한다
        "update": f"update {t} set {first_col} = {first_col}",
        "delete": f"delete from {t}",
    }


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_anon·authenticated는_어떤_테이블도_읽거나_쓸_수_없다(admin, stored_card, role):
    allowed = []
    for table in public_tables(admin):
        for op, sql in all_ops(admin, table).items():
            try:
                as_role(admin, role, sql)
                allowed.append(f"{table}.{op}")
            except errors.InsufficientPrivilege:
                pass
    assert allowed == []
    # 권한 층만 따로: RLS가 막아 줘도 권한이 열려 있으면 실패. TRUNCATE는 RLS를 무시하므로 꼭 본다
    granted = [r[0] for r in admin.execute(
        "select t.relname || '.' || p.priv from pg_class t join pg_namespace n on n.oid = t.relnamespace,"
        " unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) as p(priv)"
        " where n.nspname = 'public' and t.relkind in ('r', 'p') and has_table_privilege(%s, t.oid, p.priv)",
        (role,))]
    assert granted == []


# 앱이 직접 읽어야 할 이유가 생긴 유저 테이블만 여기 넣는다 (ADR-0003을 다시 연 뒤, 같은 커밋에서)
AUTHENTICATED_POLICY_TABLES: frozenset[str] = frozenset()


def test_앱_역할에_적용되는_정책이_없다(admin):
    # TO를 빼면 roles = {public} = anon 포함이라 같이 막는다
    anon_policies = admin.execute(
        "select tablename, policyname from pg_policies"
        " where schemaname = 'public' and roles && array['anon', 'public']::name[]").fetchall()
    authenticated_tables = {r[0] for r in admin.execute(
        "select tablename from pg_policies where schemaname = 'public' and 'authenticated' = any(roles)")}
    assert anon_policies == []
    assert authenticated_tables <= AUTHENTICATED_POLICY_TABLES


def test_public_뷰는_security_invoker다(admin):
    definer_views = [r[0] for r in admin.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind = 'v' and not coalesce(c.reloptions, '{}') &&"
        " array['security_invoker=true', 'security_invoker=on', 'security_invoker=1', 'security_invoker=yes']")]
    materialized = [r[0] for r in admin.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind = 'm'")]
    assert definer_views == []
    assert materialized == []


def test_security_definer_함수가_없다(admin):
    definers = [r[0] for r in admin.execute(
        "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
        " where n.nspname = 'public' and p.prosecdef")]
    assert definers == []


def test_시간대_없는_시각_컬럼이_없다(admin):
    naive = admin.execute(
        "select table_name, column_name from information_schema.columns"
        " where table_schema = 'public' and data_type = 'timestamp without time zone'").fetchall()
    assert naive == []
