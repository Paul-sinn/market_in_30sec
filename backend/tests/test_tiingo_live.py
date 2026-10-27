"""live: 실제 Tiingo 호출 1회(SPY 53주). 기본 실행에서 빠진다(pyproject addopts "-m 'not live'").
응답 모양만 본다. 단언은 불리언만: 실패 메시지에 가격·토큰이 찍히지 않게. 무료 키로 받은 시세는 이 프로세스 메모리에만 있다.
실행: TIINGO_API_KEY를 셸에서 export한 뒤(값을 명령에 쓰지 않는다) uv run pytest -q -m live tests/test_tiingo_live.py"""

import os
from datetime import datetime, timedelta

import pytest

from m30.adapters.tiingo import TiingoPriceSource
from m30.config import ET, TIINGO_KEY_VAR, load_tiingo_settings
from m30.pipeline.collect import valid_bars
from m30.pipeline.morning import LOOKBACK

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get(TIINGO_KEY_VAR), reason=f"{TIINGO_KEY_VAR} is not set")]


def test_실제_Tiingo에서_SPY_53주_봉을_분할_조정가_계약대로_받는다():
    today = datetime.now(ET).date()
    bars = TiingoPriceSource(load_tiingo_settings()).daily_bars("SPY", today - LOOKBACK, today - timedelta(days=1))

    # 단언 전에 참/거짓으로 만든다: pytest가 실패 설명에 DailyBar repr(가격)을 찍지 않게
    valid = valid_bars(bars)  # 타입·가격 크기·OHLC 순서·날짜 오름차순·하루 등락률 범위
    year = len(bars) >= 250  # 53주 ≈ 265 거래일
    adjusted = all(b.adjusted for b in bars)
    starts = len(bars) > 0 and bars[0].day >= today - LOOKBACK
    recent = len(bars) > 0 and bars[-1].day >= today - timedelta(days=7)  # 연휴가 길어도 1주 안
    assert valid, "bars fail valid_bars"
    assert year, "fewer than 250 bars"
    assert adjusted, "adjusted flag"
    assert starts, "bar before startDate"
    assert recent, "latest bar older than a week"
