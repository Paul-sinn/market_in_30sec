"""입구 1: 실적 추정일(#57). 시나리오 + 가짜 출처(또는 EDGAR 어댑터 + 기록용 get) → MorningPipeline.run → 저장소 읽기 함수.
네트워크 없이 돈다. 거래일 FRI 2026-10-16, 실적 공시 범위 [2025-07-18 04:00, 2026-10-16 04:00) ET."""

import dataclasses
from datetime import date, datetime, timedelta

import pytest

from m30 import trading_day
from m30.adapters import Source, error_for_status
from m30.adapters.edgar import SUBMISSION_TEXT_URL, SUBMISSIONS_URL, EdgarEarningsFilingSource
from m30.adapters.events import Earnings, EarningsTiming
from m30.adapters.fake import FailurePlan, FakeEarningsFilingSource, Scenario, load_scenario
from m30.models import Coverage, EarningsEstimate, LineStatus
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.pipeline.morning import run_failed
from conftest import SCENARIOS
from test_collect_classify import run
from test_edgar import RecordedGet, submission_file, with_rows

FRI = date(2026, 10, 16)
MON = date(2026, 10, 19)
SEC = "SEC filings"
AAPL_CIK, GOOGL_CIK = "0000320193", "0001652044"


def changed(add=(), drop=(), **fields):
    """earnings_estimate.json에서 실적 공시를 더하고(add: (접수번호, ISO 시각)) 뺀다(drop). 접수번호 앞 10자리 = CIK."""
    base = load_scenario(SCENARIOS / "earnings_estimate.json")
    filings = {cik: dict(rows) for cik, rows in base.earnings_filings.items()}
    for accession, at in add:
        filings.setdefault(accession[:10], {})[accession] = datetime.fromisoformat(at)
    for accession in drop:
        del filings[accession[:10]][accession]
    return dataclasses.replace(base, earnings_filings=filings, **fields)


def event_line(store, ticker, day=FRI):
    line = next(c for c in store.list_cards(day) if c.ticker == ticker).event_line
    return line.text, line.status, line.source_scope


@pytest.mark.parametrize(
    "ticker, line, row",
    [
        ("AAPL", "Earnings Thu 10/29 after close (est.) (D-13)",
         EarningsEstimate(date(2026, 10, 29), EarningsTiming.AFTER_CLOSE, "0000320193-25-000101")),
        ("JPM", "Earnings Tue 10/20 before open (est.) (D-4)",
         EarningsEstimate(date(2026, 10, 20), EarningsTiming.BEFORE_OPEN, "0000019617-25-000101")),
        ("MSFT", "Earnings Tue 10/27 (est.) (D-11)", EarningsEstimate(date(2026, 10, 27), None, "0000789019-25-000101")),  # 섞임
        ("KO", "Earnings Tue 10/20 (est.) (D-4)", EarningsEstimate(date(2026, 10, 20), None, "0000021344-25-000101")),  # 3건
        # 추정일(10/6)이 지난 뒤 10/9 공시가 들어옴 → 다음 분기. 기준 = 2026-02-03(작년 10월 공시의 짝은 10/9 자신)
        ("XOM", "Earnings Tue 2/2 before open (est.) (D-109)",
         EarningsEstimate(date(2027, 2, 2), EarningsTiming.BEFORE_OPEN, "0000034088-26-000021")),
    ],
    ids=["after_close", "before_open", "mixed", "three_filings", "next_quarter"],
)
def test_작년_같은_분기_실적_공시_접수일에_364일을_더한_날을_est로_보여주고_행으로_저장한다(store, earnings_estimate, ticker, line, row):
    run(store, earnings_estimate)

    assert event_line(store, ticker) == (line, LineStatus.CHECKED_FOUND, SEC)
    assert store.list_earnings_estimates(FRI)[ticker] == row


def test_지난_4개_분기가_모두_장_후면_after_close_모두_장_전이면_before_open_섞이면_날짜만이다(store, earnings_estimate):
    run(store, earnings_estimate)

    timings = {t: e.timing for t, e in store.list_earnings_estimates(FRI).items() if t in ("AAPL", "JPM", "MSFT")}
    assert timings == {"AAPL": EarningsTiming.AFTER_CLOSE, "JPM": EarningsTiming.BEFORE_OPEN, "MSFT": None}  # MSFT 4월만 09:45


@pytest.mark.parametrize(
    "accession, at, ticker, line",
    [
        ("0000019617-26-000041", "2026-04-21T09:29:59-04:00", "JPM", "Earnings Tue 10/20 before open (est.) (D-4)"),
        ("0000019617-26-000041", "2026-04-21T09:30:00-04:00", "JPM", "Earnings Tue 10/20 (est.) (D-4)"),
        ("0000320193-26-000041", "2026-04-30T15:59:59-04:00", "AAPL", "Earnings Thu 10/29 (est.) (D-13)"),
        ("0000320193-26-000041", "2026-04-30T16:00:00-04:00", "AAPL", "Earnings Thu 10/29 after close (est.) (D-13)"),
    ],
    ids=["09:29:59", "09:30:00", "15:59:59", "16:00:00"],
)
def test_장_전은_09시30분_전이고_장_후는_16시_정각부터다(store, accession, at, ticker, line):
    run(store, changed(add=[(accession, at)]))  # 한 분기만 바꾼다

    assert event_line(store, ticker) == (line, LineStatus.CHECKED_FOUND, SEC)


def test_작년_같은_분기_공시는_있지만_그_사이_공시가_4건_미만이면_날짜만이다(store, earnings_estimate):
    run(store, earnings_estimate)  # KO: 2025-10-21, 2026-02-10, 07-21 장 전(4월 공시 없음)
    assert event_line(store, "KO") == ("Earnings Tue 10/20 (est.) (D-4)", LineStatus.CHECKED_FOUND, SEC)

    run(store, changed(add=[("0000021344-26-000041", "2026-04-21T06:55:00-04:00")]))  # 빠진 분기가 들어오면 4건
    assert event_line(store, "KO") == ("Earnings Tue 10/20 before open (est.) (D-4)", LineStatus.CHECKED_FOUND, SEC)


def test_실적_공시_이력이_1년이_안_되면_Not_covered_yet이고_행이_없다(store, earnings_estimate):
    run(store, earnings_estimate)  # NVDA: 2026-02-25부터 3건. 작년 같은 분기 공시가 없다

    assert event_line(store, "NVDA") == ("Not covered yet", LineStatus.UNSUPPORTED, None)
    assert "NVDA" not in store.list_earnings_estimates(FRI)


def test_추정일이_지났는데_실적_공시가_없으면_No_confirmed_events_found이고_범위는_SEC_filings다(store, earnings_estimate):
    run(store, earnings_estimate)  # PFE: 작년 10/7 → 추정일 10/6, 그 뒤 실적 공시 없음

    assert event_line(store, "PFE") == ("No confirmed events found", LineStatus.CHECKED_NONE, SEC)
    # 지난 추정도 행은 남는다(estimate_day < trading_day)
    assert store.list_earnings_estimates(FRI)["PFE"] == EarningsEstimate(
        date(2026, 10, 6), EarningsTiming.BEFORE_OPEN, "0000078003-25-000101")


def test_추정일이_지난_뒤_실적_공시가_들어오면_다음_분기를_추정한다(store):
    run(store, changed(drop=["0000034088-26-000101"]))  # XOM 10/9 공시 전: PFE와 같은 모양
    assert event_line(store, "XOM") == ("No confirmed events found", LineStatus.CHECKED_NONE, SEC)

    run(store, changed())  # 10/9 07:00 공시가 들어옴
    assert event_line(store, "XOM") == ("Earnings Tue 2/2 before open (est.) (D-109)", LineStatus.CHECKED_FOUND, SEC)


@pytest.mark.parametrize(
    "at, line",
    [
        # 범위 안: 최근 공시가 10/16이 되어 기준이 2026-01-29로 바뀐다. 시점은 섞임(03:59:59는 장 전)
        ("2026-10-16T03:59:59-04:00", "Earnings Thu 1/28 (est.) (D-104)"),
        ("2026-10-16T04:00:00-04:00", "Earnings Thu 10/29 after close (est.) (D-13)"),  # = 범위 끝: 다음 거래일 카드 몫
    ],
    ids=["03:59:59", "04:00:00"],
)
def test_거래일_04시_정각_뒤_공시는_그날_카드의_추정에_쓰지_않는다(store, at, line):
    run(store, changed(add=[("0000320193-26-000101", at)]))

    assert event_line(store, "AAPL") == (line, LineStatus.CHECKED_FOUND, SEC)


# 분기마다 공시하다 2026년 7월 공시가 없는 회사. 최근 공시 r = 2026-04-17
LATE = [("0000078003-25-000071", "2025-07-18T{}-04:00"), ("0000078003-25-000102", "2025-10-17T07:00:00-04:00"),
        ("0000078003-26-000011", "2026-01-16T07:00:00-05:00"), ("0000078003-26-000041", "2026-04-17T07:00:00-04:00")]


@pytest.mark.parametrize(
    "at, line",
    [
        ("04:00:00", ("No confirmed events found", LineStatus.CHECKED_NONE, SEC)),  # 범위 시작(2025-07-18 04:00) 포함: 추정일 7/17 지남
        ("03:59:59", ("Not covered yet", LineStatus.UNSUPPORTED, None)),  # 빠지면 작년 같은 분기 공시가 없다
    ],
    ids=["04:00:00", "03:59:59"],
)
def test_범위_시작_04시_전_공시는_쓰지_않는다(store, at, line):
    late = [(LATE[0][0], LATE[0][1].format(at)), *LATE[1:]]
    run(store, dataclasses.replace(changed(), earnings_filings={"0000078003": {a: datetime.fromisoformat(t) for a, t in late}}))

    assert event_line(store, "PFE") == line


# 한 분기에 실적 공시가 둘인 회사(#89, TSLA 모양): 분기 초 09시대 판매 대수 8-K + 약 20일 뒤 16시대 실적 8-K(둘 다 Item 2.02).
# 26-000016·046717·049213·064366·066738은 #57 실측 기록의 접수번호·시각, 나머지는 같은 모양으로 채운 값
TSLA_CIK = "0001318605"
TESLA = {
    "0001628280-25-000401": "2025-04-02T09:00:00-04:00", "0001628280-25-000422": "2025-04-22T16:30:00-04:00",
    "0001628280-25-000702": "2025-07-02T09:00:00-04:00", "0001628280-25-000723": "2025-07-23T16:30:00-04:00",
    "0001628280-25-001002": "2025-10-02T09:00:00-04:00", "0001628280-25-001022": "2025-10-22T16:30:00-04:00",
    "0001628280-26-000016": "2026-01-02T09:20:13-05:00", "0001628280-26-000128": "2026-01-28T16:30:00-05:00",
    "0001628280-26-000402": "2026-04-02T09:00:00-04:00", "0001628280-26-000422": "2026-04-22T16:30:00-04:00",
    "0001628280-26-046717": "2026-07-02T09:01:26-04:00", "0001628280-26-049213": "2026-07-22T16:35:52-04:00",
    "0001628280-26-064366": "2026-10-02T09:04:26-04:00", "0001628280-26-066738": "2026-10-21T16:41:42-04:00",
}


def tesla():
    return dataclasses.replace(changed(), coverage=[Coverage("TSLA", "Tesla, Inc.", cik=TSLA_CIK)],
                               earnings_filings={TSLA_CIK: {a: datetime.fromisoformat(t) for a, t in TESLA.items()}})


@pytest.mark.parametrize(
    "day, line, row",
    [
        # 수정 전: 판매 대수 공시를 따라가 Fri 1/1(휴장일), 시점은 09시대·16시대가 섞여 없음
        (date(2026, 11, 6), "Earnings Wed 1/27 after close (est.) (D-82)",
         EarningsEstimate(date(2027, 1, 27), EarningsTiming.AFTER_CLOSE, "0001628280-26-000128")),
        # 되돌려 보기: 판매 대수 공시 날. 수정 전에는 작년 판매 대수 공시(+364 = 하루 전)로 추정해 No confirmed events found
        (date(2026, 10, 2), "Earnings Wed 10/21 after close (est.) (D-19)",
         EarningsEstimate(date(2026, 10, 21), EarningsTiming.AFTER_CLOSE, "0001628280-25-001022")),
        (date(2026, 7, 2), "Earnings Wed 7/22 after close (est.) (D-20)",
         EarningsEstimate(date(2026, 7, 22), EarningsTiming.AFTER_CLOSE, "0001628280-25-000723")),
    ],
    ids=["2026-11-06", "2026-10-02", "2026-07-02"],
)
def test_한_분기에_실적_공시가_둘이면_늦은_공시를_그_분기_실적_발표로_보고_추정한다(store, day, line, row):
    run(store, tesla(), day)

    assert event_line(store, "TSLA", day) == (line, LineStatus.CHECKED_FOUND, SEC)
    assert store.list_earnings_estimates(day)["TSLA"] == row


@pytest.mark.parametrize(
    "day, line, row",
    [
        # 되돌려 보기: 실적 공시 날. 그 분기 판매 대수 공시만 범위에 있다. 수정 전 Fri 1/1(차이 −72·−71일)
        (date(2026, 10, 21), "Earnings Wed 10/21 after close (est.) (D-0)",
         EarningsEstimate(date(2026, 10, 21), EarningsTiming.AFTER_CLOSE, "0001628280-25-001022")),
        (date(2026, 7, 22), "Earnings Wed 7/22 after close (est.) (D-0)",
         EarningsEstimate(date(2026, 7, 22), EarningsTiming.AFTER_CLOSE, "0001628280-25-000723")),
    ],
    ids=["2026-10-21", "2026-07-22"],
)
def test_이번_분기_앞_공시만_들어왔으면_작년_같은_분기의_늦은_공시로_이번_분기를_추정한다(store, day, line, row):
    run(store, tesla(), day)

    assert event_line(store, "TSLA", day) == (line, LineStatus.CHECKED_FOUND, SEC)
    assert store.list_earnings_estimates(day)["TSLA"] == row


@pytest.mark.parametrize(
    "prelim",
    [
        ("0000320193-25-000091", "2025-10-09T07:00:00-04:00"),  # 작년 같은 분기. 수정 전: 사전 발표 +364 = 10/8 지남 → No confirmed events found
        ("0000320193-26-000061", "2026-07-09T07:00:00-04:00"),  # 지난 분기. 수정 전: 07:00이 섞여 시점 없음
    ],
    ids=["last_year_quarter", "last_quarter"],
)
def test_같은_분기에_사전_발표_뒤_본_발표가_있으면_본_발표로만_추정일과_장_전_장_후를_정한다(store, prelim):
    run(store, changed(add=[prelim]))  # AAPL 본 발표는 전부 16:30

    assert event_line(store, "AAPL") == ("Earnings Thu 10/29 after close (est.) (D-13)", LineStatus.CHECKED_FOUND, SEC)
    assert store.list_earnings_estimates(FRI)["AAPL"] == EarningsEstimate(
        date(2026, 10, 29), EarningsTiming.AFTER_CLOSE, "0000320193-25-000101")


# 분기마다 2일 09:00에 공시하는 회사. 기준 2026-01-02(Fri) + 364 = 2027-01-01(Fri, 휴장일)
NEW_YEAR = {"0000078003-25-000101": "2025-10-02T09:00:00-04:00", "0000078003-26-000001": "2026-01-02T09:00:00-05:00",
            "0000078003-26-000041": "2026-04-02T09:00:00-04:00", "0000078003-26-000071": "2026-07-02T09:00:00-04:00",
            "0000078003-26-000101": "2026-10-02T09:00:00-04:00"}


def test_추정일이_휴장일이면_다음_거래일로_옮기고_D_N도_그날로_센다(store):
    run(store, dataclasses.replace(
        changed(), earnings_filings={"0000078003": {a: datetime.fromisoformat(t) for a, t in NEW_YEAR.items()}}))

    assert event_line(store, "PFE") == ("Earnings Mon 1/4 before open (est.) (D-80)", LineStatus.CHECKED_FOUND, SEC)
    assert store.list_earnings_estimates(FRI)["PFE"] == EarningsEstimate(
        date(2027, 1, 4), EarningsTiming.BEFORE_OPEN, "0000078003-26-000001")


def test_추정일의_해가_휴장일_표_밖이면_옮기지_않고_카드를_만든다(store, monkeypatch):
    monkeypatch.setattr(trading_day, "CALENDAR_YEARS", range(2025, 2027))  # NYSE가 내년 휴장일을 아직 안 실은 때
    run(store, dataclasses.replace(
        changed(), earnings_filings={"0000078003": {a: datetime.fromisoformat(t) for a, t in NEW_YEAR.items()}}))

    assert event_line(store, "PFE") == ("Earnings Fri 1/1 before open (est.) (D-77)", LineStatus.CHECKED_FOUND, SEC)


def stored_times(admin):
    """earnings_filing 전체: 접수번호 → (CIK, 헤더 접수 시각)."""
    return {a: (cik, at) for a, cik, at in admin.execute(
        "select accession, cik, accepted_at from public.earnings_filing order by accession").fetchall()}


def test_헤더_시각은_접수번호마다_한_번만_읽고_다음_거래일에는_저장한_시각을_쓴다(store, admin, earnings_estimate):
    first = run(store, earnings_estimate)
    saved = stored_times(admin)

    assert sorted(first.earnings.header_calls) == sorted(saved)  # 실적 공시 27건(AAPL·JPM·MSFT·PFE 4, KO·NVDA 3, XOM 5)을 한 번씩
    assert len(saved) == 27
    assert saved["0000320193-25-000101"] == (AAPL_CIK, datetime.fromisoformat("2025-10-30T16:30:00-04:00"))

    second = run(store, earnings_estimate, MON)

    assert second.earnings.header_calls == []  # 목록은 다시 받고 헤더는 읽지 않는다
    assert sorted(second.earnings.calls) == sorted(first.earnings.calls)
    assert stored_times(admin) == saved
    assert event_line(store, "AAPL", MON) == ("Earnings Thu 10/29 after close (est.) (D-10)", LineStatus.CHECKED_FOUND, SEC)


def test_같은_거래일을_다시_실행해도_같은_추정일_행과_같은_줄이다(store, earnings_estimate):
    run(store, earnings_estimate)
    rows, lines = store.list_earnings_estimates(FRI), {c.ticker: c.event_line.text for c in store.list_cards(FRI)}

    run(store, earnings_estimate)

    assert store.list_earnings_estimates(FRI) == rows
    assert sorted(rows) == ["AAPL", "JPM", "KO", "MSFT", "PFE", "XOM"]  # NVDA(1년 미만)·SPY(ETF)는 행이 없다
    assert {c.ticker: c.event_line.text for c in store.list_cards(FRI)} == lines


def test_실적_공시는_첫_번째_줄_공시_표에_들어가지_않고_분류·LLM을_부르지_않는다(store, earnings_estimate):
    ran = run(store, earnings_estimate)

    assert store.list_raw_filings(FRI) == {}
    assert ran.llm.requests == []
    assert ran.summary.filings_collected == 0
    assert {c.ticker: c.news_line.text for c in store.list_cards(FRI) if c.ticker != "SPY"} == dict.fromkeys(
        ["AAPL", "JPM", "KO", "MSFT", "NVDA", "PFE", "XOM"], "No new SEC filings found")  # 과거 실적 공시는 새 소식이 아니다


ALPHABET = {"0001652044-25-000101": "2025-10-29T16:05:00-04:00", "0001652044-26-000011": "2026-02-04T16:05:00-05:00",
            "0001652044-26-000041": "2026-04-28T16:05:00-04:00", "0001652044-26-000071": "2026-07-28T16:05:00-04:00"}


def test_같은_CIK의_티커_둘은_목록을_한_번_받고_두_티커에_같은_행을_쓴다(store):
    ran = run(store, dataclasses.replace(
        changed(),
        coverage=[Coverage("GOOG", "Alphabet Inc.", cik=GOOGL_CIK), Coverage("GOOGL", "Alphabet Inc.", cik=GOOGL_CIK)],
        earnings_filings={GOOGL_CIK: {a: datetime.fromisoformat(t) for a, t in ALPHABET.items()}},
    ))

    assert ran.earnings.calls == [GOOGL_CIK]
    assert len(ran.earnings.header_calls) == 4
    row = EarningsEstimate(date(2026, 10, 28), EarningsTiming.AFTER_CLOSE, "0001652044-25-000101")
    assert store.list_earnings_estimates(FRI) == {"GOOG": row, "GOOGL": row}
    line = ("Earnings Wed 10/28 after close (est.) (D-12)", LineStatus.CHECKED_FOUND, SEC)
    assert event_line(store, "GOOG") == event_line(store, "GOOGL") == line


def test_ETF와_CIK_없는_종목은_실적_추정_출처를_부르지_않고_두_번째_줄이_그대로다(store):
    ran = run(store, changed(coverage=[
        Coverage("AAPL", "Apple Inc.", cik=AAPL_CIK),
        Coverage("SPY", "SPDR S&P 500 ETF Trust", holdings_ticker="SPY"),
        Coverage("QQQ", "Invesco QQQ", cik="0001067839", holdings_ticker="QQQ"),  # CIK가 있어도 편입 종목을 읽는 ETF
        Coverage("BRK", "Berkshire Hathaway"),  # CIK 없음
    ]))

    assert ran.earnings.calls == [AAPL_CIK]
    for ticker in ("SPY", "QQQ", "BRK"):
        assert event_line(store, ticker) == ("Not covered yet", LineStatus.UNSUPPORTED, None)
    assert sorted(store.list_earnings_estimates(FRI)) == ["AAPL"]


def test_일정_출처가_값을_주는_종목은_그_값으로_두_번째_줄을_만든다(store):
    run(store, changed(events={"AAPL": [Earnings(date(2026, 10, 29), True, EarningsTiming.AFTER_CLOSE)], "JPM": []}))

    calendar = "Earnings and dividend calendar"
    assert event_line(store, "AAPL") == ("Earnings Thu 10/29 after close (D-13)", LineStatus.CHECKED_FOUND, calendar)  # 확정
    assert event_line(store, "JPM") == ("No confirmed events found", LineStatus.CHECKED_NONE, calendar)
    assert event_line(store, "MSFT") == ("Earnings Tue 10/27 (est.) (D-11)", LineStatus.CHECKED_FOUND, SEC)  # 일정 출처 None


DELAYED = ("Update delayed", LineStatus.DELAYED, SEC)
ERRORS = {  # 실패 종류 → (목록 호출 수, 대기, 실패 사유). test_collect_classify.ERRORS와 같은 규칙
    "transient": (4, [1.0, 2.0, 4.0], FailureReason.RETRIES_EXHAUSTED),
    "error": (1, [], FailureReason.ERROR),
    "access_denied": (1, [], FailureReason.ACCESS_DENIED),
    "rate_limited": (4, [1.0, 2.0, 4.0], FailureReason.RETRIES_EXHAUSTED),
}
NORMAL_LINES = {
    "AAPL": ("Earnings Thu 10/29 after close (est.) (D-13)", LineStatus.CHECKED_FOUND, SEC),
    "JPM": ("Earnings Tue 10/20 before open (est.) (D-4)", LineStatus.CHECKED_FOUND, SEC),
    "KO": ("Earnings Tue 10/20 (est.) (D-4)", LineStatus.CHECKED_FOUND, SEC),
    "MSFT": ("Earnings Tue 10/27 (est.) (D-11)", LineStatus.CHECKED_FOUND, SEC),
    "NVDA": ("Not covered yet", LineStatus.UNSUPPORTED, None),
    "PFE": ("No confirmed events found", LineStatus.CHECKED_NONE, SEC),
    "SPY": ("Not covered yet", LineStatus.UNSUPPORTED, None),
    "XOM": ("Earnings Tue 2/2 before open (est.) (D-109)", LineStatus.CHECKED_FOUND, SEC),
}
MSFT_CIK, NVDA_CIK = "0000789019", "0001045810"


def event_lines(store, day=FRI):
    return {c.ticker: (c.event_line.text, c.event_line.status, c.event_line.source_scope) for c in store.list_cards(day)}


@pytest.mark.parametrize("error", ERRORS)
def test_실적_추정_출처_실패는_종류대로_다시_시도하고_그_종목만_지연이다(store, error):
    ran = run(store, changed(failures={(Source.EARNINGS, AAPL_CIK): FailurePlan(error)}))

    count, sleeps, reason = ERRORS[error]
    denied = error == "access_denied"
    assert ran.earnings.calls.count(AAPL_CIK) == count
    assert ran.sleeps == sleeps
    # CIK 정렬 순: AAPL(0000320193) 뒤는 MSFT·NVDA. 401·403 뒤에는 부르지 않고 차단으로 남긴다
    blocked = [MSFT_CIK, NVDA_CIK] if denied else []
    assert [c for c in ran.earnings.calls if c in blocked] == []
    assert ran.summary.failures == tuple(SourceFailure(Source.EARNINGS, c, reason) for c in [AAPL_CIK, *blocked])
    assert ran.summary.access_denied == ((Source.EARNINGS,) if denied else ())
    assert ran.summary.rate_limited == ((Source.EARNINGS,) if error == "rate_limited" else ())
    assert run_failed(ran.summary) is True
    delayed = ["AAPL", "MSFT", "NVDA"] if denied else ["AAPL"]
    assert event_lines(store) == NORMAL_LINES | dict.fromkeys(delayed, DELAYED)
    assert not set(delayed) & set(store.list_earnings_estimates(FRI))  # 실패한 종목은 행을 쓰지 않는다


def test_헤더_읽기가_실패하면_그_종목만_지연이고_앞에서_읽은_시각은_남는다(store, admin):
    failing = "0000320193-26-000041"
    ran = run(store, changed(failures={(Source.EARNINGS, failing): FailurePlan("error")}))

    assert ran.summary.failures == (SourceFailure(Source.EARNINGS, failing, FailureReason.ERROR),)
    assert event_lines(store) == NORMAL_LINES | {"AAPL": DELAYED}
    aapl = sorted(a for a in stored_times(admin) if a.startswith(AAPL_CIK))
    assert aapl == ["0000320193-25-000101", "0000320193-26-000011"]  # 정렬 순으로 앞의 둘은 저장됐다

    again = run(store, changed(), MON)

    assert again.earnings.header_calls == [failing, "0000320193-26-000071"]  # 남은 둘만 읽는다
    assert event_line(store, "AAPL", MON) == ("Earnings Thu 10/29 after close (est.) (D-10)", LineStatus.CHECKED_FOUND, SEC)


def test_목록이_접수번호_형식이_아니면_그_종목만_지연이다(store):
    base = changed()
    aapl = base.earnings_filings[AAPL_CIK] | {"0000320193-26-41": datetime.fromisoformat("2026-04-30T16:30:00-04:00")}
    ran = run(store, dataclasses.replace(base, earnings_filings=base.earnings_filings | {AAPL_CIK: aapl}))

    assert ran.summary.failures == (SourceFailure(Source.EARNINGS, AAPL_CIK, FailureReason.INVALID_DATA),)
    assert not [a for a in ran.earnings.header_calls if a.startswith(AAPL_CIK)]  # 이상한 목록으로 헤더를 받지 않는다
    assert event_lines(store) == NORMAL_LINES | {"AAPL": DELAYED}


def test_헤더_시각에_시간대가_없으면_그_종목만_지연이다(store):
    base = changed()
    naive = "0000320193-26-000041"
    aapl = base.earnings_filings[AAPL_CIK] | {naive: datetime(2026, 4, 30, 16, 30)}
    ran = run(store, dataclasses.replace(base, earnings_filings=base.earnings_filings | {AAPL_CIK: aapl}))

    assert ran.summary.failures == (SourceFailure(Source.EARNINGS, naive, FailureReason.INVALID_DATA),)
    assert event_lines(store) == NORMAL_LINES | {"AAPL": DELAYED}


# EDGAR 어댑터(EdgarEarningsFilingSource) + 기록용 get. 실적 추정 말고는 빈 가짜 출처
AAPL_SUBMISSIONS = SUBMISSIONS_URL.format(cik=AAPL_CIK)
RESULTS = "2.02 Results of Operations and Financial Condition"
AAPL_QUARTERS = {"0000320193-25-000101": "20251030163000", "0000320193-26-000011": "20260129163000",
                 "0000320193-26-000041": "20260430163000", "0000320193-26-000071": "20260730163000"}


def txt(accession, cik=AAPL_CIK):
    return SUBMISSION_TEXT_URL.format(cik_number=int(cik), accession_digits=accession.replace("-", ""), accession=accession)


def listed(header):
    """submissions acceptanceDateTime의 관측 모양(test_edgar A1): 헤더 동부 벽시계 + 정확히 8시간에 Z."""
    return (datetime.strptime(header, "%Y%m%d%H%M%S") + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def row(accession, header, form="8-K", items="2.02,9.01"):
    return accession, form, listed(header), items, ""


def headers(times):
    """접수번호 → 헤더 시각(YYYYMMDDHHMMSS) → 전체 제출 파일 응답."""
    return {txt(a): submission_file(a, header, RESULTS) for a, header in times.items()}


def run_edgar(store, get, coverage=(Coverage("AAPL", "Apple Inc.", cik=AAPL_CIK),), day=FRI):
    return run(store, Scenario(coverage=list(coverage), prices={}), day, earnings=EdgarEarningsFilingSource(get))


def test_실적_공시는_8_K이고_항목에_2_02가_있는_것만이고_정정_공시는_빼고_헤더만_받는다(store):
    (q1, h1), (q2, h2), (q3, h3), (q4, h4) = AAPL_QUARTERS.items()
    get = RecordedGet({AAPL_SUBMISSIONS: with_rows(
        row(q4, h4, items="2.02"),
        row("0000320193-26-000072", "20260731080000", form="8-K/A", items="2.02"),  # 정정 공시
        row("0000320193-26-000073", "20260801080000", items="8.01"),  # 실적 아닌 8-K
        row("0000320193-26-000074", "20260801090000", form="4", items=""),
        row(q3, h3, items="2.02,9.01"),
        row(q2, h2, items="7.01,2.02"),  # 2.02가 뒤에 있어도
        row(q1, h1, items="2.02,9.01"),
    )} | headers(AAPL_QUARTERS))

    ran = run_edgar(store, get)

    assert get.urls == [AAPL_SUBMISSIONS, txt(q1), txt(q2), txt(q3), txt(q4)]  # 실적 공시 넷만, 접수번호 순
    assert ran.summary.failures == ()
    assert event_line(store, "AAPL") == ("Earnings Thu 10/29 after close (est.) (D-13)", LineStatus.CHECKED_FOUND, SEC)


def test_후보는_submissions_시각_앞뒤_12시간이고_추정에는_헤더_시각만_쓴다(store, admin):
    # 범위 [2025-07-18 04:00 EDT(08:00Z), 2026-10-16 04:00). 후보 창 시작 = 2025-07-17 20:00Z
    late = {"0000320193-25-000071": "20250718035959",  # 헤더로는 범위 시작 1초 전. submissions 시각(11:59:59Z)으로는 범위 안
            "0000320193-25-000102": "20251017070000", "0000320193-26-000011": "20260116070000",
            "0000320193-26-000041": "20260417070000"}  # 2026년 7월 공시 없음
    margin = {"0000320193-25-000061": "20250717120000"}  # submissions 시각을 후보 창 시작에 맞춘다(헤더로는 범위 밖)
    get = RecordedGet({AAPL_SUBMISSIONS: with_rows(
        *(row(a, h) for a, h in late.items()),
        ("0000320193-25-000061", "8-K", "2025-07-17T20:00:00.000Z", "2.02", ""),
        ("0000320193-25-000060", "8-K", "2025-07-17T19:59:59.000Z", "2.02", ""),  # 후보 창 1초 전: 받지 않는다
    )} | headers(late | margin))

    run_edgar(store, get)

    assert get.urls == [AAPL_SUBMISSIONS, *(txt(a) for a in sorted(late | margin))]
    assert sorted(stored_times(admin)) == sorted(late | margin)  # 범위 밖 헤더도 받은 시각은 저장한다
    # submissions 시각을 썼다면 2025-07-18 공시가 기준 → No confirmed events found. 헤더로 빼면 작년 같은 분기 공시가 없다
    assert event_line(store, "AAPL") == ("Not covered yet", LineStatus.UNSUPPORTED, None)


def test_두_번째_실행은_submissions만_받고_전체_제출_파일은_다시_받지_않는다(store):
    rows = with_rows(*(row(a, h) for a, h in AAPL_QUARTERS.items()))
    run_edgar(store, RecordedGet({AAPL_SUBMISSIONS: rows} | headers(AAPL_QUARTERS)))
    get = RecordedGet({AAPL_SUBMISSIONS: rows})  # 전체 제출 파일을 요청하면 AssertionError

    run_edgar(store, get, day=MON)

    assert get.urls == [AAPL_SUBMISSIONS]
    assert event_line(store, "AAPL", MON) == ("Earnings Thu 10/29 after close (est.) (D-10)", LineStatus.CHECKED_FOUND, SEC)


def test_헤더에_접수_시각이_없으면_그_종목은_지연이고_다른_공시로_대신하지_않는다(store, admin):
    last, header = "0000320193-26-000071", AAPL_QUARTERS["0000320193-26-000071"]
    no_time = submission_file(last, header, RESULTS).replace(f"<ACCEPTANCE-DATETIME>{header}\n".encode(), b"")
    get = RecordedGet({AAPL_SUBMISSIONS: with_rows(*(row(a, h) for a, h in AAPL_QUARTERS.items()))}
                      | headers(AAPL_QUARTERS) | {txt(last): no_time})

    ran = run_edgar(store, get)

    assert get.urls.count(txt(last)) == 1  # 형식 오류는 다시 시도하지 않는다
    assert ran.summary.failures == (SourceFailure(Source.EARNINGS, last, FailureReason.ERROR),)
    # 남은 셋으로 계산하면 Not covered yet이 된다. 모르는 것을 미지원으로 바꾸지 않는다
    assert event_line(store, "AAPL") == DELAYED
    assert store.list_earnings_estimates(FRI) == {}
    assert sorted(stored_times(admin)) == sorted(AAPL_QUARTERS)[:3]


def test_SEC가_403이면_실적_추정을_다시_부르지_않고_남은_종목도_지연이다(store):
    get = RecordedGet({AAPL_SUBMISSIONS: error_for_status("sec", 403)})  # GOOGL submissions는 없다: 요청하면 AssertionError

    ran = run_edgar(store, get, coverage=[Coverage("AAPL", "Apple Inc.", cik=AAPL_CIK),
                                          Coverage("GOOGL", "Alphabet Inc.", cik=GOOGL_CIK)])

    assert get.urls == [AAPL_SUBMISSIONS]
    assert ran.sleeps == []
    assert ran.summary.access_denied == (Source.EARNINGS,)
    assert ran.summary.failures == (SourceFailure(Source.EARNINGS, AAPL_CIK, FailureReason.ACCESS_DENIED),
                                    SourceFailure(Source.EARNINGS, GOOGL_CIK, FailureReason.ACCESS_DENIED))
    assert event_lines(store) == {"AAPL": DELAYED, "GOOGL": DELAYED}
