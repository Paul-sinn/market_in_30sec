"""SEC N-PORT 편입 종목 어댑터(#10 B). 녹화한 실제 응답 + 기록용 get. 네트워크·DB 없이 돈다.

tests/edgar_responses/의 아래 파일은 2026-10-28 실제 SEC 응답을 녹화해 잘라 낸 것이다(요청 헤더·User-Agent는 들어 있지 않다).
- company_tickers_mf.json: 실제 fields + QQQ·TQQQ·SCHB·SCHD 4행
- company_tickers_holdings.json: 실제 company_tickers.json 중 아래 보고에 남긴 회사 행 + SPY
- CIK0000884394.json(SPY 신탁)·CIK0001067839.json(QQQ 신탁)·CIK0001454889.json(Schwab 신탁): filings.recent에서 고른 3행
- 0001410368-26-089410.txt(SPY 2026-06-30), 0001067839-26-000030.txt(QQQ 2026-06-30), 0001410368-26-108609.txt(SCHD 2026-08-31),
  0001410368-26-108627.txt(Schwab 다른 시리즈): invstOrSec는 보통주 비중 상위 12개(다른 시리즈는 2개) + 다른 분류마다 첫 행만,
  NPORT-P가 아닌 문서(NPORT-EX·GRAPHIC)는 <TEXT> 앞 300자만 남겼다. 나머지 바이트는 받은 그대로다"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from m30.adapters import SourceError
from m30.adapters.edgar import HEADER, SUBMISSION_TEXT_URL, SUBMISSIONS_URL, TICKERS_URL
from m30.adapters.holdings import Holding
from m30.adapters.nport import HEADER_URL, MF_TICKERS_URL, EdgarHoldingsSource, fund_series, issuer_ciks, issuer_key
from test_edgar import RecordedGet, client

RESPONSES = Path(__file__).resolve().parent / "edgar_responses"
SPY_CIK, QQQ_CIK, SCHWAB_CIK = "0000884394", "0001067839", "0001454889"
SPY_8, QQQ_8, SCHD_8, OTHER_SERIES = ("0001410368-26-089410", "0001067839-26-000030", "0001410368-26-108609",
                                      "0001410368-26-108627")


def recorded(name):
    return (RESPONSES / name).read_bytes()


def txt_url(cik, accession):
    return SUBMISSION_TEXT_URL.format(cik_number=int(cik), accession_digits=accession.replace("-", ""), accession=accession)


def hdr_url(cik, accession):
    return HEADER_URL.format(cik_number=int(cik), accession_digits=accession.replace("-", ""), accession=accession)


def header(accession):
    """헤더(.hdr.sgml) 응답 자리 = 녹화 전체 제출 파일의 <SEC-HEADER> 부분. 실제 .hdr.sgml은 나머지 줄도 태그 형식이지만
    시리즈 부분(<SERIES-ID>S…)은 같은 태그다(#59 main 점검이 실제 헤더에서 같은 패턴으로 찾았다)."""
    return HEADER.search(recorded(f"{accession}.txt").decode()).group(0).encode()


def sec(**changes):
    """녹화 응답 전부: 목록 둘 + 신탁 submissions 셋 + 보고 넷 + 멀티 시리즈 보고 셋의 헤더. changes: 주소 → 바꿀 응답."""
    return RecordedGet({
        MF_TICKERS_URL: recorded("company_tickers_mf.json"),
        TICKERS_URL: recorded("company_tickers_holdings.json"),
        **{SUBMISSIONS_URL.format(cik=cik): recorded(f"CIK{cik}.json") for cik in (SPY_CIK, QQQ_CIK, SCHWAB_CIK)},
        txt_url(SPY_CIK, SPY_8): recorded(f"{SPY_8}.txt"),
        txt_url(QQQ_CIK, QQQ_8): recorded(f"{QQQ_8}.txt"),
        txt_url(SCHWAB_CIK, SCHD_8): recorded(f"{SCHD_8}.txt"),
        txt_url(SCHWAB_CIK, OTHER_SERIES): recorded(f"{OTHER_SERIES}.txt"),
        **{hdr_url(cik, a): header(a) for cik, a in ((QQQ_CIK, QQQ_8), (SCHWAB_CIK, SCHD_8), (SCHWAB_CIK, OTHER_SERIES))},
    } | changes)


def test_펀드_목록에_없는_UIT는_회사_목록의_CIK로_가장_최근_NPORT_P를_읽고_발행_회사_CIK를_이름으로_찾는다():
    get = sec()

    report = EdgarHoldingsSource(get).latest_report("SPY")

    assert (report.fund, report.accession, report.period_end, len(report.holdings)) == ("SPY", SPY_8, date(2026, 6, 30), 13)
    assert report.holdings[0] == Holding("Advanced Micro Devices Inc", "0000002488", Decimal("1.469416714247"), "EC")
    assert report.holdings[8] == Holding("Eli Lilly & Co", "0000059478", Decimal("1.471872349457"), "EC")  # &amp;를 푼 이름
    assert report.holdings[7] == Holding("CONTRA HOLOGIC INCORPO", None, Decimal("0.000003300899"), "DE")  # 회사 목록에 없음
    # 티커 목록(UIT 대체 경로·발행 회사 이름)은 한 번만 받는다. 시리즈가 없으니 헤더 없이 첫 NPORT-P를 쓴다(N-30D 행은 건너뜀)
    assert get.urls == [MF_TICKERS_URL, TICKERS_URL, SUBMISSIONS_URL.format(cik=SPY_CIK), txt_url(SPY_CIK, SPY_8)]
    assert report.raw.startswith('<?xml version="1.0" encoding="UTF-8"?><edgarSubmission')
    assert report.raw.endswith("</edgarSubmission>")


def test_멀티_시리즈_신탁은_헤더로_시리즈가_다른_보고를_건너뛰고_그_ETF_시리즈의_가장_최근_보고만_전체_파일로_받는다():
    get = sec()

    report = EdgarHoldingsSource(get).latest_report("SCHD")

    assert (report.accession, report.period_end, len(report.holdings)) == (SCHD_8, date(2026, 8, 31), 14)
    assert report.holdings[4] == Holding("Coca-Cola Co/The", "0000021344", Decimal("4.159971454108"), "EC")
    assert report.holdings[7] == Holding("Merck & Co Inc", "0000310158", Decimal("4.759978574771"), "EC")
    # 펀드 목록에 있으니 회사 티커 목록은 발행 회사 이름을 찾을 때(보고를 고른 뒤) 처음 받는다
    assert get.urls == [MF_TICKERS_URL, SUBMISSIONS_URL.format(cik=SCHWAB_CIK), hdr_url(SCHWAB_CIK, OTHER_SERIES),
                        hdr_url(SCHWAB_CIK, SCHD_8), txt_url(SCHWAB_CIK, SCHD_8), TICKERS_URL]


def test_펀드_목록의_시리즈가_있는_신탁은_서식이_정확히_NPORT_P인_첫_행의_시리즈를_확인하고_쓴다():
    get = sec()

    report = EdgarHoldingsSource(get).latest_report("QQQ")

    assert (report.accession, report.period_end) == (QQQ_8, date(2026, 6, 30))  # 40-17G 행은 건너뜀
    assert report.holdings[0] == Holding("Broadcom Inc.", "0001730168", Decimal("2.809874873774"), "EC")
    assert get.urls[:4] == [MF_TICKERS_URL, SUBMISSIONS_URL.format(cik=QQQ_CIK), hdr_url(QQQ_CIK, QQQ_8), txt_url(QQQ_CIK, QQQ_8)]


def with_recent(cik, *rows):
    """신탁 submissions의 filings.recent를 (접수번호, 서식) 행으로 바꾼다. 다른 열은 첫 행 값을 되풀이한다."""
    data = json.loads(recorded(f"CIK{cik}.json"))
    recent = data["filings"]["recent"]
    data["filings"]["recent"] = {name: [values[0]] * len(rows) for name, values in recent.items()} | {
        "accessionNumber": [a for a, _ in rows], "form": [f for _, f in rows]}
    return json.dumps(data).encode()


def test_정정_보고_NPORT_P_A는_최신이어도_쓰지_않는다():
    amended = "0001410368-26-099999"
    get = sec(**{SUBMISSIONS_URL.format(cik=SPY_CIK): with_recent(SPY_CIK, (amended, "NPORT-P/A"), (SPY_8, "NPORT-P"))})

    assert EdgarHoldingsSource(get).latest_report("SPY").accession == SPY_8
    assert txt_url(SPY_CIK, amended) not in get.urls


def test_멀티_시리즈_신탁에서_그_시리즈_최신_보고가_365번째여도_헤더로_찾고_전체_파일은_그_보고만_받는다():
    others = [(f"0001410368-26-{n:06d}", "NPORT-P") for n in range(1, 365)]  # 앞에 다른 시리즈 364건 = #59 실측 최대(iShares IWD)
    get = sec(**{SUBMISSIONS_URL.format(cik=SCHWAB_CIK): with_recent(SCHWAB_CIK, *others, (SCHD_8, "NPORT-P"))},
              **{hdr_url(SCHWAB_CIK, a): header(OTHER_SERIES) for a, _ in others})

    report = EdgarHoldingsSource(get).latest_report("SCHD")

    assert (report.accession, report.period_end) == (SCHD_8, date(2026, 8, 31))
    assert [u for u in get.urls if u.endswith(".txt")] == [txt_url(SCHWAB_CIK, SCHD_8)]


def test_최근_500건_헤더에_그_시리즈가_없으면_미지원이고_501번째_헤더와_전체_파일은_받지_않는다():
    rows = [(f"0001410368-26-{n:06d}", "NPORT-P") for n in range(1, 502)]
    get = sec(**{SUBMISSIONS_URL.format(cik=SCHWAB_CIK): with_recent(SCHWAB_CIK, *rows)},
              **{hdr_url(SCHWAB_CIK, a): header(OTHER_SERIES) for a, _ in rows})  # 전부 다른 시리즈

    assert EdgarHoldingsSource(get).latest_report("SCHD") is None
    assert get.urls.count(TICKERS_URL) == 0
    assert [u for u in get.urls if u.endswith(".hdr.sgml")] == [hdr_url(SCHWAB_CIK, a) for a, _ in rows[:500]]
    assert not [u for u in get.urls if u.endswith(".txt")]


def test_같은_신탁의_두_ETF는_앞_ETF가_받은_헤더를_다시_받지_않는다():
    get = sec(**{MF_TICKERS_URL: with_mf_rows([1454889, "S000026638", "C000080000", "SCHC"])})  # OTHER_SERIES의 시리즈
    source = EdgarHoldingsSource(get)

    schd, schc = source.latest_report("SCHD"), source.latest_report("SCHC")

    assert (schd.accession, schc.accession) == (SCHD_8, OTHER_SERIES)
    assert [u for u in get.urls if u.endswith(".hdr.sgml")] == [hdr_url(SCHWAB_CIK, OTHER_SERIES), hdr_url(SCHWAB_CIK, SCHD_8)]


NEWER = "0001410368-26-120001"  # SCHD 보고보다 최신인 Schwab 접수(가짜)
SCHD_HEADER = header(SCHD_8).decode()


@pytest.mark.parametrize(
    "newer_header",
    [header(SPY_8),  # SERIES 부분이 없는 헤더(단일 시리즈 신탁 것)
     SCHD_HEADER.replace("<SERIES-ID>S000034163", "<SERIES-ID>S00003416").encode(),  # 숫자 8개
     SCHD_HEADER.replace("<SERIES-ID>S000034163", "<SERIES-ID>S0000341630").encode(),  # 숫자 10개
     b"not a header"],
    ids=["SERIES_없음", "숫자_모자람", "숫자_넘침", "헤더_아님"],
)
def test_헤더에_그_시리즈_ID가_정확히_없으면_전체_파일을_받지_않고_다음_접수로(newer_header):
    get = sec(**{SUBMISSIONS_URL.format(cik=SCHWAB_CIK): with_recent(SCHWAB_CIK, (NEWER, "NPORT-P"), (SCHD_8, "NPORT-P")),
                 hdr_url(SCHWAB_CIK, NEWER): newer_header})

    assert EdgarHoldingsSource(get).latest_report("SCHD").accession == SCHD_8
    assert txt_url(SCHWAB_CIK, NEWER) not in get.urls


def test_헤더는_그_시리즈인데_본문_시리즈가_다르면_그_보고는_쓰지_않고_다음_접수로():
    get = sec(**{SUBMISSIONS_URL.format(cik=SCHWAB_CIK): with_recent(SCHWAB_CIK, (NEWER, "NPORT-P"), (SCHD_8, "NPORT-P")),
                 hdr_url(SCHWAB_CIK, NEWER): header(SCHD_8), txt_url(SCHWAB_CIK, NEWER): recorded(f"{OTHER_SERIES}.txt")})

    report = EdgarHoldingsSource(get).latest_report("SCHD")

    assert (report.accession, report.period_end) == (SCHD_8, date(2026, 8, 31))
    assert [u for u in get.urls if u.endswith(".txt")] == [txt_url(SCHWAB_CIK, NEWER), txt_url(SCHWAB_CIK, SCHD_8)]


@pytest.mark.parametrize(
    "fund, changes, urls",
    [
        ("VOO", {}, [MF_TICKERS_URL, TICKERS_URL]),  # 두 목록 어디에도 없음: submissions를 받지 않는다
        ("SPY", {SUBMISSIONS_URL.format(cik=SPY_CIK): with_recent(SPY_CIK, ("0001193125-26-247066", "N-30D"))},
         [MF_TICKERS_URL, TICKERS_URL, SUBMISSIONS_URL.format(cik=SPY_CIK)]),
    ],
    ids=["SEC가_모르는_ETF", "NPORT_P가_없는_신탁"],
)
def test_SEC에서_편입_보고를_찾지_못하면_실패가_아니라_미지원이다(fund, changes, urls):
    get = sec(**changes)

    assert EdgarHoldingsSource(get).latest_report(fund) is None
    assert get.urls == urls


def with_mf_rows(*rows):
    """녹화 펀드 목록 끝에 [cik, seriesId, classId, symbol] 행을 더한다."""
    data = json.loads(recorded("company_tickers_mf.json"))
    data["data"] += [list(r) for r in rows]
    return json.dumps(data).encode()


def test_펀드_목록에서_같은_심볼이_다른_CIK나_시리즈를_가리키면_그_심볼은_쓰지_않는다():
    clash = with_mf_rows([1454889, "S000099999", "C000099999", "SCHD"])  # 같은 심볼, 다른 시리즈
    get = sec(**{MF_TICKERS_URL: clash})

    assert EdgarHoldingsSource(get).latest_report("SCHD") is None  # 회사 티커 목록에도 없다
    assert fund_series(RecordedGet({MF_TICKERS_URL: clash}))["QQQ"] == ("0001067839", "S000101292")  # 나머지는 쓴다


@pytest.mark.parametrize(
    "nport_name, sec_title",
    [
        ("Coca-Cola Co/The", "COCA COLA CO"),
        ("Alphabet Inc Class C", "Alphabet Inc."),
        ("Amazon.com Inc", "AMAZON COM INC"),
        ("Merck & Co Inc", "Merck & Co., Inc."),
        ("Home Depot Inc/The", "HOME DEPOT, INC."),
        ("Berkshire Hathaway Inc Class B", "BERKSHIRE HATHAWAY INC"),
        ("News Corp", "NEWS CORP /NEW/"),
        ("Charles Schwab Corp/The", "SCHWAB CHARLES CORP"),  # SEC 정형명은 성·이름 순서가 뒤집힌 회사가 있다(#58)
        ("T Rowe Price Group Inc", "PRICE T ROWE GROUP INC"),
        # 2026-06-30 SPY 보고 이름 ↔ 2026-11 SEC 티커 목록 title(live 게이트 1차 실패, #58)
        ("Lowe's Cos Inc", "LOWES COMPANIES INC"),
        ("McDonald's Corp", "MCDONALDS CORP"),
        ("O'Reilly Automotive Inc", "O REILLY AUTOMOTIVE INC"),
        ("DR Horton Inc", "HORTON D R INC /DE/"),
        ("CH Robinson Worldwide Inc", "C. H. ROBINSON WORLDWIDE, INC."),
        ("WW Grainger Inc", "W.W. GRAINGER, INC."),
        ("Huntington Bancshares Inc/OH", "HUNTINGTON BANCSHARES INC /MD/"),
        ("Vertex Pharmaceuticals Inc", "VERTEX PHARMACEUTICALS INC / MA"),
        ("CRH PLC", "CRH PUBLIC LTD CO"),
        ("NXP Semiconductors NV", "NXP Semiconductors N.V."),
        ("Air Products and Chemicals Inc", "Air Products & Chemicals, Inc."),
        ("Wells Fargo & Co", "WELLS FARGO & COMPANY/MN"),
        ("SLB Ltd", "SLB LIMITED/NV"),
    ],
)
def test_N_PORT_이름과_SEC_회사_이름은_법인_꼬리·주식_종류를_빼고_같으면_같은_회사다(nport_name, sec_title):
    assert issuer_key(nport_name) == issuer_key(sec_title) != ""


@pytest.mark.parametrize("nport_name, sec_title", [("Meta Platforms Inc", "Meta Materials Inc."), ("Apple Inc", "Apple Hospitality REIT")])
def test_이름_일부만_같으면_같은_회사가_아니다(nport_name, sec_title):
    assert issuer_key(nport_name) != issuer_key(sec_title)


def test_정규화한_이름이_같은데_CIK가_다른_회사는_어느_쪽에도_연결하지_않는다():
    data = json.loads(recorded("company_tickers_holdings.json"))
    data["99"] = {"cik_str": 999999, "ticker": "KOX", "title": "Coca-Cola Company"}  # 'coca cola'가 둘
    get = RecordedGet({TICKERS_URL: json.dumps(data).encode()})

    found = issuer_ciks(get)
    assert "coca cola" not in found
    assert found["merck"] == "0000310158"


SCHD_TXT = recorded(f"{SCHD_8}.txt").decode()


@pytest.mark.parametrize(
    "text, message",
    [
        (SCHD_TXT.replace('<?xml version="1.0" encoding="UTF-8"?>',
                          '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'), "nport shape"),  # 엔티티 확장 막기
        (SCHD_TXT.replace("<pctVal>4.679338311033</pctVal>", "<pctVal>4.67%</pctVal>"), "nport shape"),
        (SCHD_TXT.replace("<repPdDate>2026-08-31</repPdDate>", "<repPdDate>08/31/2026</repPdDate>"), "nport shape"),
        (SCHD_TXT.replace("</edgarSubmission>", ""), "nport shape"),  # XML이 닫히지 않음
        (SCHD_TXT.replace("<TYPE>NPORT-P", "<TYPE>NPORT-EX"), "nport shape"),  # NPORT-P 문서가 없음
    ],
    ids=["DOCTYPE", "비중이_숫자_아님", "기준일_형식", "XML_깨짐", "NPORT_P_문서_없음"],
)
def test_보고_모양이_다르면_다시_시도하지_않는_출처_실패다(text, message):
    get = sec(**{txt_url(SCHWAB_CIK, SCHD_8): text.encode()})

    with pytest.raises(SourceError, match=f"^{message}$"):
        EdgarHoldingsSource(get).latest_report("SCHD")


@pytest.mark.parametrize(
    "body",
    [recorded(f"CIK{SPY_CIK}.json"), b"[]", b"{not json"],  # 다른 회사(SPY 신탁)의 submissions, 모양, JSON
    ids=["다른_회사", "모양", "JSON_깨짐"],
)
def test_submissions_모양이_다르면_출처_실패다(body):
    get = sec(**{SUBMISSIONS_URL.format(cik=SCHWAB_CIK): body})

    with pytest.raises(SourceError, match="^sec submissions shape$"):
        EdgarHoldingsSource(get).latest_report("SCHD")


def test_보고_원본의_NUL은_대체_문자로_바꾸고_모든_요청은_SEC_호스트로만_간다():
    nul = SCHD_TXT.replace("<regName>SCHWAB STRATEGIC TRUST</regName>", "<regName>SCHWAB\x00TRUST</regName>")
    get = sec(**{txt_url(SCHWAB_CIK, SCHD_8): nul.encode()})

    report = EdgarHoldingsSource(get).latest_report("SCHD")

    assert "\x00" not in report.raw and "SCHWAB�TRUST" in report.raw
    assert all(u.startswith(("https://www.sec.gov/", "https://data.sec.gov/")) for u in get.urls)


def test_헤더_주소는_EdgarClient의_HTTPS_SEC_호스트_검사를_통과한다(monkeypatch):
    edgar_client, opener = client(monkeypatch, body=header(SCHD_8))

    assert edgar_client.get(hdr_url(SCHWAB_CIK, SCHD_8)) == header(SCHD_8)
    assert [r.full_url for r in opener.requests] == [
        "https://www.sec.gov/Archives/edgar/data/1454889/000141036826108609/0001410368-26-108609.hdr.sgml"]
