"""입구 2: 내 종목 규칙(#8). 쓰기는 웹 서버·대시보드와 같은 SQL을 service_role로 한다(트랜잭션 하나 = now() 하나).
거절은 정해진 이름의 CheckViolation이다(스펙 #8 4-1 오류 계약)."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from time import monotonic, sleep
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg import errors

from m30.db.store import connect
from test_schema import as_service_role

LA = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def covered(admin):
    for ticker in ("AAPL", "MSFT", "NVDA", "KO", "PFE", "XOM"):
        admin.execute("insert into public.coverage (ticker, name) values (%s, %s)", (ticker, ticker))
    return admin


def add(conn, uid, ticker):
    as_service_role(conn, "insert into public.my_stock (user_id, ticker) values (%s, %s)", (uid, ticker))


def remove(conn, uid, ticker):
    as_service_role(conn, "delete from public.my_stock where user_id = %s and ticker = %s", (uid, ticker))


def history(conn, uid):
    return conn.execute(
        "select change::text, ticker, local_date, occurred_at from public.my_stock_history where user_id = %s order by id", (uid,)
    ).fetchall()


def test_내_종목을_넣고_빼면_이력이_한_줄씩_현지_날짜와_남는다(covered, make_user):
    uid = make_user(timezone="America/Los_Angeles")

    add(covered, uid, "AAPL")
    remove(covered, uid, "AAPL")

    rows = history(covered, uid)
    assert [(change, ticker) for change, ticker, _, _ in rows] == [("add", "AAPL"), ("remove", "AAPL")]
    for _, _, local_date, occurred_at in rows:
        assert occurred_at.utcoffset() is not None
        assert local_date == occurred_at.astimezone(LA).date()  # 프로필 타임존의 날짜
    assert covered.execute("select count(*) from public.my_stock").fetchone()[0] == 0


@pytest.mark.parametrize("sql", ["update public.my_stock_history set ticker = 'MSFT'", "delete from public.my_stock_history"],
                         ids=["수정", "삭제"])
def test_내_종목_이력은_service_role도_고치거나_지울_수_없다(covered, make_user, sql):
    uid = make_user()
    add(covered, uid, "AAPL")

    with pytest.raises(errors.InsufficientPrivilege):
        as_service_role(covered, sql)
    allowed = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
               if covered.execute("select has_table_privilege('service_role', 'public.my_stock_history', %s)", (p,)).fetchone()[0]]
    assert allowed == ["SELECT", "INSERT"]
    column_updates = covered.execute(
        "select column_name from information_schema.column_privileges where table_schema = 'public'"
        " and table_name = 'my_stock_history' and grantee = 'service_role' and privilege_type = 'UPDATE'").fetchall()
    assert column_updates == []
    assert [(c, t) for c, t, _, _ in history(covered, uid)] == [("add", "AAPL")]


def test_이미_있는_종목_추가가_무시되면_이력도_없다(covered, make_user):
    uid = make_user()
    add(covered, uid, "AAPL")

    as_service_role(covered, "insert into public.my_stock (user_id, ticker) values (%s, 'AAPL') on conflict do nothing", (uid,))

    assert [(c, t) for c, t, _, _ in history(covered, uid)] == [("add", "AAPL")]


def user_rows(conn):
    return {t: conn.execute(f"select count(*) from public.{t}").fetchone()[0] for t in ("user_profile", "my_stock", "my_stock_history")}


@pytest.mark.parametrize("plan", ["free", "plus"])
def test_계정을_지우면_프로필·내_종목·이력이_같이_지워진다(settings, covered, make_user, plan):
    uid = make_user(plan)
    for ticker in ("AAPL", "MSFT", "NVDA"):
        add(covered, uid, ticker)
    remove(covered, uid, "NVDA")
    assert user_rows(covered) == {"user_profile": 1, "my_stock": 2, "my_stock_history": 4}

    # 앱 안 계정 삭제: Supabase Auth(auth.admin.deleteUser)는 이 역할로 지운다. postgres는 이 역할로 set role 할 수 없다(로컬은 비밀번호가 같다)
    with psycopg.connect(settings.database_url, user="supabase_auth_admin", autocommit=True) as auth:
        assert auth.execute("select count(*) from public.user_profile").fetchone()[0] == 0  # 삭제용 열 권한뿐, RLS가 프로필을 가린다
        auth.execute("delete from auth.users where id = %s", (uid,))

    assert user_rows(covered) == {"user_profile": 0, "my_stock": 0, "my_stock_history": 0}  # 추가 전용이어도 cascade는 막히지 않는다


def refused(name, write, *args):
    """write가 정해진 이름(오류 계약)으로 거절된다. 메시지는 이름뿐(유저 값 없음): 공개 로그에 찍혀도 된다."""
    with pytest.raises(errors.CheckViolation) as e:
        write(*args)
    assert (e.value.diag.constraint_name, e.value.diag.message_primary) == (name, name)


def tickers(conn, uid):
    return [r[0] for r in conn.execute("select ticker from public.my_stock where user_id = %s order by ticker", (uid,))]


def removals(conn, uid):
    return [t for c, t, _, _ in history(conn, uid) if c == "remove"]


def test_무료는_하루_세_번까지_지울_수_있고_네_번째는_거절된다(covered, make_user):
    uid = make_user("free")
    for ticker in ("AAPL", "MSFT", "NVDA"):  # 온보딩 첫 3개: 교체 0회
        add(covered, uid, ticker)

    for out, new in (("AAPL", "KO"), ("MSFT", "PFE"), ("NVDA", "XOM")):  # 교체 3회
        remove(covered, uid, out)
        add(covered, uid, new)
    refused("free_swap_limit", remove, covered, uid, "KO")

    assert tickers(covered, uid) == ["KO", "PFE", "XOM"]  # 거절된 행은 남아 있다
    assert removals(covered, uid) == ["AAPL", "MSFT", "NVDA"]


def test_빈_슬롯에_넣기는_교체가_아니다(covered, make_user):
    uid = make_user("free")
    add(covered, uid, "AAPL")
    add(covered, uid, "MSFT")
    add(covered, uid, "NVDA")  # 빈 슬롯

    for ticker in ("AAPL", "MSFT", "NVDA"):
        remove(covered, uid, ticker)

    assert tickers(covered, uid) == []
    assert removals(covered, uid) == ["AAPL", "MSFT", "NVDA"]


def test_지우고_다시_넣어도_교체_횟수는_돌아오지_않는다(covered, make_user):
    uid = make_user("free")
    for ticker in ("AAPL", "MSFT", "NVDA"):
        add(covered, uid, ticker)

    for out, new in (("AAPL", "KO"), ("MSFT", "PFE"), ("NVDA", "AAPL")):  # 지운 종목을 다시 넣어도 횟수는 그대로
        remove(covered, uid, out)
        add(covered, uid, new)
    refused("free_swap_limit", remove, covered, uid, "AAPL")

    assert tickers(covered, uid) == ["AAPL", "KO", "PFE"]


def test_한_문장으로_여러_개를_지워도_하루_세_번을_넘지_않는다(covered, make_user):
    uid = make_user("free")
    for ticker in ("AAPL", "MSFT", "NVDA"):
        add(covered, uid, ticker)
    remove(covered, uid, "AAPL")
    add(covered, uid, "KO")  # 교체 1회

    refused("free_swap_limit", as_service_role, covered, "delete from public.my_stock where user_id = %s", (uid,))  # 1 + 3 = 4

    assert tickers(covered, uid) == ["KO", "MSFT", "NVDA"]
    assert removals(covered, uid) == ["AAPL"]


def test_무료는_잠기지_않은_내_종목이_3개면_더_넣을_수_없다(covered, make_user):
    uid = make_user("free")
    for ticker in ("AAPL", "MSFT", "NVDA"):
        add(covered, uid, ticker)

    refused("free_my_stock_limit", add, covered, uid, "KO")

    assert tickers(covered, uid) == ["AAPL", "MSFT", "NVDA"]


ADD_FORMS = {  # 웹(supabase-js upsert ignoreDuplicates)은 on conflict do nothing을 보낸다
    "insert": "insert into public.my_stock (user_id, ticker) values (%s, %s)",
    "on_conflict_do_nothing": "insert into public.my_stock (user_id, ticker) values (%s, %s) on conflict do nothing",
}


@pytest.mark.parametrize("sql", ADD_FORMS.values(), ids=ADD_FORMS.keys())
def test_무료_3개가_찬_상태에서_이미_내_종목인_종목을_다시_넣으면_아무_일도_없다(covered, make_user, sql):
    uid = make_user("free")
    for ticker in ("AAPL", "MSFT", "NVDA"):
        add(covered, uid, ticker)
    before = history(covered, uid)

    as_service_role(covered, sql, (uid, "MSFT"))  # 오류 없음

    assert tickers(covered, uid) == ["AAPL", "MSFT", "NVDA"]
    assert history(covered, uid) == before
    refused("free_my_stock_limit", add, covered, uid, "KO")  # 새 종목은 여전히 막힌다


@pytest.mark.parametrize("sql", ADD_FORMS.values(), ids=ADD_FORMS.keys())
def test_Plus도_이미_내_종목인_종목을_다시_넣으면_아무_일도_없다(covered, make_user, sql):
    uid = make_user("plus")
    for ticker in ("AAPL", "MSFT", "NVDA", "KO"):
        add(covered, uid, ticker)
    before = history(covered, uid)

    as_service_role(covered, sql, (uid, "KO"))  # 오류 없음

    assert tickers(covered, uid) == ["AAPL", "KO", "MSFT", "NVDA"]
    assert history(covered, uid) == before


def test_Plus는_교체·개수_제한이_없다(covered, make_user):
    uid = make_user("plus")
    for ticker in ("AAPL", "MSFT", "NVDA", "KO", "PFE"):
        add(covered, uid, ticker)

    for ticker in ("AAPL", "MSFT", "NVDA", "KO"):
        remove(covered, uid, ticker)

    assert tickers(covered, uid) == ["PFE"]
    assert removals(covered, uid) == ["AAPL", "MSFT", "NVDA", "KO"]


def set_plan(conn, uid, plan):
    as_service_role(conn, "update public.user_profile set plan = %s where user_id = %s", (plan, uid))


def locks(conn, uid):
    return dict(conn.execute("select ticker, locked from public.my_stock where user_id = %s order by ticker", (uid,)).fetchall())


def test_다운그레이드하면_먼저_등록한_3개만_남고_나머지는_잠긴다(covered, make_user):
    uid = make_user("plus")
    for ticker in ("NVDA", "AAPL", "PFE", "MSFT", "KO"):  # 등록 순서 ≠ 티커 순서. 한 번에 하나씩 = 등록 시각이 다르다
        add(covered, uid, ticker)

    set_plan(covered, uid, "free")

    assert locks(covered, uid) == {"AAPL": False, "KO": True, "MSFT": True, "NVDA": False, "PFE": False}  # 행은 지우지 않는다
    assert removals(covered, uid) == []  # 잠금은 이력이 아니다
    set_plan(covered, uid, "plus")  # 재구독하면 즉시 복구
    assert locks(covered, uid) == dict.fromkeys(["AAPL", "KO", "MSFT", "NVDA", "PFE"], False)


@pytest.mark.parametrize("locked", [True, False], ids=["잠금", "해제"])
def test_잠금은_플랜_변경으로만_바뀐다(covered, make_user, locked):
    uid = make_user("plus")
    for ticker in ("AAPL", "MSFT", "NVDA", "KO"):
        add(covered, uid, ticker)
    set_plan(covered, uid, "free")  # KO 잠김
    before = locks(covered, uid)

    # 잠그고 넣거나 풀면 삭제 없이 교체된다(고르기 화면 티켓 전까지 막음)
    refused("lock_by_plan_only", as_service_role, covered,
            "update public.my_stock set locked = %s where user_id = %s", (locked, uid))

    assert locks(covered, uid) == before


def test_무료_3개에_잠긴_종목은_세지_않는다(covered, make_user):
    uid = make_user("plus")
    for ticker in ("AAPL", "MSFT", "NVDA", "KO"):
        add(covered, uid, ticker)
    set_plan(covered, uid, "free")  # KO 잠김
    remove(covered, uid, "AAPL")  # 잠기지 않은 것 2개

    add(covered, uid, "PFE")
    refused("free_my_stock_limit", add, covered, uid, "XOM")

    assert locks(covered, uid) == {"KO": True, "MSFT": False, "NVDA": False, "PFE": False}


DELETE_SQL = "delete from public.my_stock where user_id = %s and ticker = %s"


def test_동시에_지워도_하루_세_번을_넘지_않는다(settings, covered, make_user):
    uid = make_user("free")
    for ticker in ("AAPL", "MSFT", "NVDA"):
        add(covered, uid, ticker)
    for out, new in (("AAPL", "KO"), ("MSFT", "PFE")):  # 교체 2회
        remove(covered, uid, out)
        add(covered, uid, new)

    with connect(settings) as a, connect(settings) as b:  # 둘 다 service_role
        with a.transaction():
            a.execute(DELETE_SQL, (uid, "NVDA"))  # 3번째, 커밋 전
            with pytest.raises(errors.LockNotAvailable), b.transaction():  # 같은 유저의 쓰기는 앞 트랜잭션을 기다린다
                b.execute("set local lock_timeout = '200ms'")
                b.execute(DELETE_SQL, (uid, "KO"))
        refused("free_swap_limit", b.execute, DELETE_SQL, (uid, "KO"))  # A 커밋 뒤에는 4번째

    assert tickers(covered, uid) == ["KO", "PFE"]
    assert removals(covered, uid) == ["AAPL", "MSFT", "NVDA"]


def test_같은_종목을_동시에_두_번_넣어도_한_번만_들어가고_오류가_없다(settings, covered, make_user):
    uid = make_user("free")
    add(covered, uid, "AAPL")
    add(covered, uid, "MSFT")
    sql = ADD_FORMS["on_conflict_do_nothing"]

    with connect(settings) as a, connect(settings) as b, ThreadPoolExecutor(1) as pool:  # 둘 다 service_role
        with a.transaction():
            a.execute(sql, (uid, "NVDA"))  # 첫 번째 누르기(3번째 종목), 커밋 전
            second = pool.submit(b.execute, sql, (uid, "NVDA"))  # 두 번째 누르기
            deadline = monotonic() + 5
            while covered.execute("select wait_event_type from pg_stat_activity where pid = %s",
                                  (b.info.backend_pid,)).fetchone()[0] != "Lock":  # 앞 트랜잭션을 기다리는 중
                assert monotonic() < deadline and not second.done()
                sleep(0.01)
        second.result(timeout=5)  # 앞 커밋 뒤에 깨어나도 free_my_stock_limit가 아니다

    assert tickers(covered, uid) == ["AAPL", "MSFT", "NVDA"]
    assert [(c, t) for c, t, _, _ in history(covered, uid)] == [("add", "AAPL"), ("add", "MSFT"), ("add", "NVDA")]


def local_date(conn, uid, instant):
    with conn.transaction(force_rollback=True):
        conn.execute("set local role service_role")  # 웹 서버도 service_role로 부른다
        return conn.execute("select public.user_local_date(%s, %s)", (uid, instant)).fetchone()[0]


def test_하루는_프로필_타임존_자정에_바뀐다(covered, make_user):
    uid = make_user(timezone="America/Los_Angeles")  # 10-27은 PDT(UTC−7)

    assert local_date(covered, uid, datetime(2026, 10, 27, 6, 59, 59, tzinfo=UTC)) == date(2026, 10, 26)
    assert local_date(covered, uid, datetime(2026, 10, 27, 7, 0, 0, tzinfo=UTC)) == date(2026, 10, 27)


def test_어제_지운_횟수는_오늘_세지_않는다(covered, make_user):
    uid = make_user("free", timezone="America/Los_Angeles")
    add(covered, uid, "AAPL")
    yesterday = covered.execute("select now()").fetchone()[0].astimezone(LA).date() - timedelta(days=1)
    for ticker in ("MSFT", "NVDA", "KO"):  # 어제 3회
        as_service_role(covered, "insert into public.my_stock_history (user_id, change, ticker, local_date)"
                                 " values (%s, 'remove', %s, %s)", (uid, ticker, yesterday))

    remove(covered, uid, "AAPL")

    assert tickers(covered, uid) == []


@pytest.mark.parametrize("timezone", ["Mars/Olympus", "", "+09:00"], ids=["없는_이름", "빈_값", "UTC_오프셋"])
def test_타임존_이름이_아니면_프로필에_넣을_수_없다(covered, make_user, timezone):
    refused("timezone_name", make_user, "free", timezone)  # 기기 값은 신뢰 경계
    uid = make_user(timezone="Asia/Seoul")
    refused("timezone_name", as_service_role, covered, "update public.user_profile set timezone = %s where user_id = %s",
            (timezone, uid))


def change_timezone(conn, uid, timezone):
    """service_role로 바꾸고 그 트랜잭션의 now()를 돌려준다."""
    with conn.transaction():
        conn.execute("set local role service_role")
        conn.execute("update public.user_profile set timezone = %s where user_id = %s", (timezone, uid))
        return conn.execute("select now()").fetchone()[0]


def day_pair(conn, uid):
    return conn.execute("select timezone, day_timezone, day_timezone_until from public.user_profile where user_id = %s",
                        (uid,)).fetchone()


def next_midnight(instant, zone):
    return datetime.combine(instant.astimezone(zone).date() + timedelta(days=1), time(0), tzinfo=zone)


def test_타임존을_바꿔도_하루_기준은_다음_날부터_바뀐다(covered, make_user):
    uid = make_user("free", timezone="America/Los_Angeles")
    for ticker in ("AAPL", "MSFT", "NVDA"):
        add(covered, uid, ticker)
    for out, new in (("AAPL", "KO"), ("MSFT", "PFE"), ("NVDA", "XOM")):  # LA 기준 오늘 교체 3회
        remove(covered, uid, out)
        add(covered, uid, new)

    changed_at = change_timezone(covered, uid, "Asia/Tokyo")  # 기기 타임존은 바로 저장된다

    refused("free_swap_limit", remove, covered, uid, "KO")  # 도쿄가 이미 내일이어도 오늘은 LA의 오늘
    timezone, day_timezone, until = day_pair(covered, uid)
    assert (timezone, day_timezone) == ("Asia/Tokyo", "America/Los_Angeles")
    assert until == next_midnight(changed_at, LA)
    assert local_date(covered, uid, until - timedelta(microseconds=1)) == (until - timedelta(microseconds=1)).astimezone(LA).date()
    assert local_date(covered, uid, until) == until.astimezone(ZoneInfo("Asia/Tokyo")).date()

    change_timezone(covered, uid, "Europe/London")  # 같은 날 또 바꿔도 하루 기준은 그대로
    assert day_pair(covered, uid) == ("Europe/London", "America/Los_Angeles", until)


def test_지난_변경이_적용된_뒤_바꾸면_그때_타임존이_하루_기준이_된다(covered, make_user):
    uid = make_user(timezone="America/Los_Angeles")
    change_timezone(covered, uid, "Asia/Tokyo")
    covered.execute("update public.user_profile set day_timezone_until = now() - interval '1 hour' where user_id = %s",
                    (uid,))  # 다음 날이 됐다

    changed_at = change_timezone(covered, uid, "Europe/London")

    assert day_pair(covered, uid) == ("Europe/London", "Asia/Tokyo", next_midnight(changed_at, ZoneInfo("Asia/Tokyo")))


@pytest.mark.parametrize(
    "sql, values, error",
    [
        ("insert into public.default_ticker (quarter, ticker) values (%s, %s)", ("2026-11-01", "AAPL"), errors.CheckViolation),
        ("insert into public.default_ticker (quarter, ticker) values (%s, %s)", ("2026-10-02", "AAPL"), errors.CheckViolation),
        ("insert into public.default_ticker (quarter, ticker) values (%s, %s)", ("2026-10-01", "ZZZZ"), errors.ForeignKeyViolation),
        ("insert into public.my_stock (user_id, ticker) values (%s, %s)", ("{uid}", "ZZZZ"), errors.ForeignKeyViolation),
        ("insert into public.my_stock_history (user_id, change, ticker, local_date) values (%s, 'add', %s, '2026-10-27')",
         ("{uid}", "ZZZZ"), errors.ForeignKeyViolation),
    ],
    ids=["분기_첫날_아님", "분기_첫_달_2일", "기본_종목_커버_범위_밖", "내_종목_커버_범위_밖", "이력_커버_범위_밖"],
)
def test_기본_종목은_분기_첫날·커버_범위_종목만_받는다(covered, make_user, sql, values, error):
    uid = make_user()
    as_service_role(covered, "insert into public.default_ticker (quarter, ticker) values ('2026-10-01', 'AAPL')")  # 분기 첫날

    with pytest.raises(error):
        as_service_role(covered, sql, tuple(uid if v == "{uid}" else v for v in values))


@pytest.mark.parametrize("table", ["user_profile", "my_stock", "my_stock_history"])
def test_로그인한_유저도_자기_데이터를_DB에서_직접_읽을_수_없다(covered, make_user, table):
    uid = make_user()
    add(covered, uid, "AAPL")

    with pytest.raises(errors.InsufficientPrivilege), covered.transaction(force_rollback=True):
        covered.execute("set local role authenticated")
        covered.execute("select set_config('request.jwt.claims', %s, true)",
                        (json.dumps({"sub": str(uid), "role": "authenticated"}),))
        assert covered.execute("select auth.uid()").fetchone()[0] == uid  # 본인으로 로그인한 상태다
        covered.execute(f"select * from public.{table}")  # auth.uid() 정책 경로가 없다(ADR-0003: 서버 API로만)
