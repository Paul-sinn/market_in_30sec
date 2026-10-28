"""실데이터 실험(#20) 종목. HANDOFF 7장. CIK는 SEC 공식 티커 목록에서 채운다(experiment_coverage).
실행기(#26)가 매 실행 전 upsert_coverage(experiment_coverage(ticker_ciks(client.get))). SourceError면 건너뛰고 지난 행을 쓴다.
그다음 add_default_tickers(거래일, EXPERIMENT_DEFAULT_TICKERS): 그 분기 기본 종목(#8 D7). 유저가 0명이면 생성 대상 = 이 15종목."""

import dataclasses
from collections.abc import Mapping
from decimal import Decimal

from m30.adapters import SourceError
from m30.models import Coverage

# 이름은 법인 꼬리를 뗀 흔한 이름(copy-reviewer 교체 목록): 카드 머리글과 첫 번째 줄이 같은 이름을 쓰고, 마침표 꼬리(Inc.·Co.)가
# 문장 끝으로 잡혀 재생성을 쓰지 않게. SEC title은 대문자 정형명(MICROSOFT CORP)이 많아 쓰지 않는다
EXPERIMENT_COVERAGE: tuple[Coverage, ...] = (
    Coverage("AAPL", "Apple"),
    Coverage("MSFT", "Microsoft"),
    Coverage("NVDA", "NVIDIA"),
    Coverage("AMZN", "Amazon"),
    Coverage("GOOGL", "Alphabet"),
    Coverage("META", "Meta"),
    Coverage("TSLA", "Tesla"),
    Coverage("JPM", "JPMorgan Chase"),
    Coverage("XOM", "Exxon Mobil"),
    Coverage("KO", "Coca-Cola"),
    Coverage("PFE", "Pfizer"),
    Coverage("SPY", "SPDR S&P 500 ETF"),
    Coverage("QQQ", "Invesco QQQ"),
    Coverage("TQQQ", "ProShares UltraPro QQQ", leverage=Decimal("3")),
    Coverage("SCHD", "Schwab U.S. Dividend Equity ETF"),
)
# 2026Q4 기본 종목(#8 D7). SPY·QQQ 포함(테스트로 고정). 아레나 종목은 목록이 생기면 포함 검사 추가(#13 보류)
EXPERIMENT_DEFAULT_TICKERS: tuple[str, ...] = tuple(c.ticker for c in EXPERIMENT_COVERAGE)
# U3 = A: ETF는 CIK를 비운다 → 첫 번째 줄 Not covered yet. ETF 카드의 소식은 신탁 공시가 아니라 편입 종목 소식이다(#10)
EXPERIMENT_ETFS = frozenset({"SPY", "QQQ", "TQQQ", "SCHD"})


def experiment_coverage(ciks: Mapping[str, str]) -> list[Coverage]:
    """EXPERIMENT_COVERAGE 순서 그대로, ETF가 아닌 행에 ciks[티커]를 채운다. ETF는 cik=None.
    ETF가 아닌데 ciks에 없으면 SourceError: None으로 채우면 실행기가 지난 좋은 CIK를 덮는다."""
    missing = [c.ticker for c in EXPERIMENT_COVERAGE if c.ticker not in EXPERIMENT_ETFS and c.ticker not in ciks]
    if missing:
        raise SourceError(f"sec ticker list has no {', '.join(missing)}")
    return [c if c.ticker in EXPERIMENT_ETFS else dataclasses.replace(c, cik=ciks[c.ticker]) for c in EXPERIMENT_COVERAGE]
