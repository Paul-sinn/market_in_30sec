"""live: 실제 SEC EDGAR로 10-K 수집(#60)의 모양·크기를 본다. 기본 실행에서 빠진다(pyproject addopts "-m 'not live'"). DB 없음.
실험 회사 6개마다 submissions + 최신 10-K 전체 제출 파일(요청 간격 = 분기 작업과 같은 1초).
단언은 불리언만: 실패 메시지에 본문·User-Agent가 찍히지 않게. -s 출력은 CIK·글자 수·잘림·시간과 연 저장량 추정뿐(본문 없음).
실행: SEC_USER_AGENT는 명령 줄 안에서만(파일에 쓰지 않는다)
  SEC_USER_AGENT="<연락처가 든 User-Agent>" uv run pytest -q -s -m live tests/test_quarterly_live.py"""

import os
import time
import zlib
from datetime import datetime, timedelta

import pytest

from m30.adapters.edgar import QUARTERLY_INTERVAL, EdgarAnnualReportSource, EdgarClient, Throttle
from m30.adapters.filings import ANNUAL_REPORT_BODY_MAX, SIC
from m30.config import ET, SEC_UA_VAR, load_edgar_settings
from m30.pipeline.collect import valid_annual_report, valid_annual_report_listing

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get(SEC_UA_VAR), reason=f"{SEC_UA_VAR} is not set")]

COMPANIES = {"AAPL": "0000320193", "MSFT": "0000789019", "GOOGL": "0001652044", "JPM": "0000019617", "XOM": "0000034088",
             "KO": "0000021344"}
COVERAGE_COMPANIES = 500  # 연 저장량 추정에 쓰는 커버 범위 회사 수(S&P 500, #58)


def test_실제_EDGAR로_실험_회사의_최신_10_K_주_문서_글자와_업종_코드를_읽는다():
    source = EdgarAnnualReportSource(EdgarClient(load_edgar_settings(), throttle=Throttle(QUARTERLY_INTERVAL)).get)
    now = datetime.now(ET)

    read_all, listings_ok, reports_ok, recent, item1, lines_ok, sizes = True, True, True, True, True, True, []
    for ticker, cik in COMPANIES.items():
        started = time.monotonic()
        try:
            listing = source.listing(cik)
            report = source.annual_report(cik, listing.accession) if listing.accession else None
        except Exception:  # noqa: BLE001 — 예외 메시지(주소)를 찍지 않고 불리언으로만 남긴다
            read_all = False
            continue
        listings_ok &= valid_annual_report_listing(listing) and listing.accession is not None and SIC.fullmatch(listing.sic or "") is not None
        if report is None:
            continue
        reports_ok &= valid_annual_report(report, cik, listing.accession) and report.accepted_at.tzinfo is ET
        recent &= now - timedelta(days=400) <= report.accepted_at <= now
        lowered = report.body.lower()
        item1 &= "item 1" in lowered and "business" in lowered  # 10-K 주 문서를 골랐는지
        lines_ok &= report.body.count("\n") >= 99  # 줄이 100개 이상: 블록마다 줄바꿈이 남는다
        size = len(report.body.encode())
        sizes.append((size, len(zlib.compress(report.body.encode()))))
        print(f"{ticker} cik={cik} chars={len(report.body)} bytes={size} zlib={sizes[-1][1]}"
              f" truncated={len(report.body) == ANNUAL_REPORT_BODY_MAX} seconds={time.monotonic() - started:.1f}")
    if sizes:  # zlib는 Postgres TOAST(pglz)보다 잘 줄인다: 실제 표 크기는 bytes와 zlib 사이
        print(f"estimate per year for {COVERAGE_COMPANIES} companies: bytes={sum(s for s, _ in sizes) / len(sizes) * COVERAGE_COMPANIES / 1e6:.0f}MB"
              f" zlib={sum(z for _, z in sizes) / len(sizes) * COVERAGE_COMPANIES / 1e6:.0f}MB")

    assert read_all, "L1: submissions or 10-K read failed"
    assert listings_ok, "L2: listing without 10-K accession or 4-digit sic"
    assert len(sizes) == len(COMPANIES), "L2: some company had no 10-K"
    assert reports_ok, "L2: report contract"
    assert recent, "L2: 10-K accepted more than 400 days ago"
    assert item1, "L3: body without 'item 1' and 'business' (not the 10-K main document?)"
    assert lines_ok, "L3: body has fewer than 100 lines"
