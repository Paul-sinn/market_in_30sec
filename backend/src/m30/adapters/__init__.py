from enum import StrEnum


class Source(StrEnum):
    """외부 출처. 재시도·차단·실패 기록이 출처 단위다."""

    PRICES = "prices"
    EVENTS = "events"
    SEC_FILINGS = "sec_filings"
    INDICATORS = "indicators"
    HOLDINGS = "holdings"  # ETF 편입 종목 보고(N-PORT). 대상 = 편입을 읽을 ETF 티커
    MARKET_NEWS = "market_news"  # 시장 전체 소식(공식 발표, #11). 대상 없음
    LLM = "llm"


class SourceError(Exception):
    """외부 출처 실패. 그 출처가 채우는 줄은 지연이 된다. 재시도하지 않는다(응답 형식 오류 등).
    메시지에 키·키가 들어간 URL을 넣지 않는다."""


class TransientSourceError(SourceError):
    """타임아웃·429·5xx·529. 지수 백오프로 최대 3회 다시 시도한다."""


class AccessDeniedError(SourceError):
    """401·403(키 오류, SEC 차단). 재시도하지 않고, 이번 실행에서 그 출처를 더 부르지 않는다. 실행 요약 맨 위."""


class RateLimitedError(TransientSourceError):
    """429. 일시 실패처럼 다시 시도하고, 이번 실행에서 429를 낸 출처는 실행 요약 rate_limited에 남는다."""


def error_for_status(label: str, status: int) -> SourceError:
    """401·403 → AccessDeniedError, 429 → RateLimitedError, 500~599(529 포함) → TransientSourceError, 그 외(30x 포함) →
    SourceError. 메시지는 f"{label} http {status}"뿐(응답 본문·헤더·URL 없음). Anthropic·SEC가 같이 쓴다(HANDOFF 3-10 한 벌)."""
    message = f"{label} http {status}"
    if status in (401, 403):
        return AccessDeniedError(message)
    if status == 429:
        return RateLimitedError(message)
    if 500 <= status <= 599:
        return TransientSourceError(message)
    return SourceError(message)
