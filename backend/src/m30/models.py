from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class LineStatus(StrEnum):
    CHECKED_FOUND = "checked_found"  # 확인함·있음 (등락률: 계산함)
    CHECKED_NONE = "checked_none"  # 확인함·없음 (조용한 날로 치는 유일한 상태)
    DELAYED = "delayed"  # 지연
    UNSUPPORTED = "unsupported"  # 미지원


class CardStatus(StrEnum):
    NORMAL = "normal"
    FALLBACK = "fallback"  # 축소판 (첫 번째 줄 없음)


@dataclass(frozen=True)
class Coverage:
    ticker: str
    name: str
    leverage: Decimal | None = None  # 레버리지·인버스 배율. 부호 = 방향(음수 = 인버스). 일반 종목은 None
    cik: str | None = None  # 공시 제출 회사 SEC CIK(10자리). 같은 회사의 여러 티커는 같은 값. None = 공시 출처 미지원


class NewsKind(StrEnum):
    """소식 종류(U1 = A). 카드에 직접 보이지 않는다: #6 문장 틀 고르기, #20 놓친 소식 분석. 바꾸면 마이그레이션 CHECK도 같이."""

    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    DEAL = "deal"
    LEADERSHIP = "leadership"
    CAPITAL_RETURN = "capital_return"
    FINANCING = "financing"
    LEGAL = "legal"
    RESTRUCTURING = "restructuring"
    PRODUCT = "product"
    OTHER = "other"


IMPORTANCE_MAX = 5  # U2 = B. 내부 중요도 1~5, 클수록 중요. 바꾸면 마이그레이션 CHECK도 같이


class UnclassifiedReason(StrEnum):
    BATCH_FAILED = "batch_failed"  # 묶음 전체 실패(JSON 2회 깨짐, LLM 호출 실패, 호출 상한)
    MISSING = "missing"  # 응답에 그 공시가 없음(부분 응답)
    UNKNOWN_TICKER = "unknown_ticker"  # 입력에 없던 티커를 붙임 → 버림
    INVALID = "invalid"  # 종류·중요도·의견글 값이 틀림, 같은 id 중복


@dataclass(frozen=True)
class Classification:
    """filing_classification 한 행(공시 × 연결 티커). 분류됨(종류·중요도·의견글) 또는 미분류(사유) 한쪽만."""

    accession: str
    ticker: str
    kind: NewsKind | None = None
    importance: int | None = None
    is_opinion: bool | None = None
    unclassified: UnclassifiedReason | None = None


@dataclass(frozen=True)
class NewsCandidate:
    """첫 번째 줄 후보 하나(분류됨, 의견글 아님)."""

    accession: str
    kind: NewsKind
    importance: int
    amended: bool  # 8-K/A (정정 공시)


@dataclass(frozen=True)
class TickerNews:
    """종목 하나의 첫 번째 줄 데이터 상태와 후보. 상태는 #5가, 문구는 #6이 정한다."""

    status: LineStatus
    candidates: tuple[NewsCandidate, ...] = ()  # 중요도 높은 순 → 접수 시각 늦은 순 → 접수번호


@dataclass(frozen=True)
class CardLine:
    text: str
    status: LineStatus
    checked_at: datetime
    source_scope: str | None  # status가 UNSUPPORTED일 때만 None

    def __post_init__(self) -> None:
        # 시간대 없는 시각은 timestamptz에 세션 시간대(UTC)로 들어가 4~5시간이 조용히 어긋난다
        if self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        if self.source_scope is None and self.status is not LineStatus.UNSUPPORTED:
            raise ValueError("source_scope is required unless status is unsupported")


@dataclass(frozen=True)
class StockCard:
    ticker: str
    trading_day: date
    status: CardStatus
    change_pct: Decimal | None  # 소수 첫째 자리로 반올림된 % 값
    change_status: LineStatus
    news_line: CardLine | None = None  # None = 아직 만들지 않음
    event_line: CardLine | None = None
    price_fact_line: CardLine | None = None
    leverage_tag: str | None = None  # 예: "3x · resets daily". None = 레버리지 상품 아님
    updated_at: datetime | None = None  # DB가 채움. 저장소에서 읽은 카드에만 있음 (ET)
