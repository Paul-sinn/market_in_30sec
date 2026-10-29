"""입구 1: 아침 알림 문구(#12). 시나리오 + 유저·내 종목 → MorningPipeline.run → store.list_notices."""

import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal

import psycopg
import pytest
from psycopg import errors

from m30.adapters import Source
from m30.adapters.events import Earnings, EarningsTiming, ExDividend
from m30.adapters.fake import FailurePlan, Scenario, load_scenario
from m30.config import ET
from m30.models import CardLine, CardStatus, Coverage, LineStatus, Plan, StockCard
from m30.pipeline import morning
from m30.pipeline.notice import morning_notice
from m30.copy_rules import check_card
from test_collect_classify import AAPL, FACT, LINE, MSFT, filing, label, reply, scenario
from test_review import BUY, one_filing
from test_schema import as_service_role
from test_morning_pipeline import FRI, THANKSGIVING, THU, TWO_BARS, cli, closes, run
from test_my_stock import add, remove, set_plan

QUIET = "Today's stock cards are ready"  # 고정 문구(copy-reviewer 검수 대상)


def user_with(store, admin, make_user, scenario, tickers, plan="free"):
    """커버 범위를 먼저 넣고(내 종목 FK) 유저 한 명에게 tickers를 내 종목으로 넣는다."""
    store.upsert_coverage(scenario.coverage)
    uid = make_user(plan)
    for ticker in tickers:
        add(admin, uid, ticker)
    return uid


def test_전부_조용한_유저는_고정_문구를_받는다(store, admin, make_user):
    quiet = Scenario(coverage=[AAPL], prices={"AAPL": TWO_BARS}, events={"AAPL": []})  # 공시·일정·가격 사실 모두 확인함·없음
    uid = user_with(store, admin, make_user, quiet, ["AAPL"])

    run(store, quiet)

    assert store.list_notices(FRI) == {uid: QUIET}


def news_day(aapl=1, msft=1, **more):
    """AAPL·MSFT 공시 하나씩, 내부 중요도 aapl·msft. 첫 번째 줄 둘 다 1차 통과: Apple/Microsoft named a new CFO (SEC filing)."""
    return scenario(
        [AAPL, MSFT],
        [filing(1, body="Apple named a new CFO."), filing(2, cik=MSFT.cik, body="Microsoft named a new CFO.")],
        [reply(label(1, importance=aapl), label(2, "MSFT", importance=msft)), LINE,
         json.dumps({"sentence": "Microsoft named a new CFO"}), FACT, FACT],
        **more,
    )


def aapl_news_day(prices=None, **more):
    """AAPL만 공시(중요도 5) → Apple named a new CFO (SEC filing). MSFT는 공시 없음. 시세는 prices(기본 없음)."""
    day = scenario([AAPL, MSFT], [filing(1, body="Apple named a new CFO.")], [reply(label(1, importance=5)), LINE, FACT], **more)
    return dataclasses.replace(day, prices=prices or {})


@pytest.mark.parametrize("aapl, msft, notice", [
    (2, 4, "MSFT: Microsoft named a new CFO +1 more"),
    (5, 3, "AAPL: Apple named a new CFO +1 more"),
])
def test_내부_중요도가_가장_높은_첫_번째_줄에_티커를_붙이고_소식이_있는_다른_종목_수를_붙인다(store, admin, make_user, aapl, msft, notice):
    day = news_day(aapl, msft)
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"])

    run(store, day)

    assert store.list_notices(FRI) == {uid: notice}  # 카드 줄의 출처 꼬리표는 떼고, +N more는 다른 종목 수


@pytest.mark.parametrize("event, notice", [
    (Earnings(FRI, True, EarningsTiming.BEFORE_OPEN), "MSFT: Earnings Fri 10/16 before open (D-0) +1 more"),
    (ExDividend(FRI, Decimal("0.91")), "MSFT: Ex-dividend 10/16 · $0.91/share +1 more"),
    (Earnings(date(2026, 10, 19), True, EarningsTiming.BEFORE_OPEN), "AAPL: Apple named a new CFO"),  # D-3: 오늘 일정 아님
    (ExDividend(date(2026, 10, 17), Decimal("0.91")), "AAPL: Apple named a new CFO"),
], ids=["오늘_실적", "오늘_배당락", "D-3_실적", "내일_배당락"])
def test_오늘_일정이_있으면_중요도가_높은_첫_번째_줄보다_먼저_쓴다(store, admin, make_user, event, notice):
    day = aapl_news_day(events={"MSFT": [event]})
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"])

    run(store, day)

    assert store.list_notices(FRI) == {uid: notice}


UP_5 = closes(("10-08", 100), ("10-09", 101), ("10-12", 102), ("10-13", 103), ("10-14", 104), ("10-15", 105))  # Up 5 days in a row


@pytest.mark.parametrize("plan, notice", [
    ("plus", "MSFT: Up 5 days in a row"),
    ("free", QUIET),  # 무료 유저에게 세 번째 줄은 잠금(#9)
])
def test_소식·오늘_일정이_없으면_Plus_유저만_가격_사실을_쓴다(store, admin, make_user, plan, notice):
    day = Scenario(coverage=[AAPL, MSFT], prices={"AAPL": TWO_BARS, "MSFT": UP_5})
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"], plan)

    run(store, day)

    assert store.list_notices(FRI) == {uid: notice}


def test_가격_사실만_있는_다른_종목은_N_more에_세지_않는다(store, admin, make_user):
    day = aapl_news_day(prices={"MSFT": UP_5})
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"], "plus")

    run(store, day)

    assert store.list_notices(FRI) == {uid: "AAPL: Apple named a new CFO"}


KO, PFE = Coverage("KO", "The Coca-Cola Company"), Coverage("PFE", "Pfizer Inc.")  # CIK 없음: 첫 번째 줄 Not covered yet


def downgraded(store, admin, make_user, day):
    """Plus에서 AAPL·KO·PFE·MSFT 순으로 넣고 무료로 내린 유저: 먼저 넣은 셋만 남고 MSFT가 잠긴다."""
    uid = user_with(store, admin, make_user, day, ["AAPL", "KO", "PFE", "MSFT"], "plus")
    set_plan(admin, uid, "free")
    return uid


def test_잠긴_내_종목은_소식이_더_중요해도_알림_후보도_N_more도_아니다(store, admin, make_user):
    day = dataclasses.replace(news_day(aapl=1, msft=5), coverage=[AAPL, MSFT, KO, PFE])
    uid = downgraded(store, admin, make_user, day)

    run(store, day)

    assert store.list_notices(FRI) == {uid: "AAPL: Apple named a new CFO"}


def test_내_종목이_없거나_전부_잠긴_유저는_문구를_만들지_않는다(store, admin, make_user):
    day = dataclasses.replace(news_day(), coverage=[AAPL, MSFT, KO, PFE])
    all_locked = downgraded(store, admin, make_user, day)
    for ticker in ("AAPL", "KO", "PFE"):
        remove(admin, all_locked, ticker)  # 잠긴 MSFT만 남는다
    make_user("plus")  # 내 종목 0개
    uid = user_with(store, admin, make_user, day, ["MSFT"])

    run(store, day)

    assert store.list_notices(FRI) == {uid: "MSFT: Microsoft named a new CFO"}


def test_발행_중단한_카드는_알림_후보도_N_more도_아니다(store, admin, make_user):
    day = news_day(aapl=1, msft=5)
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"])
    run(store, day)
    assert store.list_notices(FRI) == {uid: "MSFT: Microsoft named a new CFO +1 more"}
    admin.execute("update public.stock_card set publish_suspended = true where ticker = 'MSFT'")  # 대시보드에서 켜는 것과 같은 SQL

    run(store, day)

    assert store.list_notices(FRI) == {uid: "AAPL: Apple named a new CFO"}


def test_지연된_첫_번째_줄은_알림_후보도_N_more도_아니다(store, admin, make_user):
    day = aapl_news_day(failures={(Source.SEC_FILINGS, MSFT.cik): FailurePlan("error")})  # MSFT 공시 수집 실패 → Update delayed
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"])

    run(store, day)

    assert store.list_notices(FRI) == {uid: "AAPL: Apple named a new CFO"}


def test_축소판_카드는_첫_번째_줄_대신_오늘_일정이나_가격_사실을_쓴다(store, admin, make_user, monkeypatch):
    monkeypatch.setattr(morning, "news_template_line", lambda *args: None)  # 첫 번째 줄을 못 만든 카드(7:45 마감 축소판, 미구현)
    day = Scenario(coverage=[AAPL, MSFT], prices={"AAPL": UP_5},
                   events={"MSFT": [Earnings(FRI, True, EarningsTiming.AFTER_CLOSE)]})
    both = user_with(store, admin, make_user, day, ["AAPL", "MSFT"], "plus")
    aapl = user_with(store, admin, make_user, day, ["AAPL"], "plus")

    run(store, day)

    assert {c.ticker: c.status for c in store.list_cards(FRI)} == {"AAPL": CardStatus.FALLBACK, "MSFT": CardStatus.FALLBACK}
    assert store.list_notices(FRI) == {both: "MSFT: Earnings Fri 10/16 after close (D-0)", aapl: "AAPL: Up 5 days in a row"}


BUYBACK = "Microsoft said its board authorized an additional share repurchase program covering outstanding common stock"  # 14단어


def test_100자를_넘으면_문장을_단어_경계에서_자르고_말줄임표를_붙인다(store, admin, make_user):
    day = news_day(aapl=1, msft=5)
    day = dataclasses.replace(day, llm_replies=[*day.llm_replies[:2], json.dumps({"sentence": BUYBACK}), FACT, FACT])
    uid = user_with(store, admin, make_user, day, ["AAPL", "MSFT"])

    run(store, day)

    notice = "MSFT: Microsoft said its board authorized an additional share repurchase program covering… +1 more"
    assert store.list_notices(FRI) == {uid: notice}  # 자르지 않으면 122자. +N more는 자르지 않는다
    assert len(notice) == 98


def news_card(text):
    """AAPL 카드 하나, 첫 번째 줄만 확인함·있음."""
    line = CardLine(text, LineStatus.CHECKED_FOUND, datetime(2026, 10, 16, 7, 30, tzinfo=ET), "SEC filings")
    return StockCard("AAPL", FRI, CardStatus.NORMAL, None, LineStatus.DELAYED, news_line=line)


WORDS_94 = "abcdefghi " * 9 + "abcd"  # 94자: "AAPL: " + 94 = 100


@pytest.mark.parametrize("line, notice", [
    (WORDS_94 + " (SEC filing)", "AAPL: " + WORDS_94),
    (WORDS_94 + "e (SEC filing)", "AAPL: " + "abcdefghi " * 8 + "abcdefghi…"),  # 101자 → 마지막 단어를 통째로 뺀다
    ("A" * 120 + " (SEC filing)", "AAPL: " + "A" * 93 + "…"),  # 단어 경계가 없으면 글자에서 자른다
], ids=["100자_그대로", "101자_단어_경계", "경계_없는_한_단어"])
def test_알림_문구는_100자를_넘지_않는다(line, notice):
    assert morning_notice([news_card(line)], {}, Plan.FREE, FRI) == notice
    assert len(notice) <= 100


def test_첫_번째_줄이_15단어면_티커를_붙인_알림도_통과한다():
    # 맨 앞 티커는 코드가 붙인 것이라 단어 수에서 뺀다. 카드 줄 검사처럼 세면 고정 문구로 떨어진다(#12 수정 1)
    sentence = "Apple announced its board of directors elected a new chair at the annual shareholder meeting"  # 15단어
    assert morning_notice([news_card(sentence + " (SEC filing)")], {}, Plan.FREE, FRI) == "AAPL: " + sentence


def republish(admin, human):
    """AAPL 보류함 행을 사람 문장으로 재발행(대시보드와 같은 SQL). 트리거가 카드 첫 번째 줄만 바꾼다."""
    as_service_role(admin, "update public.hold_queue set edited_text = %s, state = 'republished' where ticker = 'AAPL'", (human,))


def test_보류함에서_재발행해도_알림_문구는_다시_만들지_않는다(store, admin, make_user):
    day = one_filing(BUY, BUY)  # 초안이 두 번 금지어 → 대체 줄 + 보류함 행
    uid = user_with(store, admin, make_user, day, ["AAPL"])
    run(store, day)

    republish(admin, "Apple named a new CFO (SEC filing)")

    assert store.list_cards(FRI)[0].news_line.text == "Apple named a new CFO (SEC filing)"
    assert store.list_notices(FRI) == {uid: "AAPL: Apple filed a company update"}


@pytest.mark.parametrize("human", [
    "Apple named a new CFO and the stock is a buy (SEC filing)",
    "Apple named a new CFO for your portfolio (SEC filing)",
    # 15단어·105자: 자르면 "…analysts rate…"만 남아 통과하지만 자르기 전 문장의 금지어로 닫는다
    "Apple said its board authorized an additional share repurchase program and analysts rate shares buy (SEC filing)",
], ids=["금지어", "2인칭", "잘린_꼬리의_금지어"])
def test_금지어_검사에_걸리는_문구는_고정_문구로_바꾼다(store, admin, make_user, human):
    day = one_filing(BUY, BUY)
    uid = user_with(store, admin, make_user, day, ["AAPL"])
    run(store, day)
    republish(admin, human)  # 사람이 쓴 줄은 코드 검수를 거치지 않는다

    run(store, day)  # 재실행은 재발행한 줄을 그대로 두고 알림 문구는 다시 만든다

    assert store.list_notices(FRI) == {uid: QUIET}
    assert check_card(QUIET) == []


def test_알림_문구는_유저별·거래일별로_저장되고_같은_거래일_재실행은_덮어쓴다(store, admin, make_user):
    day = news_day(aapl=1, msft=5)  # 공시는 10-15 10:00 접수 → FRI 카드 소식. THU에는 소식이 없다
    both = user_with(store, admin, make_user, day, ["AAPL", "MSFT"])
    aapl = user_with(store, admin, make_user, day, ["AAPL"])
    run(store, day, THU)
    run(store, day, FRI)

    assert store.list_notices(THU) == {both: QUIET, aapl: QUIET}
    assert store.list_notices(FRI) == {both: "MSFT: Microsoft named a new CFO +1 more", aapl: "AAPL: Apple named a new CFO"}

    remove(admin, aapl, "AAPL")  # 내 종목 0개가 된 유저
    run(store, news_day(aapl=5, msft=1), FRI)

    assert store.list_notices(FRI) == {both: "AAPL: Apple named a new CFO +1 more"}
    assert store.list_notices(THU) == {both: QUIET, aapl: QUIET}  # 다른 거래일 행은 그대로


def test_휴장일에는_알림_문구를_만들지_않는다(store, admin, make_user):
    day = news_day()
    user_with(store, admin, make_user, day, ["AAPL"])

    with pytest.raises(ValueError, match="trading day"):
        run(store, day, THANKSGIVING)

    assert store.list_notices(THANKSGIVING) == {}


# 입구 2: 스키마


def test_계정을_지우면_알림_문구도_같이_지워진다(settings, store, admin, make_user):
    day = news_day()
    uid = user_with(store, admin, make_user, day, ["AAPL"])
    other = user_with(store, admin, make_user, day, ["MSFT"])
    run(store, day)

    # 앱 안 계정 삭제(auth.admin.deleteUser)는 supabase_auth_admin으로 auth.users를 지우고 cascade한다(#38)
    with psycopg.connect(settings.database_url, user="supabase_auth_admin", autocommit=True) as auth:
        auth.execute("delete from auth.users where id = %s", (uid,))

    assert store.list_notices(FRI) == {other: "MSFT: Microsoft named a new CFO"}


def insert_notice(admin, uid, text):
    as_service_role(admin, "insert into public.morning_notice (user_id, trading_day, text) values (%s, '2026-10-16', %s)", (uid, text))


@pytest.mark.parametrize("text", ["", "A" * 101], ids=["빈_문구", "101자"])
def test_빈_문구와_100자를_넘는_문구는_DB가_거부한다(admin, make_user, text):
    uid = make_user()
    insert_notice(admin, uid, "A" * 100)
    admin.execute("delete from public.morning_notice")

    with pytest.raises(errors.CheckViolation):
        insert_notice(admin, uid, text)


def test_같은_유저·거래일_알림_문구는_하나뿐이고_service_role은_읽기·넣기·지우기만_한다(admin, make_user):
    uid = make_user()
    insert_notice(admin, uid, QUIET)

    with pytest.raises(errors.UniqueViolation):
        insert_notice(admin, uid, QUIET)
    allowed = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
               if admin.execute("select has_table_privilege('service_role', 'public.morning_notice', %s)", (p,)).fetchone()[0]]
    assert allowed == ["SELECT", "INSERT", "DELETE"]


# 입구 3: 프로세스 출력


def test_CLI_요약은_알림_문구_수만_찍고_문구는_찍지_않는다(store, admin, make_user, etf_lite):
    store.upsert_coverage(load_scenario(etf_lite).coverage)
    for tickers in (["AAPL"], ["MSFT", "SPY"]):
        uid = make_user()
        for ticker in tickers:
            add(admin, uid, ticker)

    lines = cli(etf_lite)  # 별도 프로세스, 같은 로컬 DB

    notices = store.list_notices(FRI).values()
    assert len(notices) == 2 and all(n != QUIET for n in notices)
    assert "notices=2" in lines
    assert not any(n in line or n.split(": ", 1)[1] in line for n in notices for line in lines)  # 공개 로그: 문장 없음
