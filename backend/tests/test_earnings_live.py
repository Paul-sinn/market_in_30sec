"""live: 실제 SEC EDGAR로 실적 추정일(#57)을 계산한다. 기본 실행에서 빠진다(pyproject addopts "-m 'not live'").
기본 종목 중 일반 종목 11개마다 실적 공시 목록 + 헤더 시각(메모리 캐시)을 읽고 earnings_estimate를 계산한다(DB 없음).
단언은 불리언만: 실패 메시지에 본문·User-Agent가 찍히지 않게. 추정이 있는 회사 수는 실제 일정에 따라 흔들려 단언하지 않는다.
실행: SEC_USER_AGENT는 명령 줄 안에서만(파일에 쓰지 않는다)
  SEC_USER_AGENT="<연락처가 든 User-Agent>" uv run pytest -q -m live tests/test_earnings_live.py"""

import os
from datetime import datetime

import pytest

from m30.adapters.edgar import EdgarClient, EdgarEarningsFilingSource, ticker_ciks
from m30.config import ET, SEC_UA_VAR, load_edgar_settings
from m30.coverage import DEFAULT_TICKERS, load_etfs
from m30.models import EarningsEstimate
from m30.pipeline.collect import earnings_window, valid_accepted_at, valid_earnings_accessions
from m30.pipeline.compute import earnings_estimate
from m30.trading_day import is_trading_day, previous_trading_day

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get(SEC_UA_VAR), reason=f"{SEC_UA_VAR} is not set")]


class Counted:
    """EdgarClient.get을 감싸 요청 수를 센다."""

    def __init__(self, get):
        self._get, self.requests = get, 0

    def __call__(self, url):
        self.requests += 1
        return self._get(url)


def test_실제_EDGAR로_기본_종목의_일반_종목마다_실적_추정일을_계산하거나_추정_없음이다():
    today = datetime.now(ET).date()
    day = today if is_trading_day(today) else previous_trading_day(today)
    since, until = earnings_window(day)
    get = Counted(EdgarClient(load_edgar_settings()).get)
    source = EdgarEarningsFilingSource(get)
    ciks, etfs = ticker_ciks(get), {e.ticker for e in load_etfs()}
    companies = sorted({ciks[t] for t in DEFAULT_TICKERS if t not in etfs and t in ciks})

    read_all, lists_valid, times_valid, results_ok = True, True, True, True
    for cik in companies:
        try:
            accessions = source.earnings_accessions(cik, since, until)
            times = {a: source.accepted_at(cik, a) for a in sorted(set(accessions))}  # 접수번호마다 한 번
        except Exception:  # noqa: BLE001 — 예외 메시지(주소)를 찍지 않고 불리언으로만 남긴다
            read_all = False
            continue
        lists_valid &= valid_earnings_accessions(accessions)
        times_valid &= all(valid_accepted_at(at) for at in times.values())
        result = earnings_estimate({a: at for a, at in times.items() if since <= at < until})
        results_ok &= result is None or isinstance(result, EarningsEstimate)

    assert len(companies) == 11, "default stock companies"
    assert read_all, "L1: list or header read failed"
    assert lists_valid, "L2: accession list shape"
    assert times_valid, "L2: header time is not tz-aware"
    assert results_ok, "L3: estimate type"
    assert get.requests <= 1 + 11 + 11 * 8, "L4: SEC requests per run"
