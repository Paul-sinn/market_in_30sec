"""SEC EDGAR 실제 어댑터(#19). 입구 1(아침 파이프라인 + EdgarFilingSource + 기록용 get) + 경계 직접 테스트. 네트워크 없이 돈다.

tests/edgar_responses/의 파일은 실제 녹화가 아니다. SEC 공개 문서를 기억에 기대어 손으로 만든 모양이다(스펙 #19 가정 A1~A5).
live(tests/test_edgar_live.py)가 실제 응답과 맞는지 확인하고, 틀리면 이 파일들과 파싱을 함께 고친다.
- A1(2026-10-21 live로 확인·수정): 실제 접수 시각은 전체 제출 파일 SEC-HEADER의 <ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS이고 동부
  벽시계다. submissions의 acceptanceDateTime은 그 값 + 정확히 8시간에 Z(20260730163028 → "2026-07-31T00:30:28.000Z")라 동부도
  진짜 UTC도 아니다 → 후보 고르기에만 쓴다(기간 앞뒤 12시간). fixture의 acceptanceDateTime은 이 관측 모양이다
- A2: submissions JSON = 맨 위 cik(앞 0 없는 문자열), filings.recent의 같은 길이 열 배열
  accessionNumber·form·acceptanceDateTime·items("2.02,9.01", 없으면 "")·reportDate("YYYY-MM-DD", 없으면 "")
- A3: company_tickers.json = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, …} (cik_str는 정수)
- A4: 전체 제출 파일(.txt) = SEC-HEADER + <DOCUMENT> 블록마다 <TYPE>·<FILENAME>·<TEXT>…</TEXT>. 첫 문서 TYPE은 서식 이름,
  iXBRL 본문은 <TEXT> 안에서 <XBRL>로 감싸여 있다. 그림(GRAPHIC)·PDF는 uuencode
- A5: 세 주소는 리다이렉트하지 않고, Accept-Encoding: gzip이면 응답은 gzip 또는 무압축
NUL·잘못된 UTF-8 바이트는 파일에 넣지 않고 테스트가 [NUL]·[0xFF] 자리를 바이트로 바꿔 넣는다."""

import gzip
import http.client
import io
import json
import urllib.error
import urllib.request
import urllib.response
from datetime import date, datetime
from decimal import Decimal
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from m30.adapters import (
    AccessDeniedError,
    RateLimitedError,
    Source,
    SourceError,
    TransientSourceError,
    edgar,
    error_for_status,
)
from m30.adapters.edgar import SUBMISSIONS_URL, TICKERS_URL, EdgarClient, EdgarFilingSource, Throttle, ticker_ciks
from m30.adapters.fake import (
    FailurePlan,
    FakeEventSource,
    FakeHoldingsSource,
    FakeIndicatorSource,
    FakeLLM,
    FakeMarketNewsSource,
    FakePriceSource,
    Scenario,
)
from m30.config import ET, ConfigError, load_edgar_settings
from m30.experiment import experiment_coverage
from m30.models import Coverage, LineStatus
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.pipeline.morning import MorningPipeline

UA = "M30 Canary ua-canary-Q7@example.invalid"  # 개인 정보 없는 테스트 값
RESPONSES = Path(__file__).resolve().parent / "edgar_responses"


class RecordedGet:
    """EdgarClient.get 자리. 주소 → fixture 바이트(또는 예외). 부른 주소를 순서대로 남긴다. 모르는 주소면 AssertionError:
    받으면 안 되는 파일을 받으려 하면 실행이 크게 멈춘다. 값이 목록이면 앞에서부터 하나씩 쓰고 마지막은 계속 쓴다."""

    def __init__(self, responses):
        self.urls, self._responses = [], {url: list(v) if isinstance(v, list) else [v] for url, v in responses.items()}

    def __call__(self, url):
        self.urls.append(url)
        if url not in self._responses:
            raise AssertionError(f"unexpected SEC request {url}")
        outcomes = self._responses[url]
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def recorded(name):
    return (RESPONSES / name).read_bytes()


def submission_file(accession, accepted, item="8.01 Other Events"):
    """손으로 만든 최소 전체 제출 파일: SEC-HEADER(접수 시각 = 동부 벽시계 YYYYMMDDHHMMSS) + 8-K 본문 하나."""
    return (
        f"<SEC-DOCUMENT>{accession}.txt : {accepted[:8]}\n<SEC-HEADER>{accession}.hdr.sgml : {accepted[:8]}\n"
        f"<ACCEPTANCE-DATETIME>{accepted}\nACCESSION NUMBER:\t\t{accession}\nCONFORMED SUBMISSION TYPE:\t8-K\n</SEC-HEADER>\n"
        f"<DOCUMENT>\n<TYPE>8-K\n<SEQUENCE>1\n<FILENAME>d8k.htm\n<DESCRIPTION>8-K\n<TEXT>\n"
        f"<html><body><p>Item {item}.</p></body></html>\n</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n"
    ).encode()


def test_SEC_User_Agent는_SEC_USER_AGENT_환경_변수에서만_읽는다():
    assert load_edgar_settings({"SEC_USER_AGENT": UA}).user_agent == UA
    assert UA not in repr(load_edgar_settings({"SEC_USER_AGENT": UA}))  # 설정을 찍어도 연락처가 나오지 않는다


@pytest.mark.parametrize(
    "env, message",
    [
        ({}, "SEC_USER_AGENT is not set"),
        ({"SEC_USER_AGENT": ""}, "SEC_USER_AGENT is not set"),
        ({"SEC_USER_AGENT": "name only"}, "SEC_USER_AGENT must be one line of printable ASCII with a contact email"),
        ({"SEC_USER_AGENT": "a@b\r\nX: y"}, "SEC_USER_AGENT must be one line of printable ASCII with a contact email"),
        ({"SEC_USER_AGENT": "한글@x"}, "SEC_USER_AGENT must be one line of printable ASCII with a contact email"),
    ],
    ids=["missing", "empty", "no_email", "newline", "non_ascii"],
)
def test_SEC_User_Agent가_없거나_한_줄_ASCII_연락처가_아니면_값을_빼고_설정_오류다(env, message):
    with pytest.raises(ConfigError) as raised:
        load_edgar_settings(env)
    assert str(raised.value) == message  # 값 자체는 메시지에 없다(http.client는 잘못된 헤더 값을 메시지에 넣는다)


class FakeOpener:
    """edgar._OPENER 자리. 받은 Request를 남기고 정해진 본문·Content-Encoding으로 답한다."""

    def __init__(self, body=b"{}", encoding=None, error=None):
        self.requests, self._body, self._encoding, self._error = [], body, encoding, error

    def open(self, request, timeout):
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        headers = Message()
        if self._encoding is not None:
            headers["Content-Encoding"] = self._encoding
        return urllib.response.addinfourl(io.BytesIO(self._body), headers, request.full_url, 200)


def client(monkeypatch, **opener):
    fake = FakeOpener(**opener)
    monkeypatch.setattr(edgar, "_OPENER", fake)
    return EdgarClient(load_edgar_settings({"SEC_USER_AGENT": UA}), throttle=Throttle(0, sleep=pytest.fail)), fake


AAPL_SUBMISSIONS = SUBMISSIONS_URL.format(cik="0000320193")


def test_SEC_요청은_SEC_USER_AGENT를_User_Agent로_보내고_gzip을_받겠다고_알린다(monkeypatch):
    sec, opener = client(monkeypatch, body=b'{"cik": "320193"}')

    assert sec.get(AAPL_SUBMISSIONS) == b'{"cik": "320193"}'
    [request] = opener.requests
    assert request.full_url == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert request.get_header("User-agent") == UA
    assert request.get_header("Accept-encoding") == "gzip"


@pytest.mark.parametrize("encoding", ["gzip", "identity", None])
def test_SEC_응답은_gzip이면_풀고_무압축이면_그대로_돌려준다(monkeypatch, encoding):
    body = b'{"cik": "320193"}'
    sec, _ = client(monkeypatch, body=gzip.compress(body) if encoding == "gzip" else body, encoding=encoding)

    assert sec.get(AAPL_SUBMISSIONS) == body


def test_SEC_응답이_gzip·무압축이_아닌_인코딩이면_재시도하지_않는_실패다(monkeypatch):
    sec, _ = client(monkeypatch, body=b"\x00", encoding="br")

    with pytest.raises(SourceError) as raised:
        sec.get(AAPL_SUBMISSIONS)
    assert type(raised.value) is SourceError
    assert str(raised.value) == "sec response encoding"


@pytest.mark.parametrize(
    "url",
    [
        "http://data.sec.gov/submissions/CIK0000320193.json",  # 평문
        "https://example.com/submissions/CIK0000320193.json",  # SEC가 아닌 호스트
        "https://data.sec.gov:8443/submissions/CIK0000320193.json",  # 포트가 붙음
        "https://user@data.sec.gov/submissions/CIK0000320193.json",  # 사용자 정보가 붙음
        "https://data.sec.gov.example.com/submissions/CIK0000320193.json",  # SEC 이름으로 시작하는 남의 호스트
    ],
)
def test_SEC_User_Agent는_HTTPS_SEC_호스트_기본_포트로만_보내고_아니면_요청_전에_멈춘다(monkeypatch, url):
    sec, opener = client(monkeypatch)

    with pytest.raises(ValueError):
        sec.get(url)
    assert opener.requests == []  # 연락처가 든 요청을 만들지도 않았다


def test_SEC_리다이렉트는_따라가지_않는다():
    request = urllib.request.Request("https://www.sec.gov/files/company_tickers.json")
    assert edgar._NoRedirect().redirect_request(request, None, 301, "Moved", Message(), "https://example.com/") is None
    assert any(isinstance(h, edgar._NoRedirect) for h in edgar._OPENER.handlers)  # 실제로 쓰는 opener에 끼워져 있다



def http_error(status):
    return urllib.error.HTTPError(AAPL_SUBMISSIONS, status, "x", Message(), io.BytesIO(b"body"))


@pytest.mark.parametrize(
    "opener, error, message",
    [
        ({"error": http_error(403)}, AccessDeniedError, "sec http 403"),  # SEC 차단: 다시 시도하지 않는다
        ({"error": http_error(429)}, RateLimitedError, "sec http 429"),
        ({"error": http_error(503)}, TransientSourceError, "sec http 503"),
        ({"error": http_error(301)}, SourceError, "sec http 301"),  # 리다이렉트를 따라가지 않은 결과
        ({"error": http_error(404)}, SourceError, "sec http 404"),
        ({"error": TimeoutError()}, TransientSourceError, "sec timeout"),
        ({"error": urllib.error.URLError(ConnectionRefusedError())}, TransientSourceError, "sec connection failed"),
        ({"error": http.client.IncompleteRead(b"")}, TransientSourceError, "sec connection failed"),
        ({"body": gzip.compress(b"{}")[:-4], "encoding": "gzip"}, TransientSourceError, "sec connection failed"),  # 끊긴 gzip
        ({"body": b"\x1f\x8b\x08\x00garbage", "encoding": "gzip"}, TransientSourceError, "sec connection failed"),  # 깨진 gzip
    ],
    ids=["403", "429", "503", "301", "404", "timeout", "refused", "incomplete", "gzip_cut", "gzip_broken"],
)
def test_SEC_요청_실패는_상태만_담은_출처_실패로_바뀐다(monkeypatch, opener, error, message):
    sec, _ = client(monkeypatch, **opener)

    with pytest.raises(SourceError) as raised:
        sec.get(AAPL_SUBMISSIONS)
    assert type(raised.value) is error
    assert str(raised.value) == message  # 주소·헤더·응답 본문 없음
    assert raised.value.__suppress_context__  # from None: urllib 프레임(요청 헤더)을 traceback에 잇지 않는다


class FakeClock:
    """가짜 시계: sleep이 시각을 민다. 실제로 기다리지 않는다."""

    def __init__(self):
        self.now, self.sleeps = 100.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_SEC_요청은_시작_간격이_0_125초_이상이라_어느_1초에도_8번_이하다():
    clock = FakeClock()
    throttle = Throttle(edgar.MIN_INTERVAL, clock=clock, sleep=clock.sleep)
    starts = []
    for _ in range(20):  # 사이에 시간이 흐르지 않는 연속 요청
        throttle.wait()
        starts.append(clock.now)

    assert clock.sleeps[0] == 0.125 and len(clock.sleeps) == 19  # 첫 요청은 기다리지 않는다
    assert all(b - a >= 0.125 for a, b in zip(starts, starts[1:]))
    assert max(sum(s <= t < s + 1 for t in starts) for s in starts) == 8  # SEC 상한 초당 10회 미만


def test_SEC_요청_사이에_이미_간격만큼_지났으면_기다리지_않는다():
    clock = FakeClock()
    throttle = Throttle(0.125, clock=clock, sleep=clock.sleep)
    throttle.wait()
    clock.now += 0.05
    throttle.wait()  # 0.075초 더 기다린다
    clock.now += 0.2
    throttle.wait()  # 이미 지났다

    assert clock.sleeps == [pytest.approx(0.075)]


def test_SEC_클라이언트는_요청마다_간격_조절을_거치고_요청_전에_멈춘_주소는_간격을_쓰지_않는다(monkeypatch):
    clock = FakeClock()
    opener = FakeOpener()
    monkeypatch.setattr(edgar, "_OPENER", opener)
    sec = EdgarClient(load_edgar_settings({"SEC_USER_AGENT": UA}), throttle=Throttle(0.125, clock=clock, sleep=clock.sleep))

    sec.get(AAPL_SUBMISSIONS)
    with pytest.raises(ValueError):
        sec.get("https://example.com/x")  # 호스트 검사에서 멈춤: 기다리지도 시작 시각을 적지도 않는다
    sec.get(AAPL_SUBMISSIONS)
    sec.get(AAPL_SUBMISSIONS)

    assert clock.sleeps == [0.125, 0.125]  # 실제로 보낸 요청 3개 사이마다
    assert len(opener.requests) == 3


def test_SEC_클라이언트는_기본으로_프로세스에_하나인_간격_조절을_같이_쓴다():
    settings = load_edgar_settings({"SEC_USER_AGENT": UA})
    assert EdgarClient(settings)._throttle is EdgarClient(settings)._throttle is edgar.SEC_THROTTLE
    assert edgar.SEC_THROTTLE._interval == 0.125



def test_CIK_티커_매핑은_SEC_공식_티커_목록에서_10자리_CIK로_만든다():
    get = RecordedGet({TICKERS_URL: recorded("company_tickers.json")})

    ciks = ticker_ciks(get)

    assert get.urls == ["https://www.sec.gov/files/company_tickers.json"]
    assert ciks["AAPL"] == "0000320193"  # 앞을 0으로 채운다
    assert ciks["GOOGL"] == ciks["GOOG"] == "0001652044"  # 한 회사에 티커 둘
    assert ciks["JPM"] == "0000019617"
    assert len(ciks) == 13


def test_같은_티커가_서로_다른_CIK로_나오면_그_티커만_빼고_소문자_티커는_대문자로_쓴다():
    listing = {"0": {"cik_str": 1, "ticker": "X"}, "1": {"cik_str": 2, "ticker": "X"}, "2": {"cik_str": 3, "ticker": "y"},
               "3": {"cik_str": 0, "ticker": "ZERO"}, "4": {"cik_str": 10**10, "ticker": "HUGE"}, "5": {"cik_str": 4, "ticker": "Z"}}

    assert ticker_ciks(RecordedGet({TICKERS_URL: json.dumps(listing).encode()})) == {"Y": "0000000003", "Z": "0000000004"}


@pytest.mark.parametrize("body", [b"[]", b"not json", b'{"0": {"ticker": "AAPL"}}', b'{"0": "AAPL"}', b'{"0": {"cik_str": 1, "ticker": 5}}'],
                         ids=["list", "not_json", "no_cik", "not_object", "ticker_not_text"])
def test_티커_목록_모양이_다르면_재시도하지_않는_출처_실패다(body):
    with pytest.raises(SourceError) as raised:
        ticker_ciks(RecordedGet({TICKERS_URL: body}))
    assert type(raised.value) is SourceError
    assert str(raised.value) == "sec tickers shape"



def test_실험_종목_15개는_회사_11개에_공식_목록의_CIK를_채우고_ETF_4개는_CIK_없이_둔다():
    rows = experiment_coverage(ticker_ciks(RecordedGet({TICKERS_URL: recorded("company_tickers.json")})))

    assert [(r.ticker, r.cik) for r in rows] == [
        ("AAPL", "0000320193"), ("MSFT", "0000789019"), ("NVDA", "0001045810"), ("AMZN", "0001018724"),
        ("GOOGL", "0001652044"), ("META", "0001326801"), ("TSLA", "0001318605"), ("JPM", "0000019617"),
        ("XOM", "0000034088"), ("KO", "0000021344"), ("PFE", "0000078003"),
        ("SPY", None), ("QQQ", None), ("TQQQ", None), ("SCHD", None),  # 목록에 SPY가 있어도 비운다 → Not covered yet
    ]
    assert {r.ticker: r.leverage for r in rows if r.leverage is not None} == {"TQQQ": Decimal("3")}
    # 카드 머리글 이름 = 법인 꼬리를 뗀 흔한 이름(copy-reviewer 교체 목록). SEC 대문자 정형명(MICROSOFT CORP)은 쓰지 않는다
    assert [r.name for r in rows] == [
        "Apple", "Microsoft", "NVIDIA", "Amazon", "Alphabet", "Meta", "Tesla", "JPMorgan Chase", "Exxon Mobil", "Coca-Cola",
        "Pfizer", "SPDR S&P 500 ETF", "Invesco QQQ", "ProShares UltraPro QQQ", "Schwab U.S. Dividend Equity ETF",
    ]


def test_실험_회사가_티커_목록에_없으면_지난_CIK를_덮지_않게_출처_실패다():
    ciks = ticker_ciks(RecordedGet({TICKERS_URL: recorded("company_tickers.json")}))
    del ciks["GOOGL"], ciks["KO"]

    with pytest.raises(SourceError) as raised:
        experiment_coverage(ciks)
    assert str(raised.value) == "sec ticker list has no GOOGL, KO"



# 입구 1: 아침 파이프라인 + EdgarFilingSource(기록용 get). 거래일 FRI, 공시 기간 [10-15 04:00, 10-16 04:00) ET
FRI = date(2026, 10, 16)
AAPL_CIK, GOOGL_CIK = "0000320193", "0001652044"
COVERAGE = [Coverage("AAPL", "Apple Inc.", cik=AAPL_CIK), Coverage("GOOGL", "Alphabet Inc.", cik=GOOGL_CIK),
            Coverage("GOOG", "Alphabet Inc.", cik=GOOGL_CIK), Coverage("SPY", "SPDR S&P 500 ETF Trust")]
GOOGL_SUBMISSIONS = SUBMISSIONS_URL.format(cik=GOOGL_CIK)


def txt_url(n):
    return f"https://www.sec.gov/Archives/edgar/data/320193/000032019326000{n}/0000320193-26-000{n}.txt"


def bad_bytes(data):
    """[NUL]·[0xFF] 자리에 Postgres text가 못 받는 NUL과 UTF-8이 아닌 바이트를 넣는다."""
    return data.replace(b"[NUL]", b"\x00").replace(b"[0xFF]", b"\xff")


def sec_responses(**changes):
    return {
        AAPL_SUBMISSIONS: recorded("CIK0000320193.json"),
        GOOGL_SUBMISSIONS: recorded("CIK0001652044.json"),
        txt_url(100): bad_bytes(recorded("0000320193-26-000100.txt")),
        txt_url(101): recorded("0000320193-26-000101.txt"),
        txt_url(102): recorded("0000320193-26-000102.txt"),
        # submissions 시각으로는 후보(기간 앞뒤 12시간)지만 헤더 시각으로는 기간 밖: 받고 버린다
        txt_url(104): submission_file("0000320193-26-000104", "20261015035959"),  # 시작 1초 전
        txt_url(105): submission_file("0000320193-26-000105", "20261016040000", "7.01 Regulation FD Disclosure"),  # = 끝
    } | changes


def with_rows(*rows):
    """AAPL submissions의 filings.recent를 rows로 바꾼다. row = (accessionNumber, form, acceptanceDateTime, items, reportDate)."""
    data = json.loads(recorded("CIK0000320193.json"))
    data["filings"]["recent"] = {name: [row[i] for row in rows] for i, name in enumerate(edgar.RECENT_COLUMNS)}
    return json.dumps(data).encode()


def run_edgar(store, get, day=FRI):
    """공시만 EDGAR 어댑터, 나머지는 빈 가짜. LLM은 실패시켜 분류 요청 하나만 남긴다(첫 번째 줄·판정은 부르지 않는다)."""
    scenario = Scenario(coverage=COVERAGE, prices={}, failures={(Source.LLM, None): FailurePlan("error")})
    store.upsert_coverage(scenario.coverage)
    store.add_default_tickers(day, [c.ticker for c in scenario.coverage])  # 유저 없음 → 시나리오 커버 범위 전체가 대상
    llm, sleeps = FakeLLM(scenario), []
    summary = MorningPipeline(
        prices=FakePriceSource(scenario),
        events=FakeEventSource(scenario),
        filings=EdgarFilingSource(get),
        indicators=FakeIndicatorSource(scenario),
        holdings=FakeHoldingsSource(scenario),
        market_news=FakeMarketNewsSource(scenario),
        llm=llm,
        store=store,
        sleep=sleeps.append,
    ).run(day)
    return SimpleNamespace(summary=summary, sleeps=sleeps, llm=llm)


def saved(admin, column):
    return dict(admin.execute(f"select accession, {column} from public.sec_filing order by accession").fetchall())


def test_후보는_submissions_시각으로_넓게_고르고_접수_시각은_SEC_HEADER의_동부_시각으로_정확히_거른다(store, admin):
    get = RecordedGet(sec_responses())

    run_edgar(store, get)

    # 후보 = submissions 시각이 기간 앞뒤 12시간 안인 8-K·8-K/A(서식 4·8-K12B는 받지 않는다). CIK마다 submissions 한 번
    assert get.urls == [AAPL_SUBMISSIONS, txt_url(105), txt_url(102), txt_url(101), txt_url(100), txt_url(104), GOOGL_SUBMISSIONS]
    assert saved(admin, "accepted_at") == {  # 헤더 시각으로 다시 거른 결과. 104(03:59:59)·105(끝 04:00)는 버렸다
        "0000320193-26-000100": datetime(2026, 10, 15, 4, 0, tzinfo=ET),  # = 기간 시작, 포함
        "0000320193-26-000101": datetime(2026, 10, 15, 16, 30, 12, tzinfo=ET),  # JSON "2026-10-16T00:30:12.000Z"가 아니다
        "0000320193-26-000102": datetime(2026, 10, 15, 17, 5, tzinfo=ET),
    }


def test_넓힌_후보_창에만_든_공시는_쓸_문서가_없어도_CIK를_지연시키지_않는다(store):
    # 104(헤더 03:59:59)가 그림·PDF뿐이어도 기간 밖이라 버린다. 남기면 빈 원본이 그 CIK 전체를 invalid_data로 만든다
    pdf_only = submission_file("0000320193-26-000104", "20261015035959").replace(b"<FILENAME>d8k.htm", b"<FILENAME>d8k.pdf")

    ran = run_edgar(store, RecordedGet(sec_responses(**{txt_url(104): pdf_only})))

    assert [f for f in ran.summary.failures if f.source is Source.SEC_FILINGS] == []
    assert sorted(store.list_raw_filings(FRI)) == ["0000320193-26-000100", "0000320193-26-000101", "0000320193-26-000102"]


@pytest.mark.parametrize(
    "listed, header, kept",
    [
        # submissions 시각 = 기간 시작 - 12시간(10-14 16:00 EDT)
        ("2026-10-14T20:00:00.000Z", "20261015040000", datetime(2026, 10, 15, 4, 0, tzinfo=ET)),
        ("2026-10-14T19:59:59.000Z", "20261015040000", None),  # 그보다 1초 앞: 후보 아님
        # 기간 끝 + 12시간(10-16 16:00 EDT) 1초 전
        ("2026-10-16T19:59:59.000Z", "20261016035959", datetime(2026, 10, 16, 3, 59, 59, tzinfo=ET)),
        ("2026-10-16T20:00:00.000Z", "20261016035959", None),  # = 기간 끝 + 12시간: 후보 아님
    ],
    ids=["start_margin", "before_margin", "end_margin", "after_margin"],
)
def test_후보는_submissions_시각이_기간_앞뒤_12시간_안인_공시다(store, admin, listed, header, kept):
    row = ("0000320193-26-000108", "8-K", listed, "8.01", "")
    get = RecordedGet(sec_responses(**{
        AAPL_SUBMISSIONS: with_rows(row), txt_url(108): submission_file("0000320193-26-000108", header),
    }))

    run_edgar(store, get)

    assert (txt_url(108) in get.urls) is (kept is not None)
    assert saved(admin, "accepted_at") == ({} if kept is None else {"0000320193-26-000108": kept})


def test_동부_20시_뒤_저녁_공시는_다음_거래일_카드에_들어간다(store, admin):
    # 목요일 20:30 ET 접수. submissions 값(금요일 04:30에 Z)을 동부로 읽으면 금요일 카드 기간 밖이라 월요일 카드로 밀린다
    evening = ("0000320193-26-000107", "8-K", "2026-10-16T04:30:00.000Z", "8.01", "")
    get = RecordedGet(sec_responses(**{
        AAPL_SUBMISSIONS: with_rows(evening),
        txt_url(107): submission_file("0000320193-26-000107", "20261015203000"),
    }))

    run_edgar(store, get)

    assert saved(admin, "accepted_at") == {"0000320193-26-000107": datetime(2026, 10, 15, 20, 30, tzinfo=ET)}
    assert saved(admin, "trading_day") == {"0000320193-26-000107": FRI}


@pytest.mark.parametrize(
    "day, rows, kept",
    [
        (  # 서머타임 끝(11-01): 기간 [금 10-30 04:00 EDT, 월 11-02 04:00 EST)
            date(2026, 11, 2),
            [(201, "20261030035959", "2026-10-30T11:59:59.000Z"), (202, "20261030040000", "2026-10-30T12:00:00.000Z"),
             (203, "20261102035959", "2026-11-02T11:59:59.000Z"), (204, "20261102040000", "2026-11-02T12:00:00.000Z")],
            {"0000320193-26-000202": datetime(2026, 10, 30, 4, 0, tzinfo=ET),  # UTC-4
             "0000320193-26-000203": datetime(2026, 11, 2, 3, 59, 59, tzinfo=ET)},  # UTC-5
        ),
        (  # 서머타임 시작(03-08): 기간 [금 03-06 04:00 EST, 월 03-09 04:00 EDT)
            date(2026, 3, 9),
            [(301, "20260306035959", "2026-03-06T11:59:59.000Z"), (302, "20260306040000", "2026-03-06T12:00:00.000Z"),
             (303, "20260309035959", "2026-03-09T11:59:59.000Z"), (304, "20260309040000", "2026-03-09T12:00:00.000Z")],
            {"0000320193-26-000302": datetime(2026, 3, 6, 4, 0, tzinfo=ET),  # UTC-5
             "0000320193-26-000303": datetime(2026, 3, 9, 3, 59, 59, tzinfo=ET)},  # UTC-4
        ),
    ],
    ids=["dst_ends", "dst_starts"],
)
def test_서머타임이_바뀌는_주말에도_04시_경계는_동부_벽시계로_정확하다(store, admin, day, rows, kept):
    responses = {AAPL_SUBMISSIONS: with_rows(*[(f"0000320193-26-000{n}", "8-K", listed, "8.01", "") for n, _, listed in rows])}
    responses |= {txt_url(n): submission_file(f"0000320193-26-000{n}", header) for n, header, _ in rows}
    get = RecordedGet(sec_responses(**responses))

    run_edgar(store, get, day)

    assert get.urls.count(txt_url(rows[0][0])) == 1 and get.urls.count(txt_url(rows[-1][0])) == 1  # 경계 밖 둘도 후보로 받았다
    assert saved(admin, "accepted_at") == kept


def test_보고_기준일은_EDGAR_reportDate이고_비어_있으면_없음이다(store, admin):
    run_edgar(store, RecordedGet(sec_responses()))

    # 8-K/A(102)가 10-01 원래 공시를 정정한다는 연결 고리(#7 정정 공시 보류)
    assert saved(admin, "report_date") == {
        "0000320193-26-000100": None, "0000320193-26-000101": date(2026, 10, 15), "0000320193-26-000102": date(2026, 10, 1),
    }


def test_같은_CIK의_티커_둘은_submissions를_한_번_받고_CIK_없는_ETF는_미지원이다(store):
    get = RecordedGet(sec_responses())

    ran = run_edgar(store, get)

    assert get.urls.count(GOOGL_SUBMISSIONS) == 1
    assert {t: n.status for t, n in ran.summary.news.items()} == {
        "AAPL": LineStatus.DELAYED,  # 공시는 있는데 분류(LLM)를 실패시켰다
        "GOOGL": LineStatus.CHECKED_NONE, "GOOG": LineStatus.CHECKED_NONE,  # 기간 안 공시 없음
        "SPY": LineStatus.UNSUPPORTED,  # → Not covered yet
    }


def stored_span(text, last_type=None):
    """fixture에서 <SEC-HEADER>부터 last_type 문서(없으면 첫 문서)의 </DOCUMENT>까지 = 이어진 원문 구간."""
    start, first = text.index("<SEC-HEADER>"), text.index("<DOCUMENT>")
    end = text.index("</DOCUMENT>", text.index(f"<TYPE>{last_type}") if last_type else first) + len("</DOCUMENT>")
    return text[start:end]


def test_원본은_SEC_HEADER와_8_K·Exhibit_99_문서_구간을_원문_그대로_남기고_그림·XBRL은_저장하지_않는다(store):
    run_edgar(store, RecordedGet(sec_responses()))

    raw = store.list_raw_filings(FRI)
    earnings = recorded("0000320193-26-000101.txt").decode()
    # SEC-HEADER(접수 시각 원본) → 8-K → EX-99.1 → EX-99.2 구간이 줄바꿈·태그까지 그대로. 뒤의 GRAPHIC(jpg)·EX-101.SCH(xsd)는 없다
    assert raw["0000320193-26-000101"] == stored_span(earnings, "EX-99.2")
    assert raw["0000320193-26-000101"].startswith("<SEC-HEADER>0000320193-26-000101.hdr.sgml : 20261015\n<ACCEPTANCE-DATETIME>")
    assert "<TYPE>GRAPHIC" not in raw["0000320193-26-000101"] and "XsdMarker" not in raw["0000320193-26-000101"]
    amendment = recorded("0000320193-26-000102.txt").decode()
    assert raw["0000320193-26-000102"] == stored_span(amendment)  # SEC-HEADER + 8-K/A 본문 문서


def test_원본의_NUL·UTF_8이_아닌_바이트는_대체_문자가_되고_PDF뿐인_Exhibit_99는_저장하지_않는다(store):
    ran = run_edgar(store, RecordedGet(sec_responses()))

    kept = stored_span(recorded("0000320193-26-000100.txt").decode())  # 헤더 + 8-K 문서. PDF EX-99.1·GIF는 뒤에 있다
    assert "[NUL]" in kept.split("</SEC-HEADER>")[0]  # 헤더 안의 NUL도 바꾼다
    assert store.list_raw_filings(FRI)["0000320193-26-000100"] == kept.replace("[NUL]", "\ufffd").replace("[0xFF]", "\ufffd")
    assert [f for f in ran.summary.failures if f.source is Source.SEC_FILINGS] == []  # 이상한 바이트 하나로 CIK가 지연되지 않는다


def classify_block(ran):
    """분류 요청 user 메시지의 <filings> 데이터 블록(접수 시각 순: 100 → 101 → 102)."""
    [request] = ran.llm.requests
    return json.loads(request.user.split("<filings>\n", 1)[1].rsplit("\n</filings>", 1)[0])


def test_Exhibit_99가_없으면_8_K_본문을_표지를_떼고_Item부터_넘긴다(store):
    [body_only, _, _] = classify_block(run_edgar(store, RecordedGet(sec_responses())))

    assert body_only["text"].startswith("Item 8.01 Other Events. On October 14, 2026, Apple Inc. announced� a new")
    assert "par value" not in body_only["text"]  # 표지의 상장 증권 목록($0.00001)이 #6 숫자 목록을 오염시키지 않는다
    assert "begin 644" not in body_only["text"]  # PDF Exhibit 99·그림은 읽지 않는다


def test_Exhibit_99는_99_1부터_이어_붙이고_HTML은_글자만_인라인_태그는_띄우지_않는다(store):
    [_, earnings, _] = classify_block(run_edgar(store, RecordedGet(sec_responses())))

    text = earnings["text"]
    assert text.startswith("Apple reports fourth quarter results CUPERTINO, CALIFORNIA — Apple® today announced")
    assert "Revenue was $94.9 billion, up 8 percent year over year." in text  # <span>·&nbsp; 사이에 공백을 넣지 않는다
    assert "Net sales $ 49,025 Research & development $ 8,067" in text  # 표 칸은 띄운다
    assert text.index("fourth quarter results") < text.index("conference call with investors")  # EX-99.1 → EX-99.2
    for hidden in ("TitleMarker", "StyleMarker", "ScriptMarker", "Item 2.02"):  # <title>·<style>·<script>, 그리고 본문은 뒤로
        assert hidden not in text


def test_정정_공시_본문은_Explanatory_Note부터_넘긴다(store):
    [_, _, amendment] = classify_block(run_edgar(store, RecordedGet(sec_responses())))

    assert amendment["form"] == "8-K/A"
    assert amendment["text"].startswith("EXPLANATORY NOTE This Amendment No. 1 amends the Current Report")
    assert "Item 5.02 Departure of Directors" in amendment["text"]


def test_iXBRL_숨은_값은_글자로_넘기지_않고_블록_태그만_띄운다():
    html = ('<div style="display:none"><ix:header><ix:hidden>0000320193<ix:header>false</ix:header>--09-27</ix:hidden>'
            '</ix:header></div><p>A</p><p>B<span>C</span></p>')
    assert edgar._html_text(html) == "A BC"  # 겹친 ix:header도 깊이로 센다



def test_SEC가_403으로_막으면_다시_시도하지_않고_이번_실행에서_SEC를_더_부르지_않으며_요약_맨_위에_남긴다(store):
    get = RecordedGet(sec_responses(**{AAPL_SUBMISSIONS: error_for_status("sec", 403)}))

    ran = run_edgar(store, get)

    assert get.urls == [AAPL_SUBMISSIONS]  # GOOGL CIK는 부르지 않는다(차단이 길어지지 않게)
    assert ran.sleeps == []
    assert ran.summary.access_denied == (Source.SEC_FILINGS,)
    assert ran.summary.rate_limited == ()
    assert [f for f in ran.summary.failures if f.source is Source.SEC_FILINGS] == [
        SourceFailure(Source.SEC_FILINGS, AAPL_CIK, FailureReason.ACCESS_DENIED),
        SourceFailure(Source.SEC_FILINGS, GOOGL_CIK, FailureReason.ACCESS_DENIED),
    ]
    assert {t: n.status for t, n in ran.summary.news.items() if t != "SPY"} == {
        "AAPL": LineStatus.DELAYED, "GOOGL": LineStatus.DELAYED, "GOOG": LineStatus.DELAYED,  # 못 받은 것을 없음으로 두지 않는다
    }


def test_SEC_429는_다시_시도해_성공해도_실행_요약에_남는다(store):
    get = RecordedGet(sec_responses(**{txt_url(101): [error_for_status("sec", 429), recorded("0000320193-26-000101.txt")]}))

    ran = run_edgar(store, get)

    assert ran.summary.rate_limited == (Source.SEC_FILINGS,)
    assert ran.summary.access_denied == ()
    assert ran.sleeps == [1.0]
    # 공시 파일 하나가 일시 실패하면 그 CIK를 처음부터 다시 받는다(다시 시도는 SourceCalls가 CIK 단위로)
    assert get.urls == [AAPL_SUBMISSIONS, txt_url(105), txt_url(102), txt_url(101),
                        AAPL_SUBMISSIONS, txt_url(105), txt_url(102), txt_url(101), txt_url(100), txt_url(104), GOOGL_SUBMISSIONS]
    assert ran.summary.failures == (SourceFailure(Source.LLM, "1", FailureReason.ERROR),)  # SEC 실패는 없다(LLM은 일부러 실패)
    assert len(store.list_raw_filings(FRI)) == 3


def test_같은_거래일을_다시_실행해도_같은_공시가_같은_원본으로_한_번씩만_저장된다(store):
    run_edgar(store, RecordedGet(sec_responses()))
    first = store.list_raw_filings(FRI)
    run_edgar(store, RecordedGet(sec_responses()))

    assert store.list_raw_filings(FRI) == first
    assert sorted(first) == ["0000320193-26-000100", "0000320193-26-000101", "0000320193-26-000102"]


def changed_submissions(change):
    data = json.loads(recorded("CIK0000320193.json"))
    change(data, data["filings"]["recent"])
    return json.dumps(data).encode()


@pytest.mark.parametrize(
    "body",
    [
        recorded("CIK0001652044.json"),  # 다른 회사의 submissions
        changed_submissions(lambda top, recent: recent["reportDate"].pop()),  # 열 길이가 다름
        changed_submissions(lambda top, recent: recent["accessionNumber"].__setitem__(2, "../../files/x")),  # 주소에 들어갈 값
        changed_submissions(lambda top, recent: recent["acceptanceDateTime"].__setitem__(3, "yesterday")),
        changed_submissions(lambda top, recent: recent.pop("items")),
        b"<html>maintenance</html>",
    ],
    ids=["other_company", "ragged", "accession", "accepted_at", "no_items", "not_json"],
)
def test_submissions_모양이_다르면_그_CIK만_다시_시도_없이_지연이다(store, body):
    get = RecordedGet(sec_responses(**{AAPL_SUBMISSIONS: body}))

    ran = run_edgar(store, get)

    assert get.urls == [AAPL_SUBMISSIONS, GOOGL_SUBMISSIONS]  # 공시 파일을 받지 않고, 같은 응답을 다시 받지 않는다
    assert [f for f in ran.summary.failures if f.source is Source.SEC_FILINGS] == [
        SourceFailure(Source.SEC_FILINGS, AAPL_CIK, FailureReason.ERROR)
    ]
    assert ran.summary.news["AAPL"].status is LineStatus.DELAYED
    assert ran.summary.news["GOOGL"].status is LineStatus.CHECKED_NONE


def test_쓸_문서_없이_SEC_HEADER뿐인_공시는_그_CIK를_지연시키고_없음으로_두지_않는다(store):
    pdf_only = bad_bytes(recorded("0000320193-26-000100.txt")).replace(b"<FILENAME>aapl-20261014.htm", b"<FILENAME>aapl-20261014.pdf")

    ran = run_edgar(store, RecordedGet(sec_responses(**{txt_url(100): pdf_only})))

    assert [f for f in ran.summary.failures if f.source is Source.SEC_FILINGS] == [
        SourceFailure(Source.SEC_FILINGS, AAPL_CIK, FailureReason.INVALID_DATA)  # 헤더만 있는 원본을 본문 없는 공시로 받지 않는다
    ]
    assert ran.summary.news["AAPL"].status is LineStatus.DELAYED
    assert store.list_raw_filings(FRI) == {}


def without(text, start, end):
    """text에서 start부터 end(포함)까지 지운다."""
    return text[: text.index(start)] + text[text.index(end) + len(end):]


EARNINGS_TXT = recorded("0000320193-26-000101.txt").decode()


@pytest.mark.parametrize(
    "earnings",
    [
        without(EARNINGS_TXT, "<ACCEPTANCE-DATETIME>", "163012\n"),  # 헤더에 접수 시각 줄이 없다
        EARNINGS_TXT.replace("<ACCEPTANCE-DATETIME>20261015163012", "<ACCEPTANCE-DATETIME>20261315163012"),  # 13월
        EARNINGS_TXT.replace("<ACCEPTANCE-DATETIME>20261015163012", "<ACCEPTANCE-DATETIME>2026101516"),  # 자릿수 모자람
        without(EARNINGS_TXT, "<SEC-HEADER>", "</SEC-HEADER>\n"),  # 헤더가 없다
    ],
    ids=["no_time", "bad_month", "short", "no_header"],
)
def test_헤더_접수_시각이_없거나_틀린_공시는_어느_카드인지_정할_수_없어_그_CIK를_지연시킨다(store, earnings):
    ran = run_edgar(store, RecordedGet(sec_responses(**{txt_url(101): earnings.encode()})))

    assert [f for f in ran.summary.failures if f.source is Source.SEC_FILINGS] == [
        SourceFailure(Source.SEC_FILINGS, AAPL_CIK, FailureReason.ERROR)
    ]
    assert ran.summary.news["AAPL"].status is LineStatus.DELAYED
    assert store.list_raw_filings(FRI) == {}


def test_Exhibit_99가_아닌_HTML_첨부는_원본에도_본문에도_넣지_않는다(store):
    ran = run_edgar(store, RecordedGet(sec_responses()))

    raw = store.list_raw_filings(FRI)
    texts = " ".join(item["text"] or "" for item in classify_block(ran))
    for marker in ("Ex21Marker", "Ex101Marker", "Ex104Marker"):  # EX-2.1(100)·EX-10.1·EX-104(102), 모두 .htm
        assert marker not in raw["0000320193-26-000100"] + raw["0000320193-26-000102"]
        assert marker not in texts
    assert "<TYPE>EX-10.1" in recorded("0000320193-26-000102.txt").decode()  # fixture에는 있다
