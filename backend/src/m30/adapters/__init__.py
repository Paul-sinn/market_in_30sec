from enum import StrEnum


class Source(StrEnum):
    """외부 출처. 재시도·차단·실패 기록이 출처 단위다."""

    PRICES = "prices"
    EVENTS = "events"
    SEC_FILINGS = "sec_filings"
    INDICATORS = "indicators"
    LLM = "llm"


class SourceError(Exception):
    """외부 출처 실패. 그 출처가 채우는 줄은 지연이 된다. 재시도하지 않는다(응답 형식 오류 등).
    메시지에 키·키가 들어간 URL을 넣지 않는다."""


class TransientSourceError(SourceError):
    """타임아웃·429·5xx·529. 지수 백오프로 최대 3회 다시 시도한다."""


class AccessDeniedError(SourceError):
    """401·403(키 오류, SEC 차단). 재시도하지 않고, 이번 실행에서 그 출처를 더 부르지 않는다. 실행 요약 맨 위."""
