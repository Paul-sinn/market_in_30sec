"""live: 실제 SEC N-PORT로 SPY·QQQ·SCHD 편입 종목을 받는다(#10 B 게이트). 기본 실행에서 빠진다(pyproject addopts "-m 'not live'").
통과해야 production.py가 NoHoldingsSource 대신 EdgarHoldingsSource를 쓴다. 단언은 불리언만(실패 설명에 보고 원문이 찍히지 않게).
측정값(요청 수·시간·못 찾은 회사 이름)은 로컬 출력에만 찍는다(-s). 실행: SEC_USER_AGENT를 명령 줄에서만 넣고
uv run pytest -q -s -m live tests/test_holdings_live.py"""

import os
import time
from datetime import date, timedelta

import pytest

from m30.adapters.edgar import EdgarClient
from m30.adapters.nport import EdgarHoldingsSource
from m30.config import SEC_UA_VAR, load_edgar_settings
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
