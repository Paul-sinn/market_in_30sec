"""live: 실제 SEC N-PORT로 SPY·QQQ·SCHD 편입 종목을 받는다(#10 B 게이트). 기본 실행에서 빠진다(pyproject addopts "-m 'not live'").
통과해야 production.py가 NoHoldingsSource 대신 EdgarHoldingsSource를 쓴다. 단언은 불리언만(실패 설명에 보고 원문이 찍히지 않게).
#58 게이트: 실제 SPY 보고 + 티커 목록으로 커버 범위 주식을 만든다(원격 아침 실행 전에 사람이 돌린다. 잘못 들어간 행은 지워지지 않는다).
측정값(요청 수·시간·못 찾은 회사 이름·한 회사 여러 티커)은 로컬 출력에만 찍는다(-s). 실행: SEC_USER_AGENT는 명령 줄 안에서만
  SEC_USER_AGENT="<연락처가 든 User-Agent>" uv run pytest -q -s -m live tests/test_holdings_live.py"""

import os
import time
from datetime import date, timedelta

import pytest

from m30.adapters.edgar import EdgarClient, ticker_ciks
from m30.adapters.nport import EdgarHoldingsSource
from m30.config import SEC_UA_VAR, load_edgar_settings
from m30.coverage import DEFAULT_TICKERS, SP500_FUND, coverage_name, load_etfs, sp500_stocks
from m30.pipeline.collect import valid_holdings
from m30.pipeline.compute import TOP_HOLDINGS

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get(SEC_UA_VAR), reason=f"{SEC_UA_VAR} is not set")]
FUNDS = ("SPY", "QQQ", "SCHD")


class Counted:
    """EdgarClient.get을 감싸 요청 수를 센다."""

    def __init__(self, get):
        self._get, self.requests = get, 0

    def __call__(self, url):
        self.requests += 1
        return self._get(url)


def top_companies(report):
    """보통주 롱을 회사(cik, 없으면 이름)로 묶어 비중 큰 순 TOP_HOLDINGS개의 (cik, 이름)."""
    weights = {}
    for h in report.holdings:
        if h.asset_category == "EC" and h.pct > 0:
            key = h.cik or h.name
            weights[key] = (weights.get(key, (0, h.name))[0] + h.pct, h.name)
    return [(key if key.isdigit() else None, name) for key, (_, name) in sorted(weights.items(), key=lambda kv: -kv[1][0])][
        :TOP_HOLDINGS]


def test_실제_SEC_N_PORT로_SPY·QQQ·SCHD의_편입_종목을_받고_상위_10개_회사의_CIK를_찾는다():
    get = Counted(EdgarClient(load_edgar_settings()).get)
    source = EdgarHoldingsSource(get)  # 운영처럼 한 인스턴스: 두 목록은 처음 한 번만 받는다
    results = {}
    for fund in FUNDS:
        before, started = get.requests, time.monotonic()
        report = source.latest_report(fund)
        requests, seconds = get.requests - before, time.monotonic() - started
        if report is None:
            print(f"{fund} report=None requests={requests} seconds={seconds:.1f}")
            results[fund] = None
            continue
        top = top_companies(report)
        found = sum(cik is not None for cik, _ in top)
        ec = sum(h.asset_category == "EC" for h in report.holdings)
        print(f"{fund} accession={report.accession} period_end={report.period_end} rows={len(report.holdings)} ec={ec}"
              f" top{len(top)}_cik={found} requests={requests} seconds={seconds:.1f}")
        print(f"{fund} unmatched={[name for cik, name in top if cik is None]}")
        results[fund] = (valid_holdings(report, fund), report.period_end >= date.today() - timedelta(days=200), ec >= 10,
                         found >= 9)

    for fund in FUNDS:
        assert results[fund] is not None, f"{fund}: no report"
        valid, recent, enough, matched = results[fund]
        assert valid, f"{fund}: valid_holdings"
        assert recent, f"{fund}: period_end older than 200 days"
        assert enough, f"{fund}: fewer than 10 EC rows"
        assert matched, f"{fund}: fewer than 9 of top 10 issuer CIKs"


def test_실제_SPY_N_PORT와_SEC_티커_목록으로_커버_범위_주식을_만든다():
    get = Counted(EdgarClient(load_edgar_settings()).get)
    started = time.monotonic()
    report = EdgarHoldingsSource(get).latest_report(SP500_FUND)
    assert report is not None, "SPY: no report"
    stocks, unmatched = sp500_stocks(report, ticker_ciks(get))  # 운영과 같이 티커 목록을 따로 한 번 더 받는다
    seconds = time.monotonic() - started

    tickers = {s.ticker for s in stocks}
    found = {s.cik for s in stocks}
    by_cik = {}
    for s in stocks:
        by_cik.setdefault(s.cik, []).append(s.ticker)
    missing = sorted({h.name for h in report.holdings if h.asset_category == "EC" and h.pct > 0 and h.cik not in found})
    print(f"SPY accession={report.accession} period_end={report.period_end} companies={len(found) + unmatched}"
          f" stocks={len(stocks)} unmatched={unmatched} requests={get.requests} seconds={seconds:.1f}")
    print(f"SPY unmatched={missing}")
    print(f"SPY multi_ticker={sorted(ts for ts in by_cik.values() if len(ts) > 1)}")

    companies_ok = len(found) + unmatched >= 495  # 보고 안 보통주 회사(찾은 + 못 찾은)
    unmatched_ok = unmatched <= 15
    # 회사 하한 495 − 못 찾음 상한 15 = 찾은 회사 480, 회사마다 1행 이상. 위 둘에서도 나오지만 들어갈 행 수를 직접 본다
    rows_ok = len(stocks) >= 480
    defaults = set(DEFAULT_TICKERS) - {e.ticker for e in load_etfs()}  # 기본 종목 주식 11개
    if report.period_end < date(2026, 9, 30):
        # shortcut: 06-30 보고 'Exxon Mobil Corp' ↔ SEC 목록 'ExxonMobil Holdings Corp'(지주회사 재편, 새 CIK)라 못 찾는다, 09-30 보고부터 다시 요구
        defaults -= {"XOM"}
    defaults_ok = defaults <= tickers
    share_classes = {"GOOGL", "GOOG", "BRK-B"} <= tickers  # SPY가 가진 종류만, 주 티커
    no_other = not {"GOOGN", "GOOGM", "CELG-RI", "BRK-A"} & tickers  # 권리·기타·SPY가 안 가진 종류
    names_ok = all(s.name and coverage_name(s.name) == s.name for s in stocks)  # 법인 꼬리가 남지 않았다
    assert companies_ok, "fewer than 495 companies in the SPY report"
    assert unmatched_ok, "more than 15 unmatched companies"
    assert rows_ok, "fewer than 480 stock rows"
    assert defaults_ok, "a default stock is missing"
    assert share_classes, "GOOGL, GOOG or BRK-B missing"
    assert no_other, "GOOGN, GOOGM, CELG-RI or BRK-A included"
    assert names_ok, "empty or untrimmed name"
