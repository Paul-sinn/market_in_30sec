"""분기 작업(#60) 합성 SEC 응답 + test_quarterly가 하위 프로세스로만 돌리는 탐침. test_ 접두사가 없어 기본 수집에서 빠진다.
탐침은 분기 작업 CLI(m30.pipeline.__main__.main --quarterly)를 그대로 돌리고 전송 층 EdgarClient 하나만 네트워크 없는 대역으로 바꾼다.
사용법: python tests/quarterly_probe.py <상황> --quarterly. 끝나면 stderr 마지막 줄에 불러온 가짜 모듈 목록(fake_modules=[…])을 찍는다.
그래서 가짜 어댑터를 불러오는 테스트 모듈(test_edgar 등)을 import하지 않는다."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import psycopg

from m30.adapters import AccessDeniedError, RateLimitedError, TooLargeError, TransientSourceError
from m30.adapters.edgar import ANNUAL_REPORT_FILE_MAX, QUARTERLY_INTERVAL, SUBMISSION_TEXT_URL, SUBMISSIONS_URL, Throttle
from m30.models import Coverage

RESPONSES = Path(__file__).resolve().parent / "edgar_responses"
AAPL, MSFT, GOOGL = "0000320193", "0000789019", "0001652044"  # CIK. 대상은 이 순서(CIK 오름차순)로 돈다
XLK_CIK = "0001064641"  # Select Sector SPDR 신탁. ETF는 CIK가 있어도 대상이 아니다
COMPANIES = (
    Coverage("AAPL", "Apple", cik=AAPL), Coverage("GOOG", "Alphabet", cik=GOOGL), Coverage("GOOGL", "Alphabet", cik=GOOGL),
    Coverage("MSFT", "Microsoft", cik=MSFT), Coverage("SPY", "SPDR S&P 500 ETF", holdings_ticker="SPY"),
    Coverage("XLK", "Technology Select Sector SPDR", cik=XLK_CIK, holdings_ticker="XLK"),
)
# 회사마다 최신 10-K 접수번호. MSFT는 제출 대행사 접수번호(앞 10자리 ≠ 회사 CIK): 주소는 회사 CIK로 만든다
ACCESSIONS = {AAPL: "0000320193-25-000079", MSFT: "0000950170-25-100235", GOOGL: "0001652044-25-000014"}
SICS = {AAPL: "3571", MSFT: "7372", GOOGL: "7370"}
ACCEPTED = "20251031180502"  # 헤더 접수 시각(동부 벽시계). submissions acceptanceDateTime(녹화 값)과 다르다
BODY_CANARY = "BodyCanary60"  # 10-K 본문 자리. 공개 로그에 나오면 샌 것
NAME_CANARY = "NameCanary60"  # submissions 회사 이름 자리
NO_SIC = object()  # annual_submissions: 최상위 "sic" 키를 뺀다

MAIN_HTML = (
    "<html><head><title>TitleCanary 10-K</title><style>.x {color: red}</style></head><body>\n"
    '<div style="display:none"><ix:header><ix:hidden>HiddenCanary</ix:hidden></ix:header></div>\n'
    "<table><tr><td>Item&#160;1.</td><td>Business</td><td>1</td></tr></table>\n"
    "<div><span>Item 1.</span> <span>Business</span></div>\n"
    f"<p>The Company designs <b>smartphones</b> and {BODY_CANARY} services.</p>\n"
    "<p>The Company sells\nthrough retail stores.</p>\n"
    "<div>Item 1A. Risk Factors</div>\n"
    "</body></html>"
)


def submissions_url(cik):
    return SUBMISSIONS_URL.format(cik=cik)


def txt_url(cik, accession):
    return SUBMISSION_TEXT_URL.format(cik_number=int(cik), accession_digits=accession.replace("-", ""), accession=accession)


def annual_submissions(cik, rows, sic="3571"):
    """녹화 CIK0000320193.json의 모양(열 전부)에 cik·sic·name과 recent 행만 바꾼 바이트. rows = [(접수번호, form)], 최신 먼저.
    나머지 열은 녹화 첫 행의 값. sic=NO_SIC면 키를 뺀다."""
    data = json.loads((RESPONSES / "CIK0000320193.json").read_bytes())
    data |= {"cik": str(int(cik)), "name": NAME_CANARY, "sic": sic}
    if sic is NO_SIC:
        del data["sic"]
    filler = {name: values[0] for name, values in data["filings"]["recent"].items()}
    data["filings"]["recent"] = {
        name: [{"accessionNumber": accession, "form": form}.get(name, value) for accession, form in rows]
        for name, value in filler.items()
    }
    return json.dumps(data).encode()


def annual_report_file(accession, accepted=ACCEPTED, main=MAIN_HTML, extension=".htm", extra=True):
    """손으로 만든 10-K 전체 제출 파일(SGML): SEC-HEADER + TYPE 10-K 주 문서(main=None이면 없음) + (extra면) 첨부·그림·XBRL."""
    documents = [("10-K", f"main10k{extension}", main)] if main is not None else []
    if extra:
        documents += [
            ("EX-21", "ex21.htm", "<html><body><p>SubsidiaryCanary LLC</p></body></html>"),
            ("GRAPHIC", "logo.jpg", "begin 644 logo.jpg\nM_]C_X``02D9)1@`!`0``\nend"),
            ("EX-101.SCH", "main-20250927.xsd", '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'),
        ]
    body = "".join(
        f"<DOCUMENT>\n<TYPE>{kind}\n<SEQUENCE>{n}\n<FILENAME>{name}\n<TEXT>\n{text}\n</TEXT>\n</DOCUMENT>\n"
        for n, (kind, name, text) in enumerate(documents, 1)
    )
    return (
        f"<SEC-DOCUMENT>{accession}.txt : {accepted[:8]}\n<SEC-HEADER>{accession}.hdr.sgml : {accepted[:8]}\n"
        f"<ACCEPTANCE-DATETIME>{accepted}\nACCESSION NUMBER:\t\t{accession}\nCONFORMED SUBMISSION TYPE:\t10-K\n</SEC-HEADER>\n"
        f"{body}</SEC-DOCUMENT>\n"
    ).encode()


def annual_day(**changes):
    """회사 셋의 submissions(각 10-K 한 행) + 전체 제출 파일. changes로 주소 하나를 다른 바이트·예외(목록이면 차례로)로.
    ETF(XLK) 주소는 없다: 요청하면 기록용 get이 AssertionError로 실행을 멈춘다."""
    day = {}
    for cik, accession in ACCESSIONS.items():
        day[submissions_url(cik)] = annual_submissions(cik, [(accession, "10-K")], SICS[cik])
        day[txt_url(cik, accession)] = annual_report_file(accession)
    return day | changes


def patch(module, name, value):
    """속성 바꿔치기. 이름이 바뀌면 바꿔치기가 조용히 빈 동작이 되므로 먼저 있는지 확인한다(production_probe와 같다)."""
    assert hasattr(module, name), f"{module.__name__}.{name}"
    setattr(module, name, value)


def main(situation, args):
    import m30.pipeline.__main__ as cli
    from m30.pipeline import collect

    responses = annual_day(**{
        "quiet": {},
        "empty": {},  # 커버 범위 0행(테스트가 심지 않는다)
        "db_error": {},
        "failures": {txt_url(MSFT, ACCESSIONS[MSFT]): TransientSourceError("sec http 503")},  # 4번 다 503
        "rate_limited": {txt_url(MSFT, ACCESSIONS[MSFT]): RateLimitedError("sec http 429")},
        "denied": {submissions_url(AAPL): AccessDeniedError("sec http 403")},
        "too_large": {txt_url(MSFT, ACCESSIONS[MSFT]): TooLargeError("sec response too large")},  # EdgarClient가 상한에서 내는 것
        # 라이브러리가 요청 값(연락처)을 예외 메시지에 넣는 경우(http.client의 잘못된 헤더 값처럼)
        "crash": {submissions_url(MSFT): ValueError(f"Invalid header value {os.environ.get('SEC_USER_AGENT')!r}")},
    }[situation])

    def get(url):
        if url not in responses:
            raise AssertionError("unexpected SEC request")  # 주소는 찍지 않는다
        if isinstance(outcome := responses[url], Exception):
            raise outcome
        return outcome

    def client(settings, *, throttle, max_bytes):
        # 분기 작업 간격(초당 1회)으로 만든 따로의 Throttle이어야 한다. 아침 실행의 SEC_THROTTLE(0.125초)이면 탐침이 멈춘다
        assert type(throttle) is Throttle and throttle._interval == QUARTERLY_INTERVAL, "quarterly throttle"
        assert max_bytes == ANNUAL_REPORT_FILE_MAX, "quarterly size limit"  # 전체 제출 파일 하나가 실행 전체를 멈추지 않게
        return SimpleNamespace(get=get)

    patch(cli, "EdgarClient", client)
    patch(collect, "RETRY_DELAYS", (0.0, 0.0, 0.0))  # 503 다시 시도를 실제로 기다리지 않는다
    if situation == "db_error":
        def run_quarterly(store, *, reports):  # 실행 중 DB 연결이 끊김: 메시지에 라이브러리가 넣은 값(키 캐너리)
            raise psycopg.OperationalError(f"server closed the connection {os.environ.get('ANTHROPIC_API_KEY')}")

        patch(cli, "run_quarterly", run_quarterly)
    try:
        return cli.main(args)
    finally:
        print(f"fake_modules={sorted(m for m in sys.modules if m.startswith('m30') and 'fake' in m)}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
