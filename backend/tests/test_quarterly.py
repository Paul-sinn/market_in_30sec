"""분기 작업(#60). 네트워크 없음, 로컬 DB.
입구 3(프로세스 출력): 분기 작업 CLI를 하위 프로세스(quarterly_probe)로 돌려 exit 코드·출력을 본다. 바꾸는 것은 전송 층(EdgarClient) 하나.
입구 4(분기 작업 실행): run_quarterly + 실제 EdgarAnnualReportSource에 기록용 get(test_edgar.RecordedGet)과 합성 SEC 응답(quarterly_probe).
결과는 저장소 읽기 함수(latest_annual_reports·annual_report·coverage_sics)로 본다."""

import dataclasses
import gzip
import http.client
import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from m30.adapters import Source, TransientSourceError, edgar, error_for_status
from m30.adapters.edgar import (
    ANNUAL_REPORT_FILE_MAX,
    MIN_INTERVAL,
    QUARTERLY_INTERVAL,
    EdgarAnnualReportSource,
    EdgarClient,
    Throttle,
)
from m30.adapters.filings import ANNUAL_REPORT_BODY_MAX, AnnualReport, AnnualReportListing
from m30.config import ET, load_edgar_settings
from m30.db.store import LOCK_CLASS, CardStore, connect
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.pipeline.quarterly import QuarterlySummary, quarterly_failed, run_quarterly
from quarterly_probe import (
    AAPL,
    ACCESSIONS,
    BODY_CANARY,
    COMPANIES,
    EVIDENCE_CANARY,
    EXCERPT_CANARY,
    FACT_CANARY,
    MENTION_CANARY,
    GOOGL,
    MAIN_HTML,
    MSFT,
    NAME_CANARY,
    NO_SIC,
    SICS,
    annual_day,
    annual_report_file,
    annual_submissions,
    submissions_url,
    txt_url,
)
from test_edgar import UA, RecordedGet


class NoCallLLM:
    """LLM 자리. 여기 10-K 본문(MAIN_HTML)은 Item 1이 ITEM1_MIN보다 짧아 연관 종목 단계(#64)가 LLM을 부르지 않는다(no_item1)."""

    def complete(self, request):
        raise AssertionError("unexpected LLM request")


def run(store, get, coverage=COMPANIES):
    """커버 범위를 심고 분기 작업 한 번. sleep은 기록만(다시 시도를 실제로 기다리지 않는다). 연관 종목·알아두기 요약은 test_relations·test_quiet_facts가 본다."""
    store.upsert_coverage(coverage)
    sleeps = []
    return run_quarterly(store, reports=EdgarAnnualReportSource(get), llm=NoCallLLM(), sleep=sleeps.append), sleeps


def test_분기_작업은_커버_범위_회사마다_최신_10_K_원문과_접수_시각을_저장하고_sic를_채운다(store):
    get = RecordedGet(annual_day())

    summary, _ = run(store, get)

    assert summary == QuarterlySummary(3, 3, 0, 0, 3, 0, (), (), (), ANY, ANY)
    assert store.latest_annual_reports() == {AAPL: ACCESSIONS[AAPL], MSFT: ACCESSIONS[MSFT], GOOGL: ACCESSIONS[GOOGL]}
    report = store.annual_report(ACCESSIONS[MSFT])
    assert (report.accession, report.cik) == (ACCESSIONS[MSFT], MSFT)
    assert report.accepted_at == datetime(2025, 10, 31, 18, 5, 2, tzinfo=ET)  # 헤더 시각. submissions 시각(녹화 값)이 아니다
    assert report.accepted_at.tzinfo is ET
    # 같은 CIK의 티커(GOOGL·GOOG)는 같은 값. ETF(SPY·XLK)는 없다
    assert store.coverage_sics() == {"AAPL": "3571", "GOOG": "7370", "GOOGL": "7370", "MSFT": "7372"}
    # CIK 순, 회사마다 submissions → 전체 제출 파일. GOOGL·GOOG는 한 번. MSFT 주소는 회사 CIK(접수번호 앞자리 아님)
    assert get.urls == [submissions_url(AAPL), txt_url(AAPL, ACCESSIONS[AAPL]), submissions_url(MSFT),
                        txt_url(MSFT, ACCESSIONS[MSFT]), submissions_url(GOOGL), txt_url(GOOGL, ACCESSIONS[GOOGL])]


def test_ETF는_CIK가_있어도_요청하지_않는다(store):
    get = RecordedGet({})  # XLK(CIK 있음, 편입 ETF)를 요청하면 AssertionError로 실행이 멈춘다

    summary, _ = run(store, get, coverage=[c for c in COMPANIES if c.holdings_ticker])

    assert get.urls == []
    assert summary == QuarterlySummary(0, 0, 0, 0, 0, 0, (), (), (), ANY, ANY)
    assert store.coverage_sics() == {}  # SPY·XLK sic는 null


@pytest.mark.parametrize("sic", ["", "35A1", 3571, NO_SIC], ids=["펀드_빈_값", "형식_밖", "숫자_타입", "키_없음"])
def test_sic가_없거나_형식이_틀리면_채우지_않고_저장된_값을_지우지_않는다(store, sic):
    store.upsert_coverage(COMPANIES)
    store.set_coverage_sic(AAPL, "3571")  # 지난 실행이 채운 값
    get = RecordedGet(annual_day(**{submissions_url(AAPL): annual_submissions(AAPL, [(ACCESSIONS[AAPL], "10-K")], sic)}))

    summary, _ = run(store, get)

    assert store.coverage_sics()["AAPL"] == "3571"
    assert (summary.sic, summary.sic_missing, summary.new, summary.failures) == (2, 1, 3, ())  # 실패가 아니다, 10-K는 받는다


def stored_rows(admin):
    """sec_annual_report 행 전부(받은 시각 포함). 같은 입력이면 두 번째 실행 뒤에도 같아야 한다."""
    return admin.execute("select accession, cik, accepted_at, received_at, body from public.sec_annual_report order by accession").fetchall()


def test_같은_입력으로_두_번_실행하면_두_번째는_submissions만_받고_행이_그대로다(store, admin):
    run(store, RecordedGet(annual_day()))
    before = stored_rows(admin)
    get = RecordedGet(annual_day())

    summary, _ = run(store, get)

    assert get.urls == [submissions_url(AAPL), submissions_url(MSFT), submissions_url(GOOGL)]  # 전체 제출 파일(.txt) 0
    assert summary == QuarterlySummary(3, 0, 3, 0, 3, 0, (), (), (), ANY, ANY)
    assert stored_rows(admin) == before and len(before) == 3


NEW_AAPL = "0000320193-26-000090"


def test_새_10_K가_나온_회사만_받고_지난_10_K도_남긴다(store):
    run(store, RecordedGet(annual_day()))
    get = RecordedGet(annual_day(**{
        submissions_url(AAPL): annual_submissions(AAPL, [(NEW_AAPL, "10-K"), (ACCESSIONS[AAPL], "10-K")]),
        txt_url(AAPL, NEW_AAPL): annual_report_file(NEW_AAPL, accepted="20261030163000"),
    }))

    summary, _ = run(store, get)

    assert [u for u in get.urls if u.endswith(".txt")] == [txt_url(AAPL, NEW_AAPL)]
    assert (summary.new, summary.unchanged) == (1, 2)
    assert store.latest_annual_reports()[AAPL] == NEW_AAPL
    assert store.annual_report(ACCESSIONS[AAPL]) is not None  # 지난 10-K는 지우지 않는다
    assert store.annual_report(NEW_AAPL).accepted_at == datetime(2026, 10, 30, 16, 30, tzinfo=ET)


def test_최신_10_K는_recent의_첫_10_K이고_10_K_A·10_KT는_고르지_않는다(store):
    rows = [("0000320193-26-000005", "10-K/A"), ("0000320193-26-000004", "10-KT"), ("0000320193-26-000003", "10-K "),
            (ACCESSIONS[AAPL], "10-K"), ("0000320193-24-000123", "10-K")]
    get = RecordedGet(annual_day(**{submissions_url(AAPL): annual_submissions(AAPL, rows)}))

    run(store, get)

    assert get.urls[:2] == [submissions_url(AAPL), txt_url(AAPL, ACCESSIONS[AAPL])]  # 4번째 행
    assert store.latest_annual_reports()[AAPL] == ACCESSIONS[AAPL]


def test_recent에_10_K가_없는_회사는_실패가_아니라_없음으로_센다(store):
    get = RecordedGet(annual_day(**{submissions_url(AAPL): annual_submissions(AAPL, [("0000320193-26-000101", "8-K")])}))

    summary, _ = run(store, get)

    assert (summary.no_annual_report, summary.new, summary.failures) == (1, 2, ())
    assert txt_url(AAPL, "0000320193-26-000101") not in get.urls and AAPL not in store.latest_annual_reports()
    assert store.coverage_sics()["AAPL"] == "3571"  # sic는 채운다


def saved_body(store, main, extension=".htm"):
    """AAPL 10-K 주 문서를 main으로 바꿔 한 번 돌리고 저장된 본문."""
    accession = ACCESSIONS[AAPL]
    run(store, RecordedGet(annual_day(**{txt_url(AAPL, accession): annual_report_file(accession, main=main, extension=extension)})))
    return store.annual_report(accession).body


def test_저장되는_원문은_주_문서의_글자이고_첨부·그림·XBRL·숨김_글자는_없다(store):
    body = saved_body(store, MAIN_HTML)

    assert body.split("\n") == [
        "Item 1. Business 1",  # 목차 표 한 행 = 한 줄, 칸은 공백, &#160; → 공백
        "Item 1. Business",
        f"The Company designs smartphones and {BODY_CANARY} services.",
        "The Company sells through retail stores.",  # HTML 안의 줄바꿈은 줄을 나누지 않는다
        "Item 1A. Risk Factors",
    ]
    for absent in ("SubsidiaryCanary", "begin 644", "HiddenCanary", "TitleCanary", "<", "color"):
        assert absent not in body, absent


@pytest.mark.parametrize(
    "main, extension, body",
    [
        ("<p>Nul\x00Here</p>", ".htm", "Nul\ufffdHere"),  # Postgres text는 NUL을 받지 못한다(8-K와 같다)
        ("ITEM 1.  BUSINESS\n\n   The Company\tdesigns\xa0phones.  \n", ".txt", "ITEM 1. BUSINESS\nThe Company designs phones."),
    ],
    ids=["NUL", "텍스트_주_문서"],
)
def test_주_문서의_NUL은_대체_문자로_텍스트_주_문서는_원래_줄로_저장한다(store, main, extension, body):
    assert saved_body(store, main, extension) == body


def test_주_문서가_상한보다_길면_앞_ANNUAL_REPORT_BODY_MAX자만_저장한다(store):
    line = "x" * 99 + "\n"  # 줄바꿈 포함 100자
    body = saved_body(store, line * 10_010, ".txt")  # 1,000,999자

    assert len(body) == ANNUAL_REPORT_BODY_MAX == 1_000_000
    assert body == line * 10_000  # 앞부분 그대로, 꼬리만 잘린다


MSFT_TXT = txt_url(MSFT, ACCESSIONS[MSFT])


@pytest.mark.parametrize(
    "url, outcome, reason, requests, listed",
    [
        (submissions_url(MSFT), TransientSourceError("sec http 503"), FailureReason.RETRIES_EXHAUSTED, 4, False),
        (submissions_url(MSFT), b"not json", FailureReason.ERROR, 1, False),
        (submissions_url(MSFT), annual_submissions(AAPL, [(ACCESSIONS[MSFT], "10-K")]), FailureReason.ERROR, 1, False),
        (MSFT_TXT, b"<SEC-DOCUMENT>no header</SEC-DOCUMENT>", FailureReason.ERROR, 1, True),
        (MSFT_TXT, annual_report_file(ACCESSIONS[MSFT], main=None), FailureReason.ERROR, 1, True),  # 첨부(EX-21)만
        (MSFT_TXT, error_for_status("sec", 404), FailureReason.ERROR, 1, True),
        (MSFT_TXT, ValueError("bad"), FailureReason.UNEXPECTED, 1, True),
    ],
    ids=["submissions_503_4번", "submissions_모양", "다른_회사_cik", "헤더_없음", "주_문서_없음", "404", "예상_못_한_예외"],
)
def test_한_회사가_실패해도_나머지는_계속하고_실패는_CIK와_이유_코드로_남는다(store, url, outcome, reason, requests, listed):
    get = RecordedGet(annual_day(**{url: outcome}))

    summary, sleeps = run(store, get)

    error = "ValueError" if reason is FailureReason.UNEXPECTED else None
    assert summary.failures == (SourceFailure(Source.ANNUAL_REPORT, MSFT, reason, error),)
    assert get.urls.count(url) == requests
    assert sleeps == ([1.0, 2.0, 4.0] if requests == 4 else [])
    assert store.latest_annual_reports() == {AAPL: ACCESSIONS[AAPL], GOOGL: ACCESSIONS[GOOGL]}  # 다음 회사로 계속
    assert ("MSFT" in store.coverage_sics()) is listed  # 목록을 받았으면 10-K가 실패해도 sic는 쓴다
    assert summary.companies == summary.new + summary.unchanged + summary.no_annual_report + len(summary.failures) == 3
    assert quarterly_failed(summary) is True


class DayOpener:
    """edgar._OPENER 자리(test_edgar.FakeOpener의 주소별 판). 주소마다 정해진 바이트를 실제 http.client.HTTPResponse(Content-Length
    있음)로 답한다. gzipped면 압축해 Content-Encoding: gzip, cut 주소는 Content-Length보다 1바이트 짧게(중간에 끊긴 연결)."""

    def __init__(self, day, gzipped=False, cut=None):
        self.urls, self._day, self._gzipped, self._cut = [], day, gzipped, cut

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        body = gzip.compress(self._day[request.full_url]) if self._gzipped else self._day[request.full_url]
        head = f"HTTP/1.1 200 OK\r\n{'Content-Encoding: gzip' if self._gzipped else 'X-Plain: 1'}\r\nContent-Length: {len(body)}\r\n\r\n"
        raw = head.encode() + (body[:-1] if request.full_url == self._cut else body)
        response = http.client.HTTPResponse(SimpleNamespace(makefile=lambda mode: io.BytesIO(raw)))
        response.begin()
        return response


def quarterly_get(monkeypatch, opener, max_bytes):
    """opener 뒤의 실제 EdgarClient.get(분기 작업처럼 크기 상한 있음)."""
    monkeypatch.setattr(edgar, "_OPENER", opener)
    return EdgarClient(load_edgar_settings({"SEC_USER_AGENT": UA}), throttle=Throttle(0, sleep=pytest.fail), max_bytes=max_bytes).get


@pytest.mark.parametrize("gzipped", [False, True], ids=["받은_바이트", "gzip을_푼_바이트"])
def test_전체_제출_파일이_크기_상한을_넘으면_그_회사만_too_large로_실패하고_다시_받지_않는다(store, monkeypatch, gzipped):
    limit = max(len(body) for body in annual_day().values())  # 가장 큰 정상 응답이 딱 상한: 통과한다
    padding = " " * (limit + 1 - len(annual_report_file(ACCESSIONS[MSFT])))
    oversized = annual_report_file(ACCESSIONS[MSFT], main=MAIN_HTML + padding)
    assert len(oversized) == limit + 1 and len(gzip.compress(oversized)) < limit  # gzip이면 받은 바이트는 상한 안, 풀면 넘는다
    opener = DayOpener(annual_day(**{MSFT_TXT: oversized}), gzipped)

    summary, sleeps = run(store, quarterly_get(monkeypatch, opener, limit))

    assert summary.failures == (SourceFailure(Source.ANNUAL_REPORT, MSFT, FailureReason.TOO_LARGE),)
    assert opener.urls.count(MSFT_TXT) == 1 and sleeps == []  # 다시 받아도 같은 크기라 다시 시도하지 않는다
    assert store.latest_annual_reports() == {AAPL: ACCESSIONS[AAPL], GOOGL: ACCESSIONS[GOOGL]}  # 다음 회사로 계속
    assert "MSFT" in store.coverage_sics()  # 목록은 받았다
    assert quarterly_failed(summary) is True


def test_상한_안의_전체_제출_파일이_중간에_끊기면_짧은_원문을_저장하지_않고_다시_시도한다(store, monkeypatch):
    opener = DayOpener(annual_day(), cut=MSFT_TXT)

    summary, sleeps = run(store, quarterly_get(monkeypatch, opener, ANNUAL_REPORT_FILE_MAX))

    assert summary.failures == (SourceFailure(Source.ANNUAL_REPORT, MSFT, FailureReason.RETRIES_EXHAUSTED),)
    assert opener.urls.count(MSFT_TXT) == 4 and sleeps == [1.0, 2.0, 4.0]
    assert store.latest_annual_reports() == {AAPL: ACCESSIONS[AAPL], GOOGL: ACCESSIONS[GOOGL]}


class ContractStub:
    """AnnualReportSource 대역: 회사 셋 모두 정상 값, MSFT만 listing 또는 annual_report의 필드를 바꾼 값으로 돌려준다."""

    def __init__(self, listing=None, report=None):
        self._listing, self._report = listing or {}, report or {}

    def listing(self, cik):
        good = AnnualReportListing(ACCESSIONS[cik], SICS[cik])
        return dataclasses.replace(good, **self._listing) if cik == MSFT else good

    def annual_report(self, cik, accession):
        good = AnnualReport(accession, cik, datetime(2025, 10, 31, 18, 5, 2, tzinfo=ET), "Item 1. Business")
        return dataclasses.replace(good, **self._report) if cik == MSFT else good


@pytest.mark.parametrize(
    "listing, report",
    [
        ({"sic": "35A1"}, None),
        ({"accession": "0000950170-25-1"}, None),
        (None, {"accession": "0000950170-25-999999"}),
        (None, {"cik": AAPL}),
        (None, {"accepted_at": datetime(2025, 10, 31, 18, 5, 2)}),
        (None, {"body": ""}),
        (None, {"body": " \n "}),
        (None, {"body": "x" * (ANNUAL_REPORT_BODY_MAX + 1)}),
        (None, {"body": "Nul\x00Here"}),
    ],
    ids=["형식_밖_sic", "형식_밖_접수번호", "다른_접수번호", "다른_CIK", "시간대_없는_시각", "빈_본문", "공백_본문", "상한_초과_본문",
         "NUL_본문"],
)
def test_출처가_계약_밖_값을_주면_invalid_data로_그_회사만_실패한다(store, listing, report):
    store.upsert_coverage(COMPANIES)

    summary = run_quarterly(store, reports=ContractStub(listing, report), llm=NoCallLLM(), sleep=lambda _: None)

    assert summary.failures == (SourceFailure(Source.ANNUAL_REPORT, MSFT, FailureReason.INVALID_DATA),)
    assert MSFT not in store.latest_annual_reports() and len(store.latest_annual_reports()) == 2
    assert ("MSFT" in store.coverage_sics()) is (listing is None)  # 목록이 계약 밖이면 그 sic도 쓰지 않는다


def test_SEC가_403으로_막으면_그_뒤_회사는_요청하지_않고_전부_access_denied다(store):
    get = RecordedGet(annual_day(**{submissions_url(AAPL): error_for_status("sec", 403)}))

    summary, _ = run(store, get)

    assert get.urls == [submissions_url(AAPL)]  # 차단이 길어지지 않게 뒤 회사는 부르지 않는다
    assert summary.failures == tuple(SourceFailure(Source.ANNUAL_REPORT, cik, FailureReason.ACCESS_DENIED) for cik in (AAPL, MSFT, GOOGL))
    assert summary.access_denied == (Source.ANNUAL_REPORT,)
    assert store.latest_annual_reports() == {} and store.coverage_sics() == {}


def test_429_뒤_성공하면_저장되고_rate_limited에_남는다(store):
    get = RecordedGet(annual_day(**{MSFT_TXT: [error_for_status("sec", 429), annual_report_file(ACCESSIONS[MSFT])]}))

    summary, sleeps = run(store, get)

    assert (summary.new, summary.failures, summary.rate_limited) == (3, (), (Source.ANNUAL_REPORT,))
    assert sleeps == [1.0] and get.urls.count(MSFT_TXT) == 2
    assert quarterly_failed(summary) is False


def test_분기_작업은_아침_실행_잠금이_잡혀_있어도_끝까지_돌고_실행_기록·8_K_표·카드를_건드리지_않는다(settings, store, admin):
    day = datetime.now(ET).date()
    lock = "select count(*) from pg_locks where locktype = 'advisory' and classid = %s and objid = %s and granted"
    with connect(settings) as other, CardStore(other).run_lock(day):  # 같은 날 아침 실행이 도는 중
        summary, _ = run(store, RecordedGet(annual_day()))
        held = admin.execute(lock, (LOCK_CLASS, int(day.strftime("%Y%m%d")))).fetchone()[0]

    assert summary.new == 3
    assert held == 1  # 아침 실행은 잠금을 그대로 쥐고 있다
    counts = {t: admin.execute(f"select count(*) from public.{t}").fetchone()[0] for t in ("pipeline_run", "sec_filing", "stock_card")}
    assert counts == {"pipeline_run": 0, "sec_filing": 0, "stock_card": 0}


def test_분기_작업의_SEC_간격은_아침_실행과_겹쳐도_합이_초당_10회_미만이다():
    assert 1 / MIN_INTERVAL + 1 / QUARTERLY_INTERVAL == 9 < 10


def test_저장소는_회사별_최신_10_K_접수번호와_한_건의_원문을_돌려준다(store):
    older = AnnualReport("0000320193-24-000123", AAPL, datetime(2024, 11, 1, 18, 1, 14, tzinfo=ET), "2024 report")
    newer = AnnualReport(ACCESSIONS[AAPL], AAPL, datetime(2025, 10, 31, 18, 5, 2, tzinfo=ET), "2025 report")

    assert [store.save_annual_report(r) for r in (newer, older)] == [True, True]
    assert store.save_annual_report(dataclasses.replace(newer, body="changed")) is False  # 같은 접수번호는 건드리지 않는다

    assert store.latest_annual_reports() == {AAPL: ACCESSIONS[AAPL]}  # 저장 순서가 아니라 접수 시각
    assert store.annual_report(ACCESSIONS[AAPL]) == newer
    assert store.annual_report(ACCESSIONS[AAPL]).accepted_at.tzinfo is ET
    assert store.annual_report("0000320193-26-999999") is None



# 입구 3: 분기 작업 CLI 하위 프로세스. 비밀값 자리는 캐너리(전송 층을 바꿨으니 어디로도 가지 않는다)
BACKEND = Path(__file__).resolve().parent.parent
KEY_CANARY, UA_CANARY = "sk-ant-KeyCanary60", "M30 Canary uaCanary60@example.invalid"
UNREACHABLE_DB = "postgresql://postgres:DbCanary60@db.unreachable.invalid:5432/postgres"


def run_probe(settings, situation, *args, seed=True, env=None):
    """seed = 실행 전에 COMPANIES 커버 범위를 심는다. env = 덧붙이거나(None이면 뺄) 환경 변수. 셸의 진짜 비밀값은 넘기지 않는다.
    출력에 10-K 본문·회사 이름·연락처·키·DB 주소 캐너리가 없고, 운영 경로가 가짜 어댑터를 불러오지 않았는지 늘 확인한다."""
    if seed:
        with connect(settings) as conn:
            CardStore(conn).upsert_coverage(COMPANIES)
    env = {k: v for k, v in os.environ.items() if k not in ("SEC_USER_AGENT", "ANTHROPIC_API_KEY", "SUPABASE_DB_URL")} | {
        "SUPABASE_DB_URL": settings.database_url, "ANTHROPIC_API_KEY": KEY_CANARY, "SEC_USER_AGENT": UA_CANARY} | (env or {})
    env = {k: v for k, v in env.items() if v is not None}
    r = subprocess.run([sys.executable, "tests/quarterly_probe.py", situation, "--quarterly", *args],
                       cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    names = [c.name for c in COMPANIES]  # 커버 범위 회사 이름(연관 종목 요청의 filing_company)
    leaked = [c for c in (KEY_CANARY, UA_CANARY, BODY_CANARY, NAME_CANARY, EVIDENCE_CANARY, MENTION_CANARY, FACT_CANARY,
                          EXCERPT_CANARY, "DbCanary60", settings.database_url, *names) if c in out]
    assert not leaked
    assert out.endswith("fake_modules=[]\n")  # 실행한 분기 작업 경로 어디서도 가짜 어댑터를 불러오지 않았다
    return r.returncode, out.splitlines()[:-1]


QUIET_LINE = "quarterly companies=3 new=3 unchanged=0 no_annual_report=0 sic=3 sic_missing=0"
DENIED = ", ".join(f"annual_report/{cik}=access_denied" for cik in (AAPL, MSFT, GOOGL))
# 연관 종목 두 줄(#64). 탐침 10-K(MAIN_HTML)는 Item 1이 짧아 no_item1 = 저장된 10-K 수, LLM 0회. 같은 업종 회사가 없어 행 0
EXTRACT_LINE = ("relations: extracted=0 deferred=0 json_invalid=- no_item1={} no_section=0 truncated=0 invalid_mentions=0"
                " llm_calls=0/200 tokens=in:0,out:0,cache_read:0,cache_write:0")
TABLE_LINE = ("relations: tickers={0} changed=0 rows=0 own_10k=0(-) reverse_10k=0(-) sic=0(-) under3={0} mentions=0 matched=0"
              " unmatched=0 ambiguous=0 self=0")
# 알아두기 한 줄(#66). 탐침 10-K(MAIN_HTML)는 Item 1이 짧아 no_item1 = 저장된 10-K 수, LLM 0회, 풀 0
FACTS_LINE = ("quiet_facts: made=0 facts=0 deferred=0 json_invalid=- no_item1={0} empty=0 dropped=format:0,rules:0,check:0"
              " llm_calls=0/400 tokens=in:0,out:0,cache_read:0,cache_write:0 pools=0/{1}")
QUIET = [QUIET_LINE, EXTRACT_LINE.format(3), TABLE_LINE.format(4), FACTS_LINE.format(3, 4)]
# 연관 종목 상황: AAPL 10-K만 Item 1이 길다
RELATED_LINES = ["relations: extracted=1 deferred=0 json_invalid=- no_item1=2 no_section=0 truncated=0 invalid_mentions=1"
                 " llm_calls=1/200 tokens=in:1200,out:60,cache_read:900,cache_write:0",
                 "relations: tickers=4 changed=2 rows=2 own_10k=1(50%) reverse_10k=1(50%) sic=0(0%) under3=4 mentions=2"
                 " matched=1 unmatched=1 ambiguous=0 self=0"]


@pytest.mark.parametrize(
    "situation, seed, exit_code, lines",
    [
        ("quiet", True, 0, QUIET),
        ("failures", True, 1, ["!!! FAILED: failures=1 companies=3 !!!", "failed: annual_report/0000789019=retries_exhausted",
                               "quarterly companies=3 new=2 unchanged=0 no_annual_report=0 sic=3 sic_missing=0",
                               EXTRACT_LINE.format(2), TABLE_LINE.format(4), FACTS_LINE.format(2, 4)]),
        ("rate_limited", True, 1, ["!!! FAILED: failures=1 companies=3 !!!", "failed: annual_report/0000789019=retries_exhausted",
                                   "RATE LIMITED (429, retried): annual_report",
                                   "quarterly companies=3 new=2 unchanged=0 no_annual_report=0 sic=3 sic_missing=0",
                                   EXTRACT_LINE.format(2), TABLE_LINE.format(4), FACTS_LINE.format(2, 4)]),
        ("denied", True, 1, ["!!! FAILED: failures=3 companies=3 !!!", f"failed: {DENIED}", "ACCESS DENIED (not retried): annual_report",
                             "quarterly companies=3 new=0 unchanged=0 no_annual_report=0 sic=0 sic_missing=0",
                             EXTRACT_LINE.format(0), TABLE_LINE.format(4), FACTS_LINE.format(0, 4)]),
        ("too_large", True, 1, ["!!! FAILED: failures=1 companies=3 !!!", "failed: annual_report/0000789019=too_large",
                                "quarterly companies=3 new=2 unchanged=0 no_annual_report=0 sic=3 sic_missing=0",
                                EXTRACT_LINE.format(2), TABLE_LINE.format(4), FACTS_LINE.format(2, 4)]),
        ("empty", False, 1, ["!!! FAILED: failures=0 companies=0 !!!",  # 빈·잘못된 DB
                             "quarterly companies=0 new=0 unchanged=0 no_annual_report=0 sic=0 sic_missing=0",
                             EXTRACT_LINE.format(0), TABLE_LINE.format(0), FACTS_LINE.format(0, 0)]),
        # 연관 종목(#64): AAPL 10-K만 Item 1이 길다. 응답 = Microsoft(맞음) + 범위 밖 이름(캐너리). 이름·근거 문장은 찍지 않는다
        # 알아두기(#66): 사실 셋 중 순위 하나는 코드 검사, 하나는 판정에서 빠져 하나 저장. 사실 문장·발췌는 찍지 않는다
        ("relations", True, 0, [QUIET_LINE, *RELATED_LINES,
                                "quiet_facts: made=1 facts=1 deferred=0 json_invalid=- no_item1=2 empty=0 dropped=format:0,rules:1,check:1"
                                " llm_calls=2/400 tokens=in:2400,out:120,cache_read:1800,cache_write:0 pools=1/4"]),
        ("relations_broken", True, 0, [QUIET_LINE,  # 두 번 다 깨진 JSON은 실패가 아니다(다음 실행이 다시 부른다)
                                       f"relations: extracted=0 deferred=0 json_invalid={AAPL} no_item1=2 no_section=0 truncated=0"
                                       " invalid_mentions=0 llm_calls=2/200 tokens=in:2400,out:120,cache_read:1800,cache_write:0",
                                       TABLE_LINE.format(4),
                                       f"quiet_facts: made=0 facts=0 deferred=0 json_invalid={AAPL} no_item1=2 empty=0"
                                       " dropped=format:0,rules:0,check:0 llm_calls=2/400 tokens=in:2400,out:120,cache_read:1800,"
                                       "cache_write:0 pools=0/4"]),
        # 두 단계가 따로 부르고 따로 남긴다(연관 종목 → 알아두기 순)
        ("llm_denied", True, 1, ["!!! FAILED: failures=2 companies=3 !!!", f"failed: llm/{AAPL}=access_denied, llm/{AAPL}=access_denied",
                                 "ACCESS DENIED (not retried): llm", QUIET_LINE,
                                 "relations: extracted=0 deferred=0 json_invalid=- no_item1=2 no_section=0 truncated=0 invalid_mentions=0"
                                 " llm_calls=1/200 tokens=in:0,out:0,cache_read:0,cache_write:0", TABLE_LINE.format(4),
                                 FACTS_LINE.format(2, 4).replace("llm_calls=0/", "llm_calls=1/")]),
        ("quiet_denied", True, 1, ["!!! FAILED: failures=1 companies=3 !!!", f"failed: llm/{AAPL}=access_denied",
                                   "ACCESS DENIED (not retried): llm", QUIET_LINE, *RELATED_LINES,
                                   FACTS_LINE.format(2, 4).replace("llm_calls=0/", "llm_calls=1/")]),
    ],
    ids=["정상", "503_4번", "429_4번", "SEC_403", "크기_상한_초과", "커버_범위_0", "연관_종목", "연관_종목_JSON_깨짐", "LLM_401",
         "알아두기_LLM_401"],
)
def test_분기_작업_CLI는_코드·건수·CIK만_찍고_실패한_실행이면_1로_끝난다(settings, admin, situation, seed, exit_code, lines):
    assert run_probe(settings, situation, seed=seed) == (exit_code, lines)


def test_분기_작업_CLI는_10_K_원문·회사_이름·연락처·DB_주소를_찍지_않는다(settings, store):
    assert run_probe(settings, "quiet") == (0, QUIET)  # 캐너리 검사는 run_probe
    assert BODY_CANARY in store.annual_report(ACCESSIONS[AAPL]).body  # 본문 캐너리가 실제로 지나간 실행이다

    # 예외 메시지에 연락처. 앞 실행이 받은 10-K는 다시 받지 않는다
    assert run_probe(settings, "crash") == (1, [
        "!!! FAILED: failures=1 companies=3 !!!", "failed: annual_report/0000789019=unexpected:ValueError",
        "quarterly companies=3 new=0 unchanged=2 no_annual_report=0 sic=2 sic_missing=0", EXTRACT_LINE.format(3),
        TABLE_LINE.format(4), FACTS_LINE.format(3, 4)])


def test_분기_작업_CLI는_연관_종목의_회사_이름·근거_문장·LLM_응답을_찍지_않는다(settings, store):
    assert run_probe(settings, "relations")[0] == 0  # 캐너리·회사 이름 검사는 run_probe
    # 두 캐너리가 실제로 지나간 실행이다: 근거 문장과 범위 밖 이름이 저장됐다
    [report] = store.latest_mentions().values()
    assert EVIDENCE_CANARY in report.mentions[0].evidence and MENTION_CANARY in {m.name for m in report.mentions}
    assert [r.related_ticker for r in store.list_relations()["AAPL"]] == ["MSFT"]


def test_분기_작업_CLI는_알아두기_사실_문장·발췌를_찍지_않는다(settings, store, admin):
    assert run_probe(settings, "relations")[0] == 0  # 캐너리·회사 이름 검사는 run_probe
    # 사실 문장 캐너리가 실제로 지나간 실행이다(발췌 캐너리는 그 10-K Item 1 안에 있다)
    assert admin.execute("select ticker, seq, text from public.quiet_fact").fetchall() == [("AAPL", 1, f"Apple makes {FACT_CANARY} phones")]
    assert EXCERPT_CANARY in store.annual_report(ACCESSIONS[AAPL]).body


def test_분기_작업_중_DB_오류는_예외_이름만_찍고_1로_끝난다(settings, admin):
    assert run_probe(settings, "db_error") == (1, ["RUN FAILED: OperationalError"])


@pytest.mark.parametrize("missing", ["SEC_USER_AGENT", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY"])
def test_분기_작업_CLI는_설정이_없으면_DB·SEC·LLM에_닿기_전에_변수_이름만_찍고_2로_끝난다(settings, missing):
    env = {"SUPABASE_DB_URL": UNREACHABLE_DB, missing: None}  # 연결을 시도하면 host_not_found(exit 1)로 끝났을 주소

    assert run_probe(settings, "quiet", seed=False, env=env) == (2, [f"{missing} is not set"])


@pytest.mark.parametrize("args", [["2026-10-16"], ["--quality"], ["--production"]], ids=["거래일", "quality", "production"])
def test_분기_작업_CLI는_거래일·quality·다른_모드를_받지_않는다(settings, args):
    exit_code, _ = run_probe(settings, "quiet", *args, seed=False)

    assert exit_code == 2
