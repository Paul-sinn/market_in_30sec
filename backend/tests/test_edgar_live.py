"""live: 실제 SEC EDGAR 호출(요청 10회 미만). 기본 실행에서 빠진다(pyproject addopts "-m 'not live'").
fixture(tests/edgar_responses/)를 만들 때 세운 가정 A1~A5(test_edgar.py docstring)가 실제 응답과 맞는지 본다.
단언은 불리언만: 실패 메시지에 공시 본문·User-Agent가 찍히지 않게. 실패하면 메시지의 가정 번호만 공유한다.
실행: SEC_USER_AGENT("이름 연락이메일")를 셸에서 export한 뒤 uv run pytest -q -m live tests/test_edgar_live.py"""

import os
import re
from datetime import datetime, timedelta

import pytest

from m30.adapters.edgar import EdgarClient, EdgarFilingSource, ticker_ciks
from m30.config import ET, SEC_UA_VAR, load_edgar_settings
from m30.experiment import EXPERIMENT_ETFS, experiment_coverage
from m30.pipeline.collect import valid_filings

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get(SEC_UA_VAR), reason=f"{SEC_UA_VAR} is not set")]
AAPL_CIK = "0000320193"


def header_accepted_at(raw):
    """SEC-HEADER의 <ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS(EDGAR 동부 시각). 없으면 None."""
    found = re.search(r"<ACCEPTANCE-DATETIME>([0-9]{14})", raw)
    return found and datetime.strptime(found[1], "%Y%m%d%H%M%S").replace(tzinfo=ET)


class Counted:
    """EdgarClient.get을 감싸 요청 수를 센다."""

    def __init__(self, get):
        self._get, self.requests = get, 0

    def __call__(self, url):
        self.requests += 1
        return self._get(url)


def test_실제_EDGAR에서_실험_종목_CIK와_Apple_실적_8_K를_가정대로_읽는다():
    get = Counted(EdgarClient(load_edgar_settings()).get)
    until = datetime.now(ET)
    since = until - timedelta(days=120)  # 분기 실적 8-K가 적어도 하나 들어가는 기간

    coverage = {c.ticker: c.cik for c in experiment_coverage(ticker_ciks(get))}
    filings = EdgarFilingSource(get).filings(AAPL_CIK, since, until)
    earnings = [f for f in filings if "2.02" in f.items]

    # 단언 전에 참/거짓으로 만든다: pytest가 실패 설명에 Filing repr(본문)을 찍지 않게
    googl_aapl = coverage["GOOGL"] == "0001652044" and coverage["AAPL"] == AAPL_CIK
    etfs_empty = all(coverage[t] is None for t in EXPERIMENT_ETFS)
    valid = valid_filings(filings, AAPL_CIK)
    in_window = all(since <= f.accepted_at < until for f in filings)
    headers_kept = all(f.raw.startswith("<SEC-HEADER>") and header_accepted_at(f.raw) is not None for f in filings)
    # A1 직접 확인: JSON acceptanceDateTime을 동부로 읽은 값 = 헤더의 접수 시각(동부). UTC였다면 4~5시간 차이가 난다
    header_matches = len(filings) > 0 and all(header_accepted_at(f.raw) == f.accepted_at for f in filings)
    assert googl_aapl, "A3: ticker list shape"
    assert etfs_empty, "U3: ETF CIK"
    assert valid, "A2: submissions shape"
    assert in_window, "A2: window"
    assert headers_kept, "A4: raw does not start with SEC-HEADER with ACCEPTANCE-DATETIME"
    assert header_matches, "A1: acceptanceDateTime differs from SEC-HEADER ACCEPTANCE-DATETIME (not US Eastern wall clock?)"
    assert len(earnings) > 0, "A2: no 2.02 8-K in the last 120 days"
    for f in earnings:
        has_report_date = f.report_date is not None
        exhibit_ok = len(f.exhibit99 or "") > 500 and "Apple" in (f.exhibit99 or "")
        body_at_item = (f.body or "")[:4].lower() == "item"
        raw_small = "<TYPE>GRAPHIC" not in f.raw and "<TYPE>EX-101" not in f.raw
        assert has_report_date, "A2: reportDate"
        assert exhibit_ok, "A4: EX-99 text"
        assert body_at_item, "A4/U5: 8-K body does not start at Item"
        assert raw_small, "U1: graphic/XBRL stored"
    assert get.requests < 10, "SEC requests per run"
