"""LLM 전송 층. 분류(#5)·첫 번째 줄(#6)·사실/예측 판정(#7)은 이 위에 만든 함수다. 가짜도 이 층에 끼운다."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMRequest:
    model: str  # config의 모델 상수
    system: str  # 고정 지시문(캐시 대상). 날짜·데이터를 넣지 않는다
    user: str  # 날짜 + 데이터 블록
    max_tokens: int


class LLM(Protocol):
    def complete(self, request: LLMRequest) -> str:
        """응답 텍스트. 실패: 타임아웃·429·5xx·529 → TransientSourceError, 401·403 → AccessDeniedError, 그 외 → SourceError."""
        ...


class LLMCallLimitReached(Exception):
    """실행당 LLM 호출 상한에 닿음. 출처 실패가 아니다(SourceError 아님 → 실패로 기록하지 않는다)."""


class LLMBudget:
    """실행당 LLM 호출 상한(HANDOFF 3-10: 생성 대상 종목 수 × 4 + 분류 묶음 수). 실행마다 하나, 분류·#6·#7이 같이 쓴다.
    U4 = A: 보내는 요청마다 센다(일시 실패 재시도·JSON 재시도 포함)."""

    def __init__(self, llm: LLM, limit: int) -> None:
        self._llm = llm
        self.limit = limit
        self.calls = 0

    def complete(self, request: LLMRequest) -> str:
        """남은 호출이 없으면 부르지 않고 LLMCallLimitReached."""
        if self.calls >= self.limit:
            raise LLMCallLimitReached
        self.calls += 1
        return self._llm.complete(request)
