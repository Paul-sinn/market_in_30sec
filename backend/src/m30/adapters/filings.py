import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")  # 접수번호 형식(fullmatch). 수집 검증과 EDGAR 주소 만들기가 같이 쓴다
SIC = re.compile(r"[0-9]{4}")  # SEC 업종 코드 형식(fullmatch). submissions 읽기·수집 검증·DB check가 같다
ANNUAL_REPORT_BODY_MAX = 1_000_000  # 저장하는 10-K 주 문서 글자 수 상한. Item 1은 문서 앞쪽이라 잘리는 건 꼬리다


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


class EarningsFilingSource(Protocol):
    """실적 공시(8-K 중 Item 2.02, 정정 8-K/A 제외) 출처(#57). 실적 추정일 계산 전용. 실패는 SourceError, None은 돌려주지 않는다."""

    def earnings_accessions(self, cik: str, since: datetime, until: datetime) -> list[str]:
        """cik의 실적 공시 접수번호. 출처의 대략 시각으로 [since, until)을 넓게 고른 후보라(EDGAR: 앞뒤 CANDIDATE_MARGIN) 범위 밖이
        섞일 수 있다. 정확한 거르기는 호출부가 accepted_at으로 한다. 순서 보장 없음. [] = 확인했지만 없음."""
        ...

    def accepted_at(self, cik: str, accession: str) -> datetime:
        """그 공시의 실제 접수 시각(tz-aware). EDGAR = 전체 제출 파일 SEC-HEADER의 ACCEPTANCE-DATETIME(동부 벽시계)."""
        ...


class FilingSource(Protocol):
    def filings(self, cik: str, since: datetime, until: datetime) -> list[Filing]:
        """cik가 since 이상 until 미만에 접수한 8-K·8-K/A. 순서 보장 없음. [] = 확인했지만 없음.
        실패는 SourceError(일시 실패 TransientSourceError, 401·403 AccessDeniedError). None은 돌려주지 않는다."""
        ...


@dataclass(frozen=True)
class AnnualReportListing:
    """회사 submissions 한 번에서 읽은 것(#60)."""

    accession: str | None  # recent 중 가장 최근 10-K(form이 정확히 "10-K")의 접수번호. None = recent에 없음
    sic: str | None  # SEC 업종 코드 4자리. None = 없거나 형식 밖(펀드는 "")


@dataclass(frozen=True)
class AnnualReport:
    """sec_annual_report 한 행(#60). #64·#66의 입력."""

    accession: str
    cik: str  # 받은 회사 CIK 10자리
    accepted_at: datetime  # SEC-HEADER 접수 시각, tz-aware(ET)
    body: str  # 주 문서(TYPE 10-K)의 글자: 태그를 뗀 원문, 블록마다 줄바꿈, 앞 ANNUAL_REPORT_BODY_MAX자


class AnnualReportSource(Protocol):
    """10-K 출처(#60). 실패는 SourceError. 저장소를 모른다: '이미 받음' 판단은 호출부(분기 작업)가 한다."""

    def listing(self, cik: str) -> AnnualReportListing:
        """그 회사의 최신 10-K 접수번호와 업종 코드. 요청 1회."""
        ...

    def annual_report(self, cik: str, accession: str) -> AnnualReport:
        """그 10-K의 접수 시각과 주 문서 글자. 요청 1회."""
        ...
