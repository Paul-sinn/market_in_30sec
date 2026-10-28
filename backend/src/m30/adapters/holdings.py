from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Holding:
    name: str  # N-PORT name 그대로
    cik: str | None  # 발행 회사 CIK 10자리. None = 출처가 찾지 못함
    pct: Decimal  # pctVal: 순자산 대비 %. 음수 = 숏
    asset_category: str | None  # assetCat 그대로("EC" = 보통주)


@dataclass(frozen=True)
class HoldingsReport:
    fund: str  # 요청한 ETF 티커(holdings_ticker)
    accession: str
    period_end: date  # repPdDate
    holdings: tuple[Holding, ...]  # 보고 순서 그대로
    raw: str  # fund_holdings.payload


class HoldingsSource(Protocol):
    def latest_report(self, fund: str) -> HoldingsReport | None:
        """가장 최근 공개 보고. None = 이 ETF를 다루지 않음(미지원). 실패는 SourceError. holdings 순서 무관."""
        ...
