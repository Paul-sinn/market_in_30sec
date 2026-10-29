"""입구 2: 마이그레이션이 적용된 로컬 DB가 직접 막는 규칙. 관리자 연결로 카탈로그 조회·역할 전환."""

import dataclasses
import json

import pytest
from psycopg import errors

from m30.models import IMPORTANCE_MAX, Coverage, HoldStage, HoldState, NewsKind
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
    "updated_at", "leverage_tag", "news_line_accession", "previous_trading_day", "publish_suspended",
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
    assert len(columns) == 22
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
              "fund_holdings", "morning_notice"}
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
            "lock_my_stocks_on_plan_change", "my_stock_rules", "log_my_stock_change", "dispatch_morning_workflow"} <= set(functions)  # 검사 대상이 비어서 통과하지 않게
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
                  " news_line_accession = null where ticker = 'AAPL'")
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
