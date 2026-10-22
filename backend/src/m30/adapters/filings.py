import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")  # 접수번호 형식(fullmatch). 수집 검증과 EDGAR 주소 만들기가 같이 쓴다


class FilingForm(StrEnum):
    EIGHT_K = "8-K"
    EIGHT_K_A = "8-K/A"  # 정정 공시. 원래 공시와 접수번호가 다른 새 소식


@dataclass(frozen=True)
class Filing:
    accession: str  # 접수번호 "0000320193-26-000101"
    cik: str  # 제출 회사 CIK, 10자리 "0000320193"
    form: FilingForm
    accepted_at: datetime  # EDGAR 접수 시각, tz-aware
    items: tuple[str, ...]  # 8-K 항목 번호 그대로 ("2.02", "9.01")
    body: str | None  # 8-K 본문 텍스트. None = 읽지 못함
    exhibit99: str | None  # Exhibit 99 텍스트(여럿이면 99.1부터 이어 붙임). None = 없음 또는 읽지 못함
    raw: str  # 출처가 준 원본 그대로. sec_filing.payload에 저장된다
    report_date: date | None = None  # EDGAR reportDate(8-K "Date of Report"). 8-K/A와 원래 공시를 잇는다. None = 출처가 주지 않음


class FilingSource(Protocol):
    def filings(self, cik: str, since: datetime, until: datetime) -> list[Filing]:
        """cik가 since 이상 until 미만에 접수한 8-K·8-K/A. 순서 보장 없음. [] = 확인했지만 없음.
        실패는 SourceError(일시 실패 TransientSourceError, 401·403 AccessDeniedError). None은 돌려주지 않는다."""
        ...
