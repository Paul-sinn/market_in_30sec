"""정부 기관 실제 어댑터(#50): 지표 일정(GovIndicatorSource)·공식 발표(GovNewsSource)·HTTP 창구(GovClient). 네트워크 없이 돈다.
tests/gov_responses/는 실제 녹화다(2026-10-29 ET, 키·연락처 없음). 기대값은 그 응답에서 손으로 고른 값(스펙 #50 5장 표)."""

import http.client
import io
import urllib.error
from datetime import date, datetime, timedelta, timezone
from email.message import Message

import pytest

from m30.adapters import AccessDeniedError, RateLimitedError, SourceError, TransientSourceError, edgar, gov
from m30.adapters.edgar import Throttle
from m30.adapters.gov import BEA_ICS_URL, BLS_ICS_URL, USER_AGENT, GovClient, GovIndicatorSource, bea_name, ics_events
from m30.adapters.gov_news import BEA_RSS_URL, BLS_FEED_URL, CENSUS_RSS_URL, FED_RSS_URL, GovNewsSource
from m30.config import ET, load_edgar_settings
from m30.pipeline.collect import filing_window
from production_probe import gov_day
from test_edgar import FakeClock, FakeOpener, RecordedGet


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=ET)


@pytest.mark.parametrize(
    "day, shown",
    [
        (14, [("CPI", at(14, 8, 30))]),  # 같은 시각 Real Earnings는 목록 밖
        (16, []),  # 수입물가(U.S. Import and Export Price Indexes)는 목록 밖
        (19, []),
        (28, [("Fed decision", at(28, 14))]),  # BLS 10:00 지역 고용 두 건은 목록 밖
        (29, [("GDP", at(29, 8, 30)), ("Income and spending", at(29, 8, 30))]),  # BEA는 UTC(12:30Z)
        (30, [("Labor costs", at(30, 8, 30))]),
    ],
    ids=["10_14_CPI", "10_16_없음", "10_19_없음", "10_28_FOMC", "10_29_GDP·소득지출", "10_30_고용비용"],
)
def test_지표_일정은_BLS·BEA_녹화_일정과_FOMC_표에서_거래일의_주요_발표만_화면_이름으로_돌려준다(day, shown):
    get = RecordedGet(gov_day())

    releases = GovIndicatorSource(get).releases(date(2026, 10, day), date(2026, 10, day))

    assert sorted((r.name, r.released_at) for r in releases) == shown
    assert all(r.released_at.tzinfo is ET for r in releases)
    assert get.urls == [BLS_ICS_URL, BEA_ICS_URL]


@pytest.mark.parametrize(
    "day, message, urls",
    [
        (date(2027, 1, 4), "bls calendar range", [BLS_ICS_URL]),  # BLS가 2027 일정을 아직 안 실었다(녹화 범위 2025-01-03~2026-12-30)
        (date(2024, 12, 31), "fomc table range", []),  # FOMC 표 밖은 요청 전에 멈춘다
        (date(2028, 1, 3), "fomc table range", []),
    ],
    ids=["BLS_범위_밖", "FOMC_표_앞", "FOMC_표_뒤"],
)
def test_세_곳_중_하나라도_거래일을_덮지_않으면_없음이_아니라_출처_실패다(day, message, urls):
    get = RecordedGet(gov_day())

    with pytest.raises(SourceError) as raised:
        GovIndicatorSource(get).releases(day, day)
    assert str(raised.value) == message
    assert get.urls == urls


def calendar(*events, newline="\r\n"):
    """VEVENT 원문(줄 목록)들 → ICS 바이트."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
    for event in events:
        lines += ["BEGIN:VEVENT", *event, "END:VEVENT"]
    return newline.join([*lines, "END:VCALENDAR", ""]).encode()


def test_ICS는_줄_접기와_이스케이프를_풀고_UTC와_동부_TZID를_같은_동부_시각으로_읽는다():
    data = calendar(
        ["SUMMARY:Gross Domestic Product\\, 3rd Quarter 2026 (Advance Estima", " te)\\; GDP by Industry\\\\x\\nnext",
         "DTSTART;VALUE=DATE-TIME:20261029T123000Z"],
        ["DTSTART;TZID=US-Eastern:20261029T083000", "SUMMARY:Consumer Price Index"],  # 속성 순서는 상관없다
        ["SUMMARY:Employment Cost Index", "DTSTART;TZID=America/New_York:20260115T083000"],  # 겨울(EST)
        ["SUMMARY:x", "DTSTART:20260115T133000Z"],
    )

    events = ics_events(data, "bea")

    assert [(summary, when) for summary, when, _ in events] == [
        ("Gross Domestic Product, 3rd Quarter 2026 (Advance Estimate); GDP by Industry\\x\nnext", at(29, 8, 30)),
        ("Consumer Price Index", at(29, 8, 30)),
        ("Employment Cost Index", datetime(2026, 1, 15, 8, 30, tzinfo=ET)),
        ("x", datetime(2026, 1, 15, 8, 30, tzinfo=ET)),
    ]
    assert all(when.tzinfo is ET for _, when, _ in events)
    assert events[0][2] == "\r\n".join(["BEGIN:VEVENT", "SUMMARY:Gross Domestic Product\\, 3rd Quarter 2026 (Advance Estima",
                                        " te)\\; GDP by Industry\\\\x\\nnext", "DTSTART;VALUE=DATE-TIME:20261029T123000Z",
                                        "END:VEVENT"])  # 원본은 받은 그대로(접힌 줄 포함)


def test_ICS는_LF_줄바꿈도_읽는다():
    data = calendar(["SUMMARY:Consumer Price Index", "DTSTART;TZID=US-Eastern:20261014T083000"], newline="\n")

    assert [(s, w) for s, w, _ in ics_events(data, "bls")] == [("Consumer Price Index", at(14, 8, 30))]


@pytest.mark.parametrize(
    "event",
    [
        ["SUMMARY:CPI"],  # DTSTART 없음
        ["DTSTART:20261014T123000Z"],  # SUMMARY 없음
        ["SUMMARY:CPI", "DTSTART;TZID=Europe/London:20261014T083000"],  # 모르는 TZID
        ["SUMMARY:CPI", "DTSTART:20261014T083000"],  # 시간대 없는 벽시계
        ["SUMMARY:CPI", "DTSTART;TZID=US-Eastern:20261014T083000Z"],  # TZID와 Z 둘 다
        ["SUMMARY:CPI", "DTSTART;VALUE=DATE:20261014"],  # 하루 종일
        ["SUMMARY:CPI", "DTSTART:20261340T083000Z"],  # 없는 날짜
    ],
    ids=["DTSTART_없음", "SUMMARY_없음", "모르는_TZID", "시간대_없음", "TZID와_Z", "날짜만", "없는_날짜"],
)
def test_ICS_일정_하나라도_모양이_다르면_그_기관_라벨로_출처_실패다(event):
    data = calendar(["SUMMARY:Consumer Price Index", "DTSTART;TZID=US-Eastern:20261014T083000"], event)

    with pytest.raises(SourceError) as raised:
        ics_events(data, "bls")
    assert str(raised.value) == "bls ics shape"
    assert raised.value.__suppress_context__


def test_ICS가_UTF_8이_아니면_출처_실패다():
    with pytest.raises(SourceError, match="^bea ics shape$"):
        ics_events(b"BEGIN:VEVENT\r\nSUMMARY:\xff\r\nEND:VEVENT\r\n", "bea")


def test_같은_이름·시각의_발표가_두_번_나오면_한_번만_돌려준다():
    twice = ["SUMMARY:Consumer Price Index", "DTSTART;TZID=US-Eastern:20261014T083000"]
    edge = (["SUMMARY:x", "DTSTART;TZID=US-Eastern:20260101T083000"], ["SUMMARY:x", "DTSTART;TZID=US-Eastern:20261231T083000"])
    get = RecordedGet({BLS_ICS_URL: calendar(*edge, twice, twice), BEA_ICS_URL: calendar(*edge)})

    releases = GovIndicatorSource(get).releases(date(2026, 10, 14), date(2026, 10, 14))

    assert [(r.name, r.released_at) for r in releases] == [("CPI", at(14, 8, 30))]


UA = "M30 Canary gov-ua-Q8@example.invalid"  # 개인 정보 없는 테스트 값


def gov_client(monkeypatch, clock=None, **opener):
    fake = FakeOpener(**opener)
    monkeypatch.setattr(gov, "_OPENER", fake)
    throttle = Throttle(0, sleep=pytest.fail) if clock is None else Throttle(1.0, clock=clock, sleep=clock.sleep)
    return GovClient(load_edgar_settings({"SEC_USER_AGENT": UA}), throttle=throttle), fake


@pytest.mark.parametrize(
    "url, agent",
    [
        (BLS_ICS_URL, UA),  # BLS만 연락처를 요구한다(연락처 없는 로봇 차단)
        (BLS_FEED_URL.format(slug="cpi"), UA),
        (BEA_ICS_URL, USER_AGENT),
        (BEA_RSS_URL, USER_AGENT),
        (CENSUS_RSS_URL, USER_AGENT),
        (FED_RSS_URL, USER_AGENT),
    ],
    ids=["BLS_일정", "BLS_피드", "BEA_일정", "BEA_피드", "Census", "연준"],
)
def test_기관_요청은_BLS에만_연락처를_User_Agent로_보내고_나머지는_고정_이름을_보내며_압축을_요청하지_않는다(monkeypatch, url, agent):
    client, opener = gov_client(monkeypatch, body=b"ok")

    assert client.get(url) == b"ok"
    [request] = opener.requests
    assert request.full_url == url
    assert request.get_header("User-agent") == agent
    assert request.get_header("Accept-encoding") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://www.bls.gov/schedule/news_release/bls.ics",  # 평문
        "https://example.com/feed/cpi.rss",  # 기관이 아닌 호스트
        "https://bls.gov/feed/cpi.rss",  # 허용 목록에 없는 이름(www 없음)
        "https://www.bls.gov:8443/feed/cpi.rss",  # 포트가 붙음
        "https://user@www.bls.gov/feed/cpi.rss",  # 사용자 정보가 붙음
        "https://www.bls.gov.example.com/feed/cpi.rss",  # 기관 이름으로 시작하는 남의 호스트
        "https://www.sec.gov/files/company_tickers.json",  # SEC는 이 창구가 아니다
    ],
)
def test_기관_요청은_HTTPS_허용_호스트_기본_포트로만_보내고_아니면_요청_전에_멈춘다(monkeypatch, url):
    client, opener = gov_client(monkeypatch)

    with pytest.raises(ValueError):
        client.get(url)
    assert opener.requests == []


def test_기관_요청은_리다이렉트를_따라가지_않는다():
    assert any(isinstance(h, edgar._NoRedirect) for h in gov._OPENER.handlers)


def gov_http_error(status):
    return urllib.error.HTTPError(BLS_ICS_URL, status, f"x {UA}", Message(), io.BytesIO(UA.encode()))


@pytest.mark.parametrize(
    "url, opener, error, message",
    [
        (BLS_ICS_URL, {"error": gov_http_error(403)}, AccessDeniedError, "bls http 403"),  # 연락처 없는 로봇 차단
        (BLS_ICS_URL, {"error": gov_http_error(429)}, RateLimitedError, "bls http 429"),
        (BEA_ICS_URL, {"error": gov_http_error(503)}, TransientSourceError, "bea http 503"),
        (BEA_RSS_URL, {"error": gov_http_error(301)}, SourceError, "bea http 301"),  # 리다이렉트를 따라가지 않은 결과
        (CENSUS_RSS_URL, {"error": gov_http_error(404)}, SourceError, "census http 404"),
        (FED_RSS_URL, {"error": TimeoutError()}, TransientSourceError, "fed timeout"),
        (FED_RSS_URL, {"error": urllib.error.URLError(ConnectionRefusedError())}, TransientSourceError, "fed connection failed"),
        (BLS_ICS_URL, {"error": http.client.IncompleteRead(b"")}, TransientSourceError, "bls connection failed"),
        (BLS_ICS_URL, {"body": b"\x1f\x8b", "encoding": "gzip"}, SourceError, "bls response encoding"),  # 압축을 요청하지 않았다
    ],
    ids=["403", "429", "503", "301", "404", "timeout", "refused", "incomplete", "gzip"],
)
def test_기관_요청_실패는_기관_라벨과_상태만_담은_출처_실패로_바뀐다(monkeypatch, url, opener, error, message):
    client, _ = gov_client(monkeypatch, **opener)

    with pytest.raises(SourceError) as raised:
        client.get(url)
    assert type(raised.value) is error
    assert str(raised.value) == message  # 주소·User-Agent·응답 본문 없음
    assert raised.value.__context__ is None or raised.value.__suppress_context__  # urllib 프레임(요청 헤더)을 잇지 않는다


def test_기관_요청은_시작_간격이_1초_이상이고_요청_전에_멈춘_주소는_간격을_쓰지_않는다(monkeypatch):
    clock = FakeClock()
    client, opener = gov_client(monkeypatch, clock=clock)

    client.get(BLS_ICS_URL)
    with pytest.raises(ValueError):
        client.get("https://example.com/x")
    client.get(BEA_ICS_URL)
    client.get(FED_RSS_URL)

    assert clock.sleeps == [1.0, 1.0]  # BLS "초당 여러 번" 금지. 기관이 달라도 같은 간격
    assert len(opener.requests) == 3


def test_기관_클라이언트는_기본으로_프로세스에_하나인_1초_간격_조절을_같이_쓴다():
    settings = load_edgar_settings({"SEC_USER_AGENT": UA})
    assert GovClient(settings)._throttle is GovClient(settings)._throttle is gov.GOV_THROTTLE
    assert gov.GOV_THROTTLE._interval == 1.0
    assert gov.GOV_THROTTLE is not edgar.SEC_THROTTLE


def ny(day, hour, minute=0, second=0, micro=0):
    """피드가 준 오프셋 그대로(-04:00). 같은 순간이면 ET와 같다고 비교된다."""
    return datetime(2026, 10, day, hour, minute, second, micro, tzinfo=timezone(timedelta(hours=-4)))


FED_MINUTES = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261013a.htm"
FED_FOMC = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"
BEA_GDP = "https://www.bea.gov/news/2026/gdp-advance-estimate-3rd-quarter-2026"
BEA_INCOME = "https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026"
BLS, BEA, CENSUS, FED = "Bureau of Labor Statistics", "Bureau of Economic Analysis", "Census Bureau", "Federal Reserve"
FEED_URLS = [*(BLS_FEED_URL.format(slug=s) for s in ("empsit", "cpi", "ppi", "jolts", "eci")), BEA_RSS_URL, CENSUS_RSS_URL,
             FED_RSS_URL]


@pytest.mark.parametrize(
    "day, found",
    [
        (14, [(FED, FED_MINUTES, ny(13, 14))]),  # 할인율 회의록 18:00 GMT. CPI(10/14 07:50)는 다음 기간
        (16, [(BLS, "ppi-2026_10_15__07_50_51", ny(15, 7, 50, 51, 146000)),
              (CENSUS, "retail_sales@2026-10-15T08:30:00-04:00", ny(15, 8, 30))]),  # business_sales(10:00)는 목록 밖
        (19, []),  # 주말 낀 기간 [10/16 04:00, 10/19 04:00)에 발표 없음
        (28, [(CENSUS, "durable_goods@2026-10-27T08:30:00-04:00", ny(27, 8, 30)),
              (CENSUS, "home_sales@2026-10-27T10:00:00-04:00", ny(27, 10))]),
        (29, [(FED, FED_FOMC, ny(28, 14))]),  # Census 10/28 다섯 건(빈집률·무역 속보 등)은 목록 밖
        (30, [(BEA, BEA_GDP, ny(29, 8, 30)), (BEA, BEA_INCOME, ny(29, 8, 30))]),  # EDT 표기
    ],
    ids=["10_14_연준", "10_16_PPI·소매판매", "10_19_없음", "10_28_Census_둘", "10_29_FOMC_성명", "10_30_BEA_둘"],
)
def test_공식_발표는_피드_8개에서_공시_기간_안의_주요_발표만_기관_이름·키·발표_시각으로_돌려준다(day, found):
    get = RecordedGet(gov_day())
    since, until = filing_window(date(2026, 10, day))

    items = GovNewsSource(get).items(since, until)

    assert sorted((i.source, i.key, i.published_at) for i in items) == found
    assert get.urls == FEED_URLS  # 재무부는 없다


def by_key(day):
    since, until = filing_window(date(2026, 10, day))
    return {i.key: i for i in GovNewsSource(RecordedGet(gov_day())).items(since, until)}


def test_공식_발표_제목은_원문_그대로이고_본문은_HTML_태그를_뗀_글자다():
    ppi, retail = by_key(16).values()
    fomc = by_key(29)[FED_FOMC]
    gdp = by_key(30)[BEA_GDP]

    assert ppi.title == "PPI for final demand increases 1.3% in September; goods advance 2.6%, services rise 0.8%"
    assert ppi.text.startswith("The Producer Price Index for final demand increased 1.3 percent in September.")
    assert (retail.title, retail.text) == (
        "Advance Monthly Sales for Retail and Food Services",
        "U.S. retail and food services sales for September 2026 were $745.0 billion, up 0.8 percent (+/-0.4 percent) from the"
        " previous month. September 2026: +0.8 % Change August 2026 (r): +1.3 % Change")
    assert (fomc.title, fomc.text) == ("Federal Reserve issues FOMC statement",) * 2  # 성명 RSS에는 결정 내용이 없다
    assert gdp.title == "GDP (Advance Estimate), 3rd Quarter 2026"
    assert gdp.text.startswith("Real gross domestic product (GDP) increased at an annual rate of 3.4 percent")
    assert "<p>" not in gdp.text
    assert "<guid" in gdp.raw and "gdp-advance-estimate-3rd-quarter-2026" in gdp.raw  # 원본 = 항목 요소
    assert "ppi-2026_10_15__07_50_51" in ppi.raw


def rss_item(**fields):
    tags = {"title": "Federal Reserve issues FOMC statement", "guid": "https://www.federalreserve.gov/x.htm",
            "pubDate": "Wed, 28 Oct 2026 18:00:00 GMT", "description": "d"} | fields
    return "<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in tags.items() if v is not None) + "</item>"


def rss(*items):
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{"".join(items)}</channel></rss>'.encode()


@pytest.mark.parametrize(
    "body",
    [
        rss(rss_item())[:-20],  # 끊긴 XML
        b"<html><body>Access Denied</body></html>",  # 200으로 온 차단 페이지(항목 0개 = 없음으로 읽지 않는다)
        b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>',  # 다른 형식
        rss(rss_item(pubDate=None)),
        rss(rss_item(pubDate="Wed, 28 Oct 2026 18:00:00 XYZ")),  # 모르는 시간대 = 시각을 모른다
        rss(rss_item(pubDate="yesterday")),
        rss(rss_item(guid=" ")),
        rss(rss_item(title=None)),
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/hosts">]><rss><channel>&x;</channel></rss>',  # 외부 엔티티
    ],
    ids=["끊긴_XML", "HTML", "Atom", "날짜_없음", "모르는_시간대", "날짜_아님", "빈_guid", "제목_없음", "외부_엔티티"],
)
def test_피드_하나라도_모양이_다르면_공식_발표_전체가_그_기관_라벨로_출처_실패다(body):
    get = RecordedGet(gov_day(**{FED_RSS_URL: body}))
    since, until = filing_window(date(2026, 10, 29))

    with pytest.raises(SourceError) as raised:
        GovNewsSource(get).items(since, until)
    assert str(raised.value) == "fed feed shape"
    assert raised.value.__suppress_context__


def atom(entry):
    return f'<feed xmlns="http://www.w3.org/2005/Atom"><id>x</id><title>t</title>{entry}</feed>'.encode()


ATOM_ENTRY = "<entry><title>CPI rose</title><id>cpi-1</id>{content}<published>{published}</published></entry>"


@pytest.mark.parametrize("published", ["", "2026-10-14T07:50:31", "October 14"], ids=["없음", "오프셋_없음", "날짜_아님"])
def test_BLS_항목에_오프셋_있는_발표_시각이_없으면_출처_실패다(published):
    body = atom(ATOM_ENTRY.format(content="", published=published))
    get = RecordedGet(gov_day(**{BLS_FEED_URL.format(slug="cpi"): body}))
    since, until = filing_window(date(2026, 10, 15))

    with pytest.raises(SourceError, match="^bls feed shape$"):
        GovNewsSource(get).items(since, until)


@pytest.mark.parametrize(
    "content, text",
    [
        ("<content>Prices rose 0.6 percent.</content>", "Prices rose 0.6 percent."),
        ('<content type="html">&lt;p&gt;Prices &lt;b&gt;rose&lt;/b&gt; 0.6 percent.&lt;/p&gt;</content>', "Prices rose 0.6 percent."),
        ('<content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Prices <b>rose</b> 0.6 percent.</div></content>',
         "Prices rose 0.6 percent."),
        ("", ""),
    ],
    ids=["글자", "html", "xhtml", "본문_없음"],
)
def test_BLS_본문은_content_종류에_맞게_태그를_뗀다(content, text):
    body = atom(ATOM_ENTRY.format(content=content, published="2026-10-14T07:50:31.2-04:00"))
    get = RecordedGet(gov_day(**{BLS_FEED_URL.format(slug="cpi"): body}))
    since, until = filing_window(date(2026, 10, 15))

    [item] = GovNewsSource(get).items(since, until)
    assert (item.source, item.key, item.title, item.text) == (BLS, "cpi-1", "CPI rose", text)


def test_피드_받기가_실패하면_다시_시도는_호출부에_맡기고_그대로_올린다():
    get = RecordedGet(gov_day(**{CENSUS_RSS_URL: TransientSourceError("census http 503")}))
    since, until = filing_window(date(2026, 10, 30))

    with pytest.raises(TransientSourceError, match="^census http 503$"):
        GovNewsSource(get).items(since, until)
    assert get.urls == FEED_URLS[:7]  # 연준은 부르지 않았다


def test_같은_기관의_같은_키는_한_번만_돌려준다():
    twice = rss_item(guid="https://www.federalreserve.gov/a.htm")
    get = RecordedGet(gov_day(**{FED_RSS_URL: rss(twice, twice)}))
    since, until = filing_window(date(2026, 10, 29))

    assert [i.key for i in GovNewsSource(get).items(since, until)] == ["https://www.federalreserve.gov/a.htm"]


@pytest.mark.parametrize(
    "title, name",
    [
        ("GDP (Advance Estimate), 3rd Quarter 2026", "GDP"),
        ("Gross Domestic Product, 3rd Quarter 2025 (Updated Estimate), GDP by Industry, and Corporate Profits (Revised)", "GDP"),
        ("Personal Income and Outlays, September 2026", "Income and spending"),
        ("U.S. International Trade in Goods and Services, August 2026", "Trade balance"),
        ("Gross Domestic Product by State and Personal Income by State, 3rd Quarter 2025", None),  # 주별: 시장 전체가 아니다
        ("Gross Domestic Product by County and Metropolitan Area, 2023", None),
        ("GDP by County and Metropolitan Area, 2024", None),
        ("Gross Domestic Product for Puerto Rico, 2023", None),
        ("U.S. International Transactions, 3rd Quarter 2025", None),
        ("Real Personal Consumption Expenditures by State and Real Personal Income by State, 2024", None),
    ],
)
def test_BEA_주요_발표는_제목_앞부분으로만_고른다(title, name):
    assert bea_name(title) == name


def test_BLS_주요_발표는_일정_제목이_정확히_같을_때만_고른다():
    edge = (["SUMMARY:x", "DTSTART;TZID=US-Eastern:20260101T083000"], ["SUMMARY:x", "DTSTART;TZID=US-Eastern:20261231T083000"])
    near = [["SUMMARY:Employment Situation of Veterans", "DTSTART;TZID=US-Eastern:20261014T100000"],
            ["SUMMARY:Employment Situation", "DTSTART;TZID=US-Eastern:20261014T083000"],
            ["SUMMARY:Consumer Price Index for All Urban Consumers", "DTSTART;TZID=US-Eastern:20261014T083000"]]
    get = RecordedGet({BLS_ICS_URL: calendar(*edge, *near), BEA_ICS_URL: calendar(*edge)})

    releases = GovIndicatorSource(get).releases(date(2026, 10, 14), date(2026, 10, 14))

    assert [(r.name, r.released_at) for r in releases] == [("Jobs report", at(14, 8, 30))]
