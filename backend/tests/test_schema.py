"""입구 2: 마이그레이션이 적용된 로컬 DB가 직접 막는 규칙. 관리자 연결로 카탈로그 조회·역할 전환."""

import dataclasses
import json
from datetime import date, datetime, timedelta

import pytest
from psycopg import errors

from m30.config import ET
from m30.models import IMPORTANCE_MAX, Coverage, HoldStage, HoldState, NewsKind, Relation, RelationBasis
from test_collect_classify import AAPL, FRI, MSFT, filing, label, reply, run, scenario

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
    "updated_at", "leverage_tag", "news_line_accession", "previous_trading_day", "publish_suspended", "news_line_filing_count",
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
    assert columns == CARD_COLUMNS  # 콜·토크·방향·판정 컬럼은 영원히 없다 (ADR-0001). 출처 공시 열은 방향 의견이 아니다
    assert len(columns) == 23
    assert enum_values(admin, "card_status") == ["normal", "fallback"]
    assert enum_values(admin, "line_status") == ["checked_found", "checked_none", "delayed", "unsupported"]


CARD_COLS = "ticker, trading_day, status, change_pct, change_status"


@pytest.mark.parametrize("leverage", ["1", "0", "0.5"], ids=["1배", "0", "1_미만_양수"])
def test_레버리지_배율이_1_이하의_양수나_0이면_커버_범위에_넣을_수_없다(admin, leverage):
    with pytest.raises(errors.CheckViolation):
        admin.execute("insert into public.coverage (ticker, name, leverage) values ('TQQQ', 'ProShares UltraPro QQQ', %s)",
                      (leverage,))


def test_빈_레버리지_태그는_DB가_거부한다(aapl):
    with pytest.raises(errors.CheckViolation):
        aapl.execute(f"insert into public.stock_card ({CARD_COLS}, leverage_tag)"
                     " values ('AAPL', '2026-10-16', 'fallback', 1.3, 'checked_found', '')")


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
    tables = {"coverage", "stock_card", "sec_filing", "indicator_release", "filing_classification", "hold_queue",
              "stock_card_revision", "user_profile", "my_stock", "my_stock_history", "default_ticker", "pipeline_run",
              "fund_holdings", "morning_notice", "market_glance", "market_news_item", "earnings_filing", "earnings_estimate",
              "sec_annual_report", "annual_report_mentions", "stock_relation", "quiet_fact",
              "locked_slot_tap"}
    assert tables <= set(public_tables(admin))  # 검사 대상이 비어서 통과하는 것을 막는다
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
        "select column_name from information_schema.columns"  # identity 열은 갱신 자체를 권한 검사 전에 거부한다
        " where table_schema = 'public' and table_name = %s and is_identity = 'NO' order by ordinal_position limit 1",
        (table,)).fetchone()[0]
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


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_anon·authenticated는_public_함수를_실행할_수_없다(admin, role):
    executable = [r[0] for r in admin.execute(
        "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
        " where n.nspname = 'public' and has_function_privilege(%s, p.oid, 'EXECUTE')", (role,))]
    functions = [r[0] for r in admin.execute(
        "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public'")]
    assert {"keep_card_revision", "republish_from_hold_queue", "user_local_date", "user_profile_timezone",
            "lock_my_stocks_on_plan_change", "my_stock_rules", "log_my_stock_change", "dispatch_morning_workflow",
            "my_quiet_facts", "count_locked_slot_tap"} <= set(functions)  # 검사 대상이 비어서 통과하지 않게
    assert executable == []


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


FILING_SQL = (
    "insert into public.sec_filing (accession, cik, form, accepted_at, items, trading_day, payload)"
    " values (%s, %s, '8-K', '2026-10-15 16:31-04', '{2.02}', '2026-10-16', '{}')"
)
ACCESSION = "0000320193-26-000101"


def test_같은_접수번호의_공시_원본은_DB가_하나만_받는다(admin):
    admin.execute(FILING_SQL, (ACCESSION, "0000320193"))
    with pytest.raises(errors.UniqueViolation):
        admin.execute(FILING_SQL, (ACCESSION, "0000320193"))


@pytest.mark.parametrize(
    "sql, params",
    [
        (FILING_SQL, ("0000320193-26-101", "0000320193")),
        (FILING_SQL, ("", "0000320193")),
        (FILING_SQL, (ACCESSION, "320193")),
        ("insert into public.coverage (ticker, name, cik) values ('AAPL', 'Apple Inc.', %s)", ("320193",)),
        ("insert into public.coverage (ticker, name, cik) values ('AAPL', 'Apple Inc.', %s)", ("000032019A",)),
    ],
    ids=["접수번호_자릿수", "빈_접수번호", "공시_CIK_0_채움_없음", "커버_범위_CIK_0_채움_없음", "커버_범위_CIK_문자"],
)
def test_접수번호·CIK_형식이_아니면_DB가_거부한다(admin, sql, params):
    with pytest.raises(errors.CheckViolation):
        admin.execute(sql, params)


@pytest.fixture
def aapl_filing(aapl):
    aapl.execute(FILING_SQL, (ACCESSION, "0000320193"))
    return aapl


def classify_row(conn, kind="other", importance=1, is_opinion=False, unclassified=None):
    with conn.transaction(force_rollback=True):
        conn.execute(
            "insert into public.filing_classification (accession, ticker, kind, importance, is_opinion, unclassified)"
            " values (%s, 'AAPL', %s, %s, %s, %s)",
            (ACCESSION, kind, importance, is_opinion, unclassified),
        )


@pytest.mark.parametrize(
    "row",
    [
        {"kind": None, "importance": None, "is_opinion": None},
        {"importance": None, "is_opinion": None},
        {"unclassified": "missing"},
    ],
    ids=["다_비움", "종류만", "분류됨_더하기_사유"],
)
def test_분류_행은_분류됨이나_미분류_한쪽만_채울_수_있다(aapl_filing, row):
    with pytest.raises(errors.CheckViolation):
        classify_row(aapl_filing, **row)


def test_분류_종류와_중요도_범위는_코드와_DB가_같다(aapl_filing):
    for kind in NewsKind:  # U1
        classify_row(aapl_filing, kind=kind.value)
    for importance in (1, IMPORTANCE_MAX):  # U2
        classify_row(aapl_filing, importance=importance)
    for bad in ({"kind": "rumor"}, {"importance": 0}, {"importance": IMPORTANCE_MAX + 1}):
        with pytest.raises(errors.CheckViolation):
            classify_row(aapl_filing, **bad)


# 보류함 재발행·수정 이력(U3·U4): 대시보드에서 service_role로 보류함 행을 고치는 것과 같은 SQL
HUMAN = "Apple named a new CFO (SEC filing)"
REPLACEMENT = "Apple filed a company update (SEC filing)"


@pytest.fixture
def held(store, admin):
    """AAPL 카드 = 대체 줄 + 보류함 행 1개(금지어 두 번), MSFT 카드 = 공시 없음. 파이프라인으로 만든다."""
    buy = json.dumps({"sentence": "Apple agreed to buy a startup"})
    run(store, scenario([AAPL, MSFT], [filing(1, body="Apple agreed to acquire a startup.")], [reply(label(1)), buy, buy]))
    return store


def as_service_role(conn, sql, params=()):
    with conn.transaction():
        conn.execute("set local role service_role")
        conn.execute(sql, params)


def table_contents(conn, skip):
    return {t: sorted(r[0] for r in conn.execute(f"select t::text from public.{t} t"))
            for t in public_tables(conn) if t not in skip}


def revisions(conn):
    return conn.execute("select ticker, trading_day, previous->>'news_line_text' from public.stock_card_revision order by id").fetchall()


def test_보류함에서_재발행하면_그_카드의_첫_번째_줄만_바뀌고_다른_테이블은_그대로다(admin, held):
    before = {c.ticker: c for c in held.list_cards(FRI)}
    others = table_contents(admin, {"stock_card", "hold_queue", "stock_card_revision"})
    assert before["AAPL"].news_line.text == REPLACEMENT and others["sec_filing"]  # 검사 대상이 비어서 통과하지 않게

    as_service_role(admin, "update public.hold_queue set edited_text = %s, state = 'republished'", (HUMAN,))

    after = {c.ticker: c for c in held.list_cards(FRI)}
    aapl = before["AAPL"]
    assert after["AAPL"].news_line == dataclasses.replace(aapl.news_line, text=HUMAN)  # 줄 상태·출처 범위·확인 시각 그대로
    assert dataclasses.replace(after["AAPL"], news_line=aapl.news_line, updated_at=None) == dataclasses.replace(aapl, updated_at=None)
    assert after["MSFT"] == before["MSFT"]
    assert table_contents(admin, {"stock_card", "hold_queue", "stock_card_revision"}) == others  # 아침 알림(#12)도 여기 들어온다
    assert revisions(admin) == [("AAPL", FRI, REPLACEMENT)]  # 이전 내용은 수정 이력에


def test_수정됨은_카드를_바꾸지_않는다(admin, held):
    before = held.list_cards(FRI)
    as_service_role(admin, "update public.hold_queue set edited_text = %s, state = 'edited'", (HUMAN,))

    assert held.list_cards(FRI) == before
    assert revisions(admin) == []


@pytest.mark.parametrize("state", ["edited", "republished"])
def test_고친_문장_없이_수정됨이나_재발행으로_바꿀_수_없다(admin, held, state):
    with pytest.raises(errors.CheckViolation):
        as_service_role(admin, "update public.hold_queue set state = %s", (state,))


def test_공시_줄이_없는_카드는_재발행이_실패한다(admin, held):
    admin.execute("update public.stock_card set news_line_text = 'No new SEC filings found', news_line_status = 'checked_none',"
                  " news_line_accession = null, news_line_filing_count = null where ticker = 'AAPL'")
    with pytest.raises(errors.RaiseException):
        as_service_role(admin, "update public.hold_queue set edited_text = %s, state = 'republished'", (HUMAN,))


def test_보류함_단계·상태는_코드와_DB가_같다(admin):
    assert enum_values(admin, "hold_stage") == [s.value for s in HoldStage]
    assert enum_values(admin, "hold_state") == [s.value for s in HoldState]


def test_수정_이력은_추가만_할_수_있다(admin):
    allowed = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
               if admin.execute("select has_table_privilege('service_role', 'public.stock_card_revision', %s)", (p,)).fetchone()[0]]
    assert allowed == ["SELECT", "INSERT"]


def test_새_카드는_발행_중단이_꺼져_있다(aapl):
    aapl.execute(CARD_SQL)

    assert aapl.execute("select publish_suspended from public.stock_card").fetchall() == [(False,)]


NEWS_COLS = f"{CARD_COLS}, news_line_text, news_line_status, news_line_checked_at, news_line_source_scope"
FOUND = "'Apple named a new CFO +2 more (SEC filing)', 'checked_found', now(), 'SEC filings'"


def insert_filing_count(conn, news, count):
    """news = 첫 번째 줄 값 4개(SQL), None = 축소판(첫 번째 줄 없음)."""
    columns, values = (CARD_COLS, "'AAPL', '2026-10-16', 'fallback', 1.3, 'checked_found'") if news is None else (
        NEWS_COLS, f"'AAPL', '2026-10-16', 'normal', 1.3, 'checked_found', {news}")
    conn.execute(f"insert into public.stock_card ({columns}, news_line_filing_count) values ({values}, %s)", (count,))


@pytest.mark.parametrize(
    "news, count",
    [
        ("'No new SEC filings found', 'checked_none', now(), 'SEC filings'", 1),
        ("'Update delayed', 'delayed', now(), 'SEC filings'", 1),
        ("'Not covered yet', 'unsupported', now(), null", 1),
        (None, 1),
        (FOUND, 0),
    ],
    ids=["확인함·없음", "지연", "미지원", "축소판", "확인함·있음인데_0"],
)
def test_첫_번째_줄_공시_수는_확인함·있음_줄에만_1_이상으로_둘_수_있다(aapl, news, count):
    with pytest.raises(errors.CheckViolation):
        insert_filing_count(aapl, news, count)


@pytest.mark.parametrize("count", [None, 1, 3], ids=["#63_전_카드", "1건", "3건"])
def test_확인함·있음_줄은_공시_수가_비었거나_1_이상이면_받는다(aapl, count):
    insert_filing_count(aapl, FOUND, count)

    assert aapl.execute("select news_line_filing_count from public.stock_card").fetchall() == [(count,)]


def test_종가_날짜가_카드_거래일과_같거나_뒤면_DB가_거부한다(aapl):
    for day in ("2026-10-16", "2026-10-19"):
        with pytest.raises(errors.CheckViolation):
            aapl.execute(f"insert into public.stock_card ({CARD_COLS}, previous_trading_day)"
                         f" values ('AAPL', '2026-10-16', 'fallback', 1.3, 'checked_found', '{day}')")


def test_실행_기록은_서버가_넣고_끝_시각과_실행_요약만_고칠_수_있고_지울_수_없다(admin):
    allowed = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
               if admin.execute("select has_table_privilege('service_role', 'public.pipeline_run', %s)", (p,)).fetchone()[0]]
    updatable = [r[0] for r in admin.execute(
        "select column_name from information_schema.columns where table_schema = 'public' and table_name = 'pipeline_run'"
        " and has_column_privilege('service_role', 'public.pipeline_run', column_name, 'UPDATE') order by column_name")]
    assert allowed == ["SELECT", "INSERT"]  # UPDATE는 컬럼 단위로만
    assert updatable == ["failed", "finished_at", "summary"]


@pytest.mark.parametrize(
    "columns, values",
    [
        ("finished_at, failed, summary", "now(), false, '[]'"),  # 배열: 키로 읽는 월 합계 조회가 깨진다
        ("failed, summary", "false, '{}'"),  # 끝나지 않은 실행에 요약
        ("finished_at, summary", "now(), '{}'"),  # 실패 여부 없이 요약
        ("finished_at, failed", "now(), true"),  # 요약 없이 실패 여부
    ],
    ids=["배열_요약", "끝_시각_없음", "실패_여부_없음", "요약_없음"],
)
def test_실행_요약은_끝난_실행에_실패_여부와_함께_객체로만_남는다(admin, columns, values):
    with pytest.raises(errors.CheckViolation):
        as_service_role(admin, f"insert into public.pipeline_run (trading_day, {columns}) values ('2026-10-16', {values})")


def test_실행_기록의_끝_시각은_시작_시각보다_앞설_수_없다(admin):
    with pytest.raises(errors.CheckViolation):
        as_service_role(admin, "insert into public.pipeline_run (trading_day, started_at, finished_at)"
                               " values ('2026-10-16', '2026-10-16 05:00-04', '2026-10-16 04:59-04')")


HOLD_SQL = ("insert into public.hold_queue (ticker, trading_day, accession, stage, draft_text, rules, replacement_text, edited_text)"
            " values (%s, '2026-10-16', %s, %s, %s, %s, %s, %s)")
HOLD_ROW = {"ticker": "AAPL", "accession": ACCESSION, "stage": "draft", "draft_text": None, "rules": ["1 draft: no_text"],
            "replacement_text": REPLACEMENT, "edited_text": None}


@pytest.fixture
def aapl_card(aapl_filing):
    aapl_filing.execute(f"insert into public.stock_card ({CARD_COLS}, news_line_text, news_line_status, news_line_checked_at,"
                        " news_line_source_scope, news_line_accession) values ('AAPL', '2026-10-16', 'normal', 1.3,"
                        f" 'checked_found', %s, 'checked_found', now(), 'SEC filings', %s)", (REPLACEMENT, ACCESSION))
    return aapl_filing


def hold_row(conn, **changes):
    row = HOLD_ROW | changes
    with conn.transaction(force_rollback=True):
        conn.execute(HOLD_SQL, tuple(row.values()))


def test_보류함_행은_대체_줄_행과_정정_공시_행_모양만_받는다(aapl_card):
    hold_row(aapl_card)
    hold_row(aapl_card, stage="amended_filing", rules=["정정 공시 있음"], replacement_text=None)


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"rules": []}, errors.CheckViolation),
        ({"stage": "amended_filing", "rules": ["정정 공시 있음"]}, errors.CheckViolation),  # 정정 행에 대체 줄
        ({"replacement_text": None}, errors.CheckViolation),  # 검수 행에 대체 줄 없음
        ({"stage": "amended_filing", "replacement_text": None, "draft_text": "Apple named a CFO"}, errors.CheckViolation),
        ({"edited_text": ""}, errors.CheckViolation),
        ({"ticker": "MSFT"}, errors.ForeignKeyViolation),  # 카드가 없는 종목
    ],
    ids=["규칙_없음", "정정_행에_대체_줄", "검수_행에_대체_줄_없음", "정정_행에_원래_문장", "빈_고친_문장", "없는_카드"],
)
def test_보류함_행_규칙을_DB가_막는다(aapl_card, changes, error):
    with pytest.raises(error):
        hold_row(aapl_card, **changes)


def test_데이터_상태_문구_줄에는_출처_공시를_둘_수_없다(aapl_filing):
    with pytest.raises(errors.CheckViolation):
        aapl_filing.execute(f"insert into public.stock_card ({CARD_COLS}, news_line_text, news_line_status, news_line_checked_at,"
                            " news_line_source_scope, news_line_accession) values ('AAPL', '2026-10-16', 'normal', 1.3,"
                            " 'checked_found', 'No new SEC filings found', 'checked_none', now(), 'SEC filings', %s)",
                            (ACCESSION,))


def test_축소판에는_출처_공시를_둘_수_없다(aapl_filing):
    with pytest.raises(errors.CheckViolation):
        aapl_filing.execute(f"insert into public.stock_card ({CARD_COLS}, news_line_accession)"
                            " values ('AAPL', '2026-10-16', 'fallback', 1.3, 'checked_found', %s)", (ACCESSION,))


def test_재발행한_행의_고친_문장을_다시_고치면_카드도_따라_바뀐다(admin, held):
    second = "Apple named a new chief financial officer (SEC filing)"
    as_service_role(admin, "update public.hold_queue set edited_text = %s, state = 'republished'", (HUMAN,))
    as_service_role(admin, "update public.hold_queue set edited_text = %s", (second,))

    assert {c.ticker: c.news_line.text for c in held.list_cards(FRI)}["AAPL"] == second
    assert revisions(admin) == [("AAPL", FRI, REPLACEMENT), ("AAPL", FRI, HUMAN)]
    as_service_role(admin, "update public.hold_queue set rules = rules")  # 상태·문장이 그대로인 갱신은 카드를 건드리지 않는다

    assert len(revisions(admin)) == 2


@pytest.mark.parametrize("holdings_ticker", ["qqq", "", "ABCDEFGHIJK", "Q QQ"], ids=["소문자", "빈_값", "11자", "공백"])
def test_편입_종목을_읽을_ETF_티커가_티커_형식이_아니면_커버_범위에_넣을_수_없다(admin, holdings_ticker):
    with pytest.raises(errors.CheckViolation):
        admin.execute("insert into public.coverage (ticker, name, holdings_ticker) values ('TQQQ', 'ProShares UltraPro QQQ', %s)",
                      (holdings_ticker,))


def test_편입_종목_보고는_서버가_추가만_하고_고치거나_지울_수_없다(admin):
    admin.execute("insert into public.coverage (ticker, name, holdings_ticker) values ('SPY', 'SPDR S&P 500 ETF Trust', 'SPY')")
    as_service_role(admin, "insert into public.fund_holdings (accession, fund, period_end, holdings, payload)"
                           " values ('0000884394-26-000101', 'SPY', '2026-06-30', '[]', '<edgarSubmission/>')")
    allowed = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
               if admin.execute("select has_table_privilege('service_role', 'public.fund_holdings', %s)", (p,)).fetchone()[0]]

    assert allowed == ["SELECT", "INSERT"]  # 원본은 처음 받은 그대로 둔다
    for sql in ("update public.fund_holdings set payload = ''", "delete from public.fund_holdings"):
        with pytest.raises(errors.InsufficientPrivilege):
            as_service_role(admin, sql)


DISPATCH_URL = "https://api.github.com/repos/Paul-sinn/market_in_30sec/actions/workflows/morning.yml/dispatches"


def test_아침_dispatch_cron_작업은_평일_09시17분_UTC에_함수만_부르고_토큰_값이_없다(admin):
    jobs = admin.execute("select schedule, command, username, active from cron.job where jobname = 'morning_dispatch'").fetchall()
    assert jobs == [("17 9 * * 1-5", "select public.dispatch_morning_workflow()", "postgres", True)]
    [body] = admin.execute("select prosrc from pg_proc where oid = 'public.dispatch_morning_workflow()'::regprocedure").fetchone()
    assert DISPATCH_URL in body
    assert "vault.decrypted_secrets" in body and "'github_dispatch_token'" in body  # 토큰은 Vault에서만
    for token_shape in ("ghp_", "github_pat_", "gho_", "ghs_"):  # GitHub 토큰 접두사: 값이 코드에 박히지 않았다
        assert token_shape not in body + jobs[0][1]
    # cron(postgres = 소유자)만 부른다. 서버(service_role)도 GitHub 실행을 시작할 수 없다
    assert admin.execute("select has_function_privilege('service_role', 'public.dispatch_morning_workflow()', 'EXECUTE')").fetchone() == (False,)


def queued_dispatches(conn):
    return conn.execute("select count(*) from net.http_request_queue where url = %s", (DISPATCH_URL,)).fetchone()[0]


def test_Vault에_토큰이_없으면_아침_dispatch는_요청을_만들지_않는다(admin):
    with admin.transaction(force_rollback=True):  # 로컬 Vault에 토큰이 있어도 이 검사 안에서만 지운다
        admin.execute("delete from vault.secrets where name = 'github_dispatch_token'")
        assert admin.execute("select public.dispatch_morning_workflow()").fetchone() == (None,)
        assert queued_dispatches(admin) == 0


TOKEN_CANARY = "dispatchTokenCanary72"


def test_Vault_토큰이_있으면_main으로_morning_workflow_dispatch_요청_하나를_Bearer_헤더로_만든다(admin):
    # 커밋하지 않는다: pg_net 작업자는 커밋된 요청만 보내므로 GitHub에 아무것도 가지 않는다
    with admin.transaction(force_rollback=True):
        admin.execute("delete from vault.secrets where name = 'github_dispatch_token'")
        admin.execute("select vault.create_secret(%s, 'github_dispatch_token')", (TOKEN_CANARY,))
        [request_id] = admin.execute("select public.dispatch_morning_workflow()").fetchone()
        method, url, headers, body = admin.execute(
            "select method, url, headers, convert_from(body, 'utf8') from net.http_request_queue where id = %s", (request_id,)
        ).fetchone()
        assert (method, url, json.loads(body)) == ("POST", DISPATCH_URL, {"ref": "main"})
        assert headers == {"Authorization": f"Bearer {TOKEN_CANARY}", "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json", "User-Agent": "market_in_30sec-morning-dispatch"}
    assert queued_dispatches(admin) == 0


# 시장 한눈에(#11): 거래일마다 한 행, 줄 모양은 카드와 같다
GLANCE_COLUMNS = [
    "trading_day",
    "close_line_text", "close_line_status", "close_line_checked_at", "close_line_source_scope",
    "indicator_line_text", "indicator_line_status", "indicator_line_checked_at", "indicator_line_source_scope",
    "market_news_line_text", "market_news_line_status", "market_news_line_checked_at", "market_news_line_source_scope",
    "market_news_hold_draft", "market_news_hold_rules", "updated_at",
]
GLANCE_SQL = (
    "insert into public.market_glance (trading_day, close_line_text, close_line_status, close_line_checked_at,"
    " close_line_source_scope, indicator_line_text, indicator_line_status, indicator_line_checked_at,"
    " indicator_line_source_scope, market_news_line_text, market_news_line_status, market_news_line_checked_at,"
    " market_news_line_source_scope, market_news_hold_draft, market_news_hold_rules)"
    " values ('2026-10-16', 'Update delayed', 'delayed', now(), 'Daily prices',"
    " 'Not covered yet', 'unsupported', now(), null, %(news_text)s, %(news_status)s, now(), %(news_scope)s, %(draft)s, %(rules)s)"
)
GLANCE_ROW = {"news_text": "Not covered yet", "news_status": "unsupported", "news_scope": None, "draft": None, "rules": None}


def test_시장_한눈에_컬럼은_정해진_목록뿐이고_방향_의견_필드가_없다(admin):
    columns = [r[0] for r in admin.execute(
        "select column_name from information_schema.columns"
        " where table_schema = 'public' and table_name = 'market_glance' order by ordinal_position")]
    assert columns == GLANCE_COLUMNS  # 콜·토크·방향 컬럼은 없다 (ADR-0001)


def test_시장_한눈에는_거래일마다_한_행이고_서버는_고칠_수만_있고_지울_수_없다(admin):
    as_service_role(admin, GLANCE_SQL, GLANCE_ROW)
    allowed = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
               if admin.execute("select has_table_privilege('service_role', 'public.market_glance', %s)", (p,)).fetchone()[0]]

    assert allowed == ["SELECT", "INSERT", "UPDATE"]  # 재실행 = upsert
    with pytest.raises(errors.UniqueViolation):
        admin.execute(GLANCE_SQL, GLANCE_ROW)
    with pytest.raises(errors.InsufficientPrivilege):
        as_service_role(admin, "delete from public.market_glance")


@pytest.mark.parametrize(
    "changes",
    [
        {"news_status": "checked_found", "news_text": "Contoso Labor Bureau reported jobs data"},  # 확인함인데 출처 범위 없음
        {"news_status": "delayed", "news_text": "Update delayed", "news_scope": "Official releases",
         "draft": "Contoso said stocks will rise"},  # 걸린 규칙 없이 초안만
        {"news_status": "checked_found", "news_text": "Contoso Labor Bureau reported jobs data", "news_scope": "Official releases",
         "rules": ["1 fact_check: forecast"]},  # 보류 기록이 있는데 통과한 줄
        {"news_status": "delayed", "news_text": "Update delayed", "news_scope": "Official releases", "rules": []},  # 빈 규칙
        {"news_status": "delayed", "news_text": "Update delayed", "news_scope": "Official releases", "draft": "",
         "rules": ["1 draft: empty"]},  # 빈 초안
    ],
    ids=["출처_범위_없음", "초안만", "통과한_줄에_규칙", "빈_규칙", "빈_초안"],
)
def test_시장_한눈에_줄_범위와_보류_기록_규칙을_DB가_막는다(admin, changes):
    with pytest.raises(errors.CheckViolation):
        as_service_role(admin, GLANCE_SQL, GLANCE_ROW | changes)


def test_시장_한눈에_보류_기록은_지연_줄에_규칙과_함께_남는다(admin):
    as_service_role(admin, GLANCE_SQL, GLANCE_ROW | {"news_status": "delayed", "news_text": "Update delayed",
                                                     "news_scope": "Official releases", "rules": ["1 draft: llm_failed"]})


def test_시장_전체_소식_원본은_서버가_추가만_하고_고치거나_지울_수_없다(admin):
    as_service_role(admin, "insert into public.market_news_item (source, key, published_at, trading_day, payload)"
                           " values ('Contoso Labor Bureau', 'jobs-1', '2026-10-15 08:30-04', '2026-10-16', '{}')")
    allowed = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
               if admin.execute("select has_table_privilege('service_role', 'public.market_news_item', %s)", (p,)).fetchone()[0]]

    assert allowed == ["SELECT", "INSERT"]
    for sql in ("update public.market_news_item set payload = ''", "delete from public.market_news_item"):
        with pytest.raises(errors.InsufficientPrivilege):
            as_service_role(admin, sql)


# 실적 추정일(#57): 실적 공시 시각과 거래일별 추정. 둘 다 추가만 하는 새 표
EARNINGS_FILING_SQL = "insert into public.earnings_filing (accession, cik, accepted_at) values (%s, %s, '2025-10-30 16:30-04')"
ESTIMATE_SQL = (
    "insert into public.earnings_estimate (ticker, trading_day, estimate_day, timing, basis_accession)"
    " values ('AAPL', '2026-10-16', '2026-10-29', %s, %s)"
)
BASIS = "0000320193-25-000101"


def service_role_privileges(conn, table):
    return [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            if conn.execute("select has_table_privilege('service_role', %s, %s)", (f"public.{table}", p)).fetchone()[0]]


def test_실적_공시_시각은_서버가_추가만_하고_고치거나_지울_수_없다(admin):
    as_service_role(admin, EARNINGS_FILING_SQL, (BASIS, "0000320193"))

    assert service_role_privileges(admin, "earnings_filing") == ["SELECT", "INSERT"]  # 처음 읽은 시각을 그대로 둔다
    with pytest.raises(errors.UniqueViolation):
        admin.execute(EARNINGS_FILING_SQL, (BASIS, "0000320193"))
    for sql in ("update public.earnings_filing set accepted_at = now()", "delete from public.earnings_filing"):
        with pytest.raises(errors.InsufficientPrivilege):
            as_service_role(admin, sql)


@pytest.fixture
def aapl_basis(aapl):
    aapl.execute(EARNINGS_FILING_SQL, (BASIS, "0000320193"))
    return aapl


def test_실적_추정_행은_종목·거래일마다_하나이고_서버는_고칠_수만_있고_지울_수_없다(aapl_basis):
    as_service_role(aapl_basis, ESTIMATE_SQL, ("after_close", BASIS))

    assert service_role_privileges(aapl_basis, "earnings_estimate") == ["SELECT", "INSERT", "UPDATE"]  # 재실행 = upsert
    with pytest.raises(errors.UniqueViolation):
        aapl_basis.execute(ESTIMATE_SQL, ("after_close", BASIS))
    as_service_role(aapl_basis, "update public.earnings_estimate set timing = 'unknown'")
    with pytest.raises(errors.InsufficientPrivilege):
        as_service_role(aapl_basis, "delete from public.earnings_estimate")


@pytest.mark.parametrize("timing, ok", [("before_open", True), ("after_close", True), ("unknown", True),
                                        ("during_market", False), ("", False), (None, False)])
def test_실적_추정_시점은_before_open·after_close·unknown만_받는다(aapl_basis, timing, ok):
    if ok:
        aapl_basis.execute(ESTIMATE_SQL, (timing, BASIS))
    else:
        with pytest.raises((errors.CheckViolation, errors.NotNullViolation)):
            aapl_basis.execute(ESTIMATE_SQL, (timing, BASIS))


@pytest.mark.parametrize(
    "sql, params, error",
    [
        (ESTIMATE_SQL, ("unknown", "0000320193-25-000999"), errors.ForeignKeyViolation),  # 저장되지 않은 실적 공시
        (EARNINGS_FILING_SQL, ("0000320193-25-101", "0000320193"), errors.CheckViolation),
        (EARNINGS_FILING_SQL, ("", "0000320193"), errors.CheckViolation),
        (EARNINGS_FILING_SQL, (BASIS, "320193"), errors.CheckViolation),
        ("insert into public.earnings_estimate (ticker, trading_day, estimate_day, timing, basis_accession)"
         " values ('MSFT', '2026-10-16', '2026-10-27', 'unknown', %s)", (BASIS,), errors.ForeignKeyViolation),  # 커버 범위 밖 종목
    ],
    ids=["근거_공시_없음", "접수번호_자릿수", "빈_접수번호", "CIK_0_채움_없음", "커버_범위_밖_종목"],
)
def test_실적_추정의_근거_접수번호는_저장된_실적_공시여야_하고_접수번호·CIK_형식이_아니면_거부한다(aapl_basis, sql, params, error):
    with pytest.raises(error):
        aapl_basis.execute(sql, params)


# 분기 작업(#60): 10-K 원문 표와 업종 코드. 추가만
ANNUAL_SQL = "insert into public.sec_annual_report (accession, cik, accepted_at, body) values (%s, %s, %s, %s)"
ANNUAL_ROW = ("0000320193-25-000079", "0000320193", "2025-10-31 18:05:02-04", "Item 1. Business")


def test_10_K_원문은_서버가_추가만_하고_고치거나_지울_수_없다(admin):
    as_service_role(admin, ANNUAL_SQL, ANNUAL_ROW)

    assert service_role_privileges(admin, "sec_annual_report") == ["SELECT", "INSERT"]  # 처음 받은 원문을 그대로 둔다
    with pytest.raises(errors.UniqueViolation):
        admin.execute(ANNUAL_SQL, ANNUAL_ROW)
    for sql in ("update public.sec_annual_report set body = 'x'", "delete from public.sec_annual_report"):
        with pytest.raises(errors.InsufficientPrivilege):
            as_service_role(admin, sql)


@pytest.mark.parametrize(
    "row, error",
    [
        (("0000320193-25-79", *ANNUAL_ROW[1:]), errors.CheckViolation),
        ((ANNUAL_ROW[0], "320193", *ANNUAL_ROW[2:]), errors.CheckViolation),
        ((*ANNUAL_ROW[:3], ""), errors.CheckViolation),
        ((*ANNUAL_ROW[:2], None, ANNUAL_ROW[3]), errors.NotNullViolation),
    ],
    ids=["접수번호_형식_밖", "CIK_6자리", "빈_본문", "접수_시각_없음"],
)
def test_10_K_원문_형식이_틀리면_DB가_거부한다(admin, row, error):
    with pytest.raises(error):
        admin.execute(ANNUAL_SQL, row)


def test_8_K_공시_표는_그대로다(admin):
    columns = [r[0] for r in admin.execute(
        "select column_name from information_schema.columns"
        " where table_schema = 'public' and table_name = 'sec_filing' order by ordinal_position")]

    assert columns == ["accession", "cik", "form", "accepted_at", "items", "trading_day", "received_at", "payload", "report_date"]
    with pytest.raises(errors.CheckViolation):  # 10-K는 첫 번째 줄 분류 대상이 아니다
        admin.execute(FILING_SQL.replace("'8-K'", "'10-K'"), (ACCESSION, "0000320193"))


@pytest.mark.parametrize("sic, ok", [("3571", True), (None, True), ("357", False), ("35711", False), ("35A1", False), ("", False)])
def test_업종_코드는_네_자리_숫자만_받는다(admin, sic, ok):
    sql = "insert into public.coverage (ticker, name, cik, sic) values ('AAPL', 'Apple', '0000320193', %s)"
    if ok:
        admin.execute(sql, (sic,))
    else:
        with pytest.raises(errors.CheckViolation):
            admin.execute(sql, (sic,))


# 연관 종목(#64): 10-K 언급(추가만)과 종목별 연관 종목(종목 단위로 지우고 다시 씀)
MENTIONS_SQL = "insert into public.annual_report_mentions (accession, mentions) values (%s, %s)"
RELATION_COLUMNS = "ticker, related_ticker, relation, basis, rank, source_accession, evidence"
RELATION_SQL = f"insert into public.stock_relation ({RELATION_COLUMNS}) values (%s, %s, %s, %s, %s, %s, %s)"
OWN = ("AAPL", "MSFT", "competitor", "own_10k", 1, ANNUAL_ROW[0], "We compete with Microsoft.")
PEER = ("AAPL", "DELL", "peer", "sic", 2, None, None)


@pytest.fixture
def related(admin):
    """AAPL·MSFT·DELL 커버 범위 + AAPL 10-K 한 건."""
    admin.execute("insert into public.coverage (ticker, name) values ('AAPL', 'Apple'), ('MSFT', 'Microsoft'), ('DELL', 'Dell')")
    admin.execute(ANNUAL_SQL, ANNUAL_ROW)
    return admin


def test_10_K_언급은_서버가_추가만_하고_연관_종목은_지우고_다시_쓸_수만_있다(related):
    as_service_role(related, MENTIONS_SQL, (ANNUAL_ROW[0], "[]"))
    as_service_role(related, RELATION_SQL, OWN)

    assert service_role_privileges(related, "annual_report_mentions") == ["SELECT", "INSERT"]  # 같은 10-K는 다시 뽑지 않는다
    assert service_role_privileges(related, "stock_relation") == ["SELECT", "INSERT", "DELETE"]  # update 없음
    with pytest.raises(errors.UniqueViolation):
        related.execute(MENTIONS_SQL, (ANNUAL_ROW[0], "[]"))
    for sql in ("update public.annual_report_mentions set mentions = '[]'", "delete from public.annual_report_mentions",
                "update public.stock_relation set rank = 2"):
        with pytest.raises(errors.InsufficientPrivilege):
            as_service_role(related, sql)
    as_service_role(related, "delete from public.stock_relation")


def test_연관_종목은_종목당_순위_1_5_하나씩이라_5개를_넘을_수_없고_같은_상대는_한_번이다(related):
    related.execute("insert into public.coverage (ticker, name) values ('HPQ', 'HP'), ('IBM', 'IBM'), ('ORCL', 'Oracle'),"
                    " ('CSCO', 'Cisco')")
    for rank, other in enumerate(("MSFT", "DELL", "HPQ", "IBM", "ORCL"), 1):
        related.execute(RELATION_SQL, ("AAPL", other, "peer", "sic", rank, None, None))

    with pytest.raises(errors.CheckViolation):
        related.execute(RELATION_SQL, ("AAPL", "CSCO", "peer", "sic", 6, None, None))
    with pytest.raises(errors.UniqueViolation):
        related.execute(RELATION_SQL, ("AAPL", "CSCO", "peer", "sic", 5, None, None))
    related.execute("delete from public.stock_relation where rank = 5")
    with pytest.raises(errors.UniqueViolation):  # 같은 상대는 빈 순위로도 다시 못 넣는다
        related.execute(RELATION_SQL, ("AAPL", "MSFT", "competitor", "own_10k", 5, OWN[5], OWN[6]))


@pytest.mark.parametrize(
    "row, error",
    [
        ((*OWN[:2], "partner", *OWN[3:]), errors.CheckViolation),
        ((*OWN[:3], "news", *OWN[4:]), errors.CheckViolation),
        ((*OWN[:4], 0, *OWN[5:]), errors.CheckViolation),
        ((*PEER[:3], "own_10k", *PEER[4:]), errors.CheckViolation),  # 같은 업종은 공시 근거가 아니다
        ((*OWN[:2], "peer", *OWN[3:]), errors.CheckViolation),  # 공시 근거 관계가 peer
        ((*PEER[:5], OWN[5], OWN[6]), errors.CheckViolation),  # 같은 업종에 접수번호
        ((*OWN[:6], None), errors.CheckViolation),  # 접수번호 있는데 근거 문장 없음
        ((*OWN[:5], None, OWN[6]), errors.CheckViolation),  # own_10k인데 접수번호 없음
        ((*OWN[:6], ""), errors.CheckViolation),
        (("AAPL", "AAPL", *OWN[2:]), errors.CheckViolation),  # 자기 자신
        (("AAPL", "ZZZZ", *OWN[2:]), errors.ForeignKeyViolation),  # 커버 범위 밖 상대
        (("ZZZZ", "AAPL", *OWN[2:]), errors.ForeignKeyViolation),
        ((*OWN[:5], "0000320193-25-000999", OWN[6]), errors.ForeignKeyViolation),  # 저장 안 된 10-K
    ],
    ids=["관계_값_밖", "근거_종류_값_밖", "순위_0", "peer인데_own_10k", "own_10k인데_peer", "sic에_접수번호", "근거_문장_없음",
         "접수번호_없음", "빈_근거_문장", "자기_자신", "없는_상대_티커", "없는_종목", "없는_접수번호"],
)
def test_연관_종목의_관계·근거가_어긋나면_DB가_거부한다(related, row, error):
    with pytest.raises(error):
        related.execute(RELATION_SQL, row)


@pytest.mark.parametrize("mentions, error", [('{"name": "Microsoft"}', errors.CheckViolation), ('"[]"', errors.CheckViolation),
                                             (None, errors.NotNullViolation)], ids=["객체", "문자열", "없음"])
def test_10_K_언급은_배열만_받고_저장된_10_K에만_붙는다(related, mentions, error):
    with pytest.raises(error):
        related.execute(MENTIONS_SQL, (ANNUAL_ROW[0], mentions))
    with pytest.raises(errors.ForeignKeyViolation):
        related.execute(MENTIONS_SQL, ("0000320193-25-000999", "[]"))


def test_연관_종목_관계·근거_종류는_코드와_DB가_같다(related):
    for relation in Relation:
        basis, accession, evidence = ("sic", None, None) if relation is Relation.PEER else ("own_10k", OWN[5], OWN[6])
        related.execute(RELATION_SQL, ("MSFT", "AAPL", relation.value, basis, 1, accession, evidence))
        related.execute("delete from public.stock_relation")
    for basis in RelationBasis:
        relation = "peer" if basis is RelationBasis.SIC else "customer"
        accession, evidence = (None, None) if basis is RelationBasis.SIC else (OWN[5], OWN[6])
        related.execute(RELATION_SQL, ("MSFT", "AAPL", relation, basis.value, 1, accession, evidence))
        related.execute("delete from public.stock_relation")



# 알아두기(#66): 종목마다 풀 하나(지우고 다시 씀) + 유저 진도를 세는 DB 함수(진도는 저장하지 않는다)
QUIET_SQL = "insert into public.quiet_fact (ticker, seq, text, source_accession) values (%s, %s, %s, %s)"
QUIET_ROW = ("AAPL", 1, "Apple makes phones and computers", ANNUAL_ROW[0])


@pytest.fixture
def quiet(admin):
    """AAPL·MSFT·NVDA·KO 커버 범위 + 10-K 한 건 + 풀: AAPL 15개, MSFT 3개, KO 15개. NVDA는 풀 없음(ETF처럼)."""
    admin.execute("insert into public.coverage (ticker, name) values ('AAPL', 'Apple'), ('MSFT', 'Microsoft'), ('NVDA', 'NVIDIA'),"
                  " ('KO', 'Coca-Cola')")
    admin.execute(ANNUAL_SQL, ANNUAL_ROW)
    for ticker, size in (("AAPL", 15), ("MSFT", 3), ("KO", 15)):
        for seq in range(1, size + 1):
            admin.execute(QUIET_SQL, (ticker, seq, f"{ticker} fact {seq}", ANNUAL_ROW[0]))
    return admin


def test_알아두기_풀은_서버가_지우고_다시_쓸_수만_있고_진도_함수는_서버만_부른다(quiet):
    as_service_role(quiet, "delete from public.quiet_fact where ticker = 'MSFT'")
    as_service_role(quiet, QUIET_SQL, ("MSFT", 1, "Microsoft makes software", ANNUAL_ROW[0]))

    assert service_role_privileges(quiet, "quiet_fact") == ["SELECT", "INSERT", "DELETE"]  # update 없음
    with pytest.raises(errors.InsufficientPrivilege):
        as_service_role(quiet, "update public.quiet_fact set text = 'x'")
    assert quiet.execute("select has_function_privilege('service_role', 'public.my_quiet_facts(uuid, date)', 'EXECUTE')"
                         ).fetchone()[0] is True


@pytest.mark.parametrize(
    "row, error",
    [
        (("AAPL", 16, *QUIET_ROW[2:]), errors.CheckViolation),
        (("NVDA", 0, *QUIET_ROW[2:]), errors.CheckViolation),
        (QUIET_ROW, errors.UniqueViolation),  # AAPL 1번은 이미 있다
        (("NVDA", 1, "", ANNUAL_ROW[0]), errors.CheckViolation),
        (("NVDA", 1, None, ANNUAL_ROW[0]), errors.NotNullViolation),
        (("ZZZZ", 1, *QUIET_ROW[2:]), errors.ForeignKeyViolation),
        (("NVDA", 1, QUIET_ROW[2], "0000320193-25-000999"), errors.ForeignKeyViolation),
    ],
    ids=["seq_16", "seq_0", "같은_종목·번호", "빈_문장", "문장_없음", "없는_종목", "저장_안_된_10_K"],
)
def test_알아두기는_종목마다_1_15번_하나씩이고_저장된_10_K에만_붙는다(quiet, row, error):
    with pytest.raises(error):
        quiet.execute(QUIET_SQL, row)


D0 = date(2026, 11, 2)


def day(n):
    return D0 + timedelta(days=n)


def card_on(conn, ticker, n, news="checked_none", suspended=False):
    """ticker의 day(n) 카드. news = 첫 번째 줄 상태, None = 축소판(첫 번째 줄 없음)."""
    if news is None:
        conn.execute("insert into public.stock_card (ticker, trading_day, status, change_pct, change_status, publish_suspended)"
                     " values (%s, %s, 'fallback', null, 'unsupported', %s)", (ticker, day(n), suspended))
        return
    conn.execute(
        "insert into public.stock_card (ticker, trading_day, status, change_pct, change_status, news_line_text, news_line_status,"
        " news_line_checked_at, news_line_source_scope, publish_suspended)"
        " values (%s, %s, 'normal', null, 'unsupported', 'x', %s, now(), 'SEC filings', %s)", (ticker, day(n), news, suspended))


def history_row(conn, uid, ticker, change, n):
    """내 종목 이력 한 줄을 넣은 날 day(n)로(유저 현지 날짜). 트리거가 쓴 오늘 줄보다 id가 크다."""
    as_service_role(conn, "insert into public.my_stock_history (user_id, change, ticker, local_date) values (%s, %s, %s, %s)",
                    (uid, change, ticker, day(n)))


def my_stock(conn, uid, ticker, added=None):
    """내 종목에 넣고(트리거가 오늘 이력을 쓴다), added가 있으면 넣은 날을 day(added)로."""
    as_service_role(conn, "insert into public.my_stock (user_id, ticker) values (%s, %s)", (uid, ticker))
    if added is not None:
        history_row(conn, uid, ticker, "add", added)


def quiet_facts(conn, uid, n):
    """service_role로 my_quiet_facts(uid, day(n)) → {티커: 사실 문장}."""
    with conn.transaction(force_rollback=True):
        conn.execute("set local role service_role")
        return dict(conn.execute("select ticker, fact from public.my_quiet_facts(%s, %s)", (uid, day(n))).fetchall())


def test_알아두기_번호는_마지막으로_넣은_날부터_그날까지_조용한_날_수다(quiet, make_user):
    uid = make_user("plus")
    my_stock(quiet, uid, "AAPL", added=1)
    statuses = {0: "checked_none", 1: "checked_none", 2: "checked_found", 3: "checked_none", 4: "delayed", 5: "unsupported", 6: None,
                8: "checked_none"}
    for n, news in statuses.items():
        card_on(quiet, "AAPL", n, news)
    card_on(quiet, "AAPL", 7, suspended=True)  # 발행 중단 카드는 아무에게도 안 나갔다

    seen = {n: quiet_facts(quiet, uid, n).get("AAPL") for n in range(10)}

    # 넣기 전 조용한 날(0)·확인함 있음·지연·미지원·축소판·발행 중단은 세지 않는다. 오늘 카드가 조용한 날인지는 웹이 본다(2일에도 1번)
    assert seen == {0: None, 1: "AAPL fact 1", 2: "AAPL fact 1", 3: "AAPL fact 2", 4: "AAPL fact 2", 5: "AAPL fact 2",
                    6: "AAPL fact 2", 7: "AAPL fact 2", 8: "AAPL fact 3", 9: "AAPL fact 3"}


def test_지웠다가_다시_넣으면_다시_넣은_날부터_1번이고_이미_내_종목을_또_넣으면_그대로다(quiet, make_user):
    uid = make_user("plus")
    my_stock(quiet, uid, "AAPL", added=1)
    for n in range(1, 6):
        card_on(quiet, "AAPL", n)
    assert quiet_facts(quiet, uid, 5) == {"AAPL": "AAPL fact 5"}

    history_row(quiet, uid, "AAPL", "remove", 3)
    history_row(quiet, uid, "AAPL", "add", 3)
    assert quiet_facts(quiet, uid, 5) == {"AAPL": "AAPL fact 3"}

    as_service_role(quiet, "insert into public.my_stock (user_id, ticker) values (%s, 'AAPL')", (uid,))  # 이력이 생기지 않는다(#38)
    assert quiet_facts(quiet, uid, 5) == {"AAPL": "AAPL fact 3"}


def test_조용한_날이_풀보다_많으면_알아두기가_끝나고_1번으로_돌아가지_않는다(quiet, make_user):
    uid = make_user("plus")
    my_stock(quiet, uid, "AAPL", added=0)
    my_stock(quiet, uid, "MSFT", added=0)
    for n in range(20):
        card_on(quiet, "AAPL", n)
        card_on(quiet, "MSFT", n)

    assert quiet_facts(quiet, uid, 2) == {"AAPL": "AAPL fact 3", "MSFT": "MSFT fact 3"}
    assert quiet_facts(quiet, uid, 3) == {"AAPL": "AAPL fact 4"}  # MSFT 풀은 3개
    assert quiet_facts(quiet, uid, 14) == {"AAPL": "AAPL fact 15"}
    assert quiet_facts(quiet, uid, 15) == {} == quiet_facts(quiet, uid, 19)  # 16번째 조용한 날부터(16행에서 세기를 멈춘다)


def test_알아두기_진도는_그_유저의_잠기지_않은_내_종목만_그_유저_이력으로_센다(quiet, make_user):
    uid, other = make_user("plus"), make_user("plus")
    for ticker in ("AAPL", "MSFT", "NVDA", "KO"):  # 넣은 순서대로. 무료가 되면 KO가 잠긴다
        my_stock(quiet, uid, ticker, added=0)
        card_on(quiet, ticker, 0)
        card_on(quiet, ticker, 1)
    my_stock(quiet, other, "AAPL", added=1)
    my_stock(quiet, other, "MSFT", added=0)
    as_service_role(quiet, "update public.user_profile set plan = 'free' where user_id = %s", (uid,))

    # NVDA는 풀이 없다(ETF처럼). KO는 잠겼다. 다른 유저의 늦은 이력은 섞이지 않는다
    assert quiet_facts(quiet, uid, 1) == {"AAPL": "AAPL fact 2", "MSFT": "MSFT fact 2"}
    assert quiet_facts(quiet, other, 1) == {"AAPL": "AAPL fact 1", "MSFT": "MSFT fact 2"}


# 잠긴 자리·대기 등록(#69): 프로필의 대기 등록 시각 + 잠긴 자리 탭 일별 합계(유저 값 없음)
def service_role_columns(conn, table, privilege):
    return [r[0] for r in conn.execute(
        "select column_name from information_schema.columns where table_schema = 'public' and table_name = %s"
        " and has_column_privilege('service_role', 'public.' || table_name, column_name, %s) order by column_name",
        (table, privilege))]


def test_대기_등록_시각은_비어_있는_채로_프로필이_생기고_서버는_그_열을_고칠_수만_있다(admin, make_user):
    uid = make_user()

    assert admin.execute("select data_type, is_nullable from information_schema.columns where table_schema = 'public'"
                         " and table_name = 'user_profile' and column_name = 'waitlisted_at'").fetchone() == (
        "timestamp with time zone", "YES")
    assert admin.execute("select waitlisted_at from public.user_profile where user_id = %s", (uid,)).fetchone() == (None,)
    assert service_role_columns(admin, "user_profile", "UPDATE") == ["morning_push_time", "plan", "timezone", "waitlisted_at"]
    assert service_role_columns(admin, "user_profile", "INSERT") == ["morning_push_time", "plan", "timezone", "user_id"]
    as_service_role(admin, "update public.user_profile set waitlisted_at = now() where user_id = %s and waitlisted_at is null",
                    (uid,))


def test_잠긴_자리_탭_집계는_날짜·자리·합계_열뿐이고_유저를_알_수_있는_열이_없다(admin):
    columns = [r[0] for r in admin.execute(
        "select column_name from information_schema.columns"
        " where table_schema = 'public' and table_name = 'locked_slot_tap' order by ordinal_position")]
    assert columns == ["day", "slot", "taps"]  # 유저 id·IP·시각 열은 영원히 없다(개인정보처리방침 "not linked to you")


TAP_SQL = "insert into public.locked_slot_tap (day, slot, taps) values ('2026-11-05', %s, %s)"


@pytest.mark.parametrize(
    "slot, taps, error",
    [
        ("earnings", 1, errors.CheckViolation),
        ("Big_holders", 1, errors.CheckViolation),
        ("", 1, errors.CheckViolation),
        (None, 1, errors.NotNullViolation),
        ("related_lock", 0, errors.CheckViolation),
        ("big_holders", 1, errors.UniqueViolation),  # 그날 big_holders 행은 이미 있다
    ],
    ids=["모르는_자리", "대소문자_다름", "빈_자리", "자리_없음", "합계_0", "같은_날·자리"],
)
def test_잠긴_자리_탭은_세_자리_종류만_하루_한_행씩_1_이상으로_받는다(admin, slot, taps, error):
    for ok in ("earnings_summary", "big_holders", "related_lock"):  # 웹 TAP_SLOTS와 같다
        admin.execute(TAP_SQL, (ok, 1))
    with pytest.raises(error):
        admin.execute(TAP_SQL, (slot, taps))


def test_잠긴_자리_탭_집계는_서버가_넣고_올릴_수만_있고_지울_수_없다(admin):
    as_service_role(admin, TAP_SQL, ("big_holders", 1))
    as_service_role(admin, "update public.locked_slot_tap set taps = taps + 1")

    assert service_role_privileges(admin, "locked_slot_tap") == ["SELECT", "INSERT", "UPDATE"]  # 증가 함수가 서버 권한으로 쓴다
    with pytest.raises(errors.InsufficientPrivilege):
        as_service_role(admin, "delete from public.locked_slot_tap")


def tap(conn, slot, timezone="UTC"):
    """service_role로 count_locked_slot_tap(slot)을 부른다. timezone = 연결 세션 시간대."""
    with conn.transaction():
        conn.execute("set local role service_role")
        conn.execute(f"set local timezone = '{timezone}'")
        conn.execute("select public.count_locked_slot_tap(%s)", (slot,))


def test_탭을_세면_오늘_동부_날짜의_그_자리_합계가_1씩_오르고_다른_자리는_따로_센다(admin):
    tap(admin, "earnings_summary", "Pacific/Kiritimati")  # UTC+14
    tap(admin, "earnings_summary", "Etc/GMT+12")  # UTC-12: 세션 날짜를 쓰면 위와 늘 다른 날이 된다
    tap(admin, "related_lock")

    today = datetime.now(ET).date()
    assert admin.execute("select day, slot, taps from public.locked_slot_tap order by slot").fetchall() == [
        (today, "earnings_summary", 2), (today, "related_lock", 1)]


def test_탭_세기_함수는_서버만_부를_수_있고_모르는_자리는_세지_않는다(admin):
    # public·anon·authenticated 실행 불가와 security definer 아님은 위 함수 전체 검사가 본다(anon은 public 권한을 물려받는다)
    assert admin.execute("select has_function_privilege('service_role', 'public.count_locked_slot_tap(text)', 'EXECUTE')"
                         ).fetchone() == (True,)
    for slot in ("earnings", "", None):
        with pytest.raises((errors.CheckViolation, errors.NotNullViolation)):
            tap(admin, slot)
    assert admin.execute("select count(*) from public.locked_slot_tap").fetchone() == (0,)
