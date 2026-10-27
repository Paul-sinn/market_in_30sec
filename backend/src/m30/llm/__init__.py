"""LLM 전송 층. 분류(#5)·첫 번째 줄(#6)·사실/예측 판정(#7)은 이 위에 만든 함수다. 가짜도 이 층에 끼운다."""

import json
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


def data_json(value: object) -> str:
    """프롬프트 데이터 블록용 JSON. 분류·첫 번째 줄이 같이 쓴다(인젝션 방어를 한 벌로).
    < > & 를 JSON 이스케이프로: 원문에 닫는 태그가 있어도 블록이 닫히지 않고, JSON으로 읽으면 원문 그대로다."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def json_object_text(text: str) -> str:
    """처음 '{'부터 마지막 '}'까지(둘 다 있고 순서가 맞을 때). 아니면 text 그대로(json.loads가 깨짐으로 본다).
    세 호출(분류·첫 번째 줄·판정)의 답이 모두 JSON 객체 하나라, 펜스(```json·```JSON·``` json·```)·앞 설명·뒤 설명을 한 규칙으로
    벗긴다(변형마다 재시도하면 호출 상한만 쓴다, #14 D4). 객체가 둘이면 여전히 깨짐. 정규식을 쓰지 않는다: 겹치는 \\s*가 긴 공백에서
    백트래킹해 실행이 멈췄다. find·rfind라 선형."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text
