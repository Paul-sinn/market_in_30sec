"""수집: 공시 기간, 외부 호출 창구(재시도·차단·실패 기록), 받은 값 검증."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from m30.adapters import AccessDeniedError, RateLimitedError, Source, SourceError, TransientSourceError
from m30.adapters.events import Earnings, EarningsTiming, ExDividend
from m30.adapters.filings import ACCESSION, Filing, FilingForm
from m30.adapters.indicators import IndicatorRelease
from m30.adapters.prices import DailyBar
from m30.config import ET
from m30.pipeline.compute import round_pct
from m30.trading_day import previous_trading_day

RETRY_DELAYS = (1.0, 2.0, 4.0)  # U5 = A. 길이 = 재시도 횟수(3) → 최대 4번 호출. 지터 없음(서버 1대, 결정적 테스트)
CUTOFF = time(4, 0)  # 수집 시각(HANDOFF 3-6). 공시 기간의 경계
ITEM = re.compile(r"[0-9]\.[0-9]{2}")


def filing_window(trading_day: date) -> tuple[datetime, datetime]:
    """[직전 거래일 04:00 ET, 거래일 04:00 ET). 실행 시각 대신 고정 시각: 재실행해도 같은 공시가 같은 카드로 간다.
    shortcut: previous_trading_day가 휴장일을 모르는 동안(#16 전) 휴장일 다음 거래일 카드는 휴장일 04:00부터 받는다."""
    return datetime.combine(previous_trading_day(trading_day), CUTOFF, ET), datetime.combine(trading_day, CUTOFF, ET)


class FailureReason(StrEnum):
    ACCESS_DENIED = "access_denied"  # 401·403, 또는 이번 실행에서 이미 차단된 출처
    RETRIES_EXHAUSTED = "retries_exhausted"  # 일시 실패 4번
    ERROR = "error"  # 재시도하지 않는 SourceError
    INVALID_DATA = "invalid_data"  # 받은 값이 계약에 안 맞음(타입·형식)


@dataclass(frozen=True, order=True)
class SourceFailure:
    source: Source
    subject: str | None  # 티커(시세·일정), CIK(공시), 묶음 번호(LLM 분류)·접수번호(LLM 첫 번째 줄·판정), None(지표)
    reason: FailureReason


class SourceCalls:
    """한 실행 동안의 외부 호출 창구: 재시도, 401·403 뒤 그 출처 차단, 실패 기록.
    실패 기록에 예외 메시지를 남기지 않는다(실제 어댑터의 메시지에 URL·키가 섞일 수 있다)."""

    def __init__(self, sleep: Callable[[float], None]) -> None:
        self._sleep = sleep
        self._failures: list[SourceFailure] = []
        self._denied: set[Source] = set()
        self._rate_limited: set[Source] = set()

    def call[T](self, source: Source, subject: str | None, fetch: Callable[[], T], valid: Callable[[T], bool]) -> T:
        """최종 실패는 기록 후 그 SourceError를 그대로 올린다. 받은 값이 valid가 아니면 기록 후 SourceError.
        SourceError가 아닌 예외는 기록하지 않고 올린다(버그, LLMCallLimitReached)."""
        try:
            if source in self._denied:  # 차단된 출처를 계속 부르면 SEC 차단이 길어지고 키 오류는 같은 실패만 반복한다
                raise AccessDeniedError(f"{source} denied earlier in this run")
            value = self._retrying(source, fetch)
        except SourceError as e:
            if isinstance(e, AccessDeniedError):
                self._denied.add(source)
            self._failures.append(SourceFailure(source, subject, _reason(e)))
            raise
        if not valid(value):  # 어댑터 반환값은 신뢰 경계. 이상한 값 하나가 실행 전체를 멈추지 않게 그 대상만 지연
            self._failures.append(SourceFailure(source, subject, FailureReason.INVALID_DATA))
            raise SourceError(f"{source} returned invalid data for {subject}")
        return value

    def _retrying[T](self, source: Source, fetch: Callable[[], T]) -> T:
        for delay in RETRY_DELAYS:
            try:
                return self._fetch(source, fetch)
            except TransientSourceError:
                self._sleep(delay)
        return self._fetch(source, fetch)

    def _fetch[T](self, source: Source, fetch: Callable[[], T]) -> T:
        try:
            return fetch()
        except RateLimitedError:  # 다시 시도로 풀려도 남긴다: 429는 요청 간격을 다시 봐야 한다는 신호
            self._rate_limited.add(source)
            raise

    @property
    def access_denied(self) -> tuple[Source, ...]:
        return tuple(sorted(self._denied))

    @property
    def rate_limited(self) -> tuple[Source, ...]:
        """이번 실행에서 429를 한 번이라도 낸 출처. 다시 시도로 성공했어도 남는다."""
        return tuple(sorted(self._rate_limited))

    @property
    def failures(self) -> tuple[SourceFailure, ...]:
        return tuple(sorted(self._failures))


def _reason(error: SourceError) -> FailureReason:
    if isinstance(error, AccessDeniedError):
        return FailureReason.ACCESS_DENIED
    if isinstance(error, TransientSourceError):
        return FailureReason.RETRIES_EXHAUSTED
    return FailureReason.ERROR


# 받은 값 검증: 타입·계약과 데이터 오류. 봉 날짜가 직전 거래일인지는 bars_usable이 본다

# 시세 크기(#18): 이 밖은 상장 주식 시세가 아니라 데이터 오류다. 안이면 두 가격의 비가 1E13 이하라 compute의 모든 %가
# Decimal 28자리 안이다(#6 qa: 전일 종가 1E-30이면 반올림이 InvalidOperation으로 실행 전체를 멈췄다)
PRICE_MIN, PRICE_MAX = Decimal("0.0001"), Decimal("1000000000")
CHANGE_PCT_MAX = Decimal("99999.9")  # stock_card.change_pct numeric(6,1). 넘으면 저장 오류로 실행 전체가 멈춘다


def valid_bars(bars: object) -> bool:
    """봉마다 타입, 가격 크기, OHLC 순서(저가 ≤ 시가·종가 ≤ 고가). 날짜 오름차순이고 하루 등락률(반올림 후)이 DB 범위 안."""
    return (
        isinstance(bars, list)
        and all(
            isinstance(b, DailyBar)
            and _is_day(b.day)
            and all(_is_finite(price) for price in (b.open, b.high, b.low, b.close))  # NaN은 크기 비교에서 예외라 먼저
            and PRICE_MIN <= b.low <= min(b.open, b.close)
            and max(b.open, b.close) <= b.high <= PRICE_MAX
            and type(b.volume) is int  # bool은 아니다
            and b.volume >= 0
            and isinstance(b.adjusted, bool)
            for b in bars
        )
        and all(
            a.day < b.day and abs(round_pct((b.close - a.close) / a.close * 100)) <= CHANGE_PCT_MAX for a, b in pairwise(bars)
        )
    )


def valid_events(events: object) -> bool:
    return events is None or (isinstance(events, list) and all(_valid_event(e) for e in events))


def _valid_event(event: object) -> bool:
    if isinstance(event, Earnings):
        return (
            _is_day(event.day)
            and isinstance(event.confirmed, bool)
            and (event.timing is None or isinstance(event.timing, EarningsTiming))
        )
    return isinstance(event, ExDividend) and _is_day(event.day) and _is_finite(event.amount) and event.amount > 0


def valid_filings(filings: object, cik: str) -> bool:
    return isinstance(filings, list) and all(
        isinstance(f, Filing)
        and isinstance(f.accession, str)
        and ACCESSION.fullmatch(f.accession) is not None
        and f.cik == cik
        and isinstance(f.form, FilingForm)
        and _is_aware(f.accepted_at)
        and isinstance(f.items, tuple)
        and all(isinstance(i, str) and ITEM.fullmatch(i) is not None for i in f.items)
        and all(text is None or _is_text(text) for text in (f.body, f.exhibit99))
        and _is_text(f.raw)
        and f.raw != ""
        and (f.report_date is None or _is_day(f.report_date))
        for f in filings
    )


def valid_releases(releases: object) -> bool:
    return isinstance(releases, list) and all(
        isinstance(r, IndicatorRelease)
        and _is_text(r.name)
        and r.name != ""
        and _is_aware(r.released_at)
        and _is_text(r.raw)
        for r in releases
    )


def _is_text(value: object) -> bool:
    """DB·프롬프트에 그대로 넣을 수 있는 문자열: Postgres text는 NUL을 받지 않고, 짝 없는 서로게이트는 UTF-8이 아니다."""
    if not isinstance(value, str) or "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_day(value: object) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)  # datetime은 date의 하위 클래스다


def _is_finite(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def _is_aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None
