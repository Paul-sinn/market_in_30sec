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
    news_line_accession: str | None = None  # 첫 번째 줄이 쓴 공시(통과·대체·재발행 줄). 데이터 상태 문구면 None
    previous_trading_day: date | None = None  # 등락률·세 번째 줄의 종가 날짜. 파이프라인은 항상 채운다. None = #16 전 카드


class HoldStage(StrEnum):
    """보류함 행이 걸린 단계. 바꾸면 마이그레이션 enum도 같이."""

    DRAFT = "draft"  # 초안 형식(빈 응답·거절·남은 #·두 문장·15단어 초과·쉼표) 또는 문장 없음(JSON 깨짐·전송 실패·상한·본문 없음)
    NUMBERS = "numbers"  # 숫자 대조
    COPY_RULES = "copy_rules"  # 금지어 검사(m30.copy_rules)
    FACT_CHECK = "fact_check"  # 사실/예측 판정: 예측·의견, 또는 판정 LLM 실패
    AMENDED_FILING = "amended_filing"  # 발행된 카드가 쓴 공시에 정정 공시(8-K/A)가 옴


class HoldState(StrEnum):
    """보류함 처리 상태. 바꾸면 마이그레이션 enum도 같이."""

    PENDING = "pending"  # 대기
    EDITED = "edited"  # 수정됨: edited_text를 썼고 카드는 그대로
    REPUBLISHED = "republished"  # 재발행됨: 카드 첫 번째 줄 = edited_text (DB 트리거)


AMENDED_RULE = "정정 공시 있음"


@dataclass(frozen=True)
class HoldItem:
    """hold_queue 한 행(GLOSSARY HoldQueue)."""

    ticker: str
    trading_day: date
    accession: str  # 이 행을 만든 공시(검수 = 초안의 공시, 정정 = 8-K/A)
    stage: HoldStage
    draft_text: str | None  # 원래 문장(마지막으로 받은 LLM 문장). None = 문장 없음·정정 행
    rules: tuple[str, ...]  # 걸린 규칙. 비지 않는다
    replacement_text: str | None  # 카드에 들어간 대체 줄. 정정 행은 None(카드를 고치지 않는다)
    state: HoldState = HoldState.PENDING
    edited_text: str | None = None  # 사람이 쓴 첫 번째 줄(꼬리표 포함 전체)
