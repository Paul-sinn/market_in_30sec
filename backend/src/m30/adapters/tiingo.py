"""Tiingo 실제 시세 어댑터(#18). 표준 라이브러리만. 다시 시도는 하지 않는다(SourceCalls가 한다). 벤더 확인: docs/vendors/tiingo.md

토큰 노출 방지는 anthropic.py·edgar.py와 같다: 토큰은 TiingoSettings(repr 숨김) 안에만 있고, 헤더는 요청을 만드는 도우미
_request 안에서만 만든다. 토큰은 URL이 아니라 Authorization 헤더로 보낸다(URL은 로그에 찍힐 수 있다).
모든 실패는 상태만 담은 메시지로 from None — 원래 예외(urllib 프레임에 요청 헤더가 있다)를 끊는다."""

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from m30.adapters import SourceError, TransientSourceError, error_for_status
from m30.adapters.edgar import _NoRedirect
from m30.adapters.prices import DailyBar
from m30.config import TiingoSettings

PRICES_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices?{query}"
USER_AGENT = "m30/0.1 (market_in_30sec morning pipeline)"

_OPENER = urllib.request.build_opener(_NoRedirect)  # 리다이렉트로 Authorization이 다른 호스트·http로 가지 않게. 테스트가 패치한다


class TiingoPriceSource:
    """PriceSource 구현. 종목마다 EOD 요청 1회(기간 전체가 한 응답에 온다)."""

    def __init__(self, settings: TiingoSettings, *, timeout: float = 30.0) -> None:
        self._settings = settings
        self._timeout = timeout

    def daily_bars(self, ticker: str, start: date, end: date) -> list[DailyBar]:
        """실패: 401·403 → AccessDeniedError, 429 → RateLimitedError, 5xx·타임아웃·접속 실패 → TransientSourceError,
        그 밖의 HTTP 오류(404 모르는 티커, 30x)·깨진 응답·봉 0개 → SourceError. 모두 그 종목만 지연(SourceCalls)."""
        query = urllib.parse.urlencode({"startDate": start.isoformat(), "endDate": end.isoformat()})
        url = PRICES_URL.format(ticker=urllib.parse.quote(ticker, safe=""), query=query)
        try:
            with _OPENER.open(self._request(url), timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as e:  # URLError의 하위 클래스라 먼저 받는다
            raise error_for_status("tiingo", e.code) from None
        except TimeoutError:
            raise TransientSourceError("tiingo timeout") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):  # 접속 실패·응답 도중 끊김
            raise TransientSourceError("tiingo connection failed") from None
        try:
            bars = _bars(json.loads(body, parse_float=Decimal, parse_constant=Decimal))
        except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):  # 0으로 나누기(splitFactor 0) 포함
            raise SourceError("tiingo response shape") from None
        if not bars:  # 커버 종목은 모두 1년 넘게 상장: 기간이 통째로 비면 벤더 장애·조회 오류다(#18 qa 6c). 조용한 지연으로 묻지 않는다
            raise SourceError("tiingo no bars")
        return bars

    def _request(self, url: str) -> urllib.request.Request:
        """헤더(토큰)는 이 프레임 안에서만 만든다. Request의 repr에는 헤더가 없다."""
        return urllib.request.Request(
            url, headers={"Authorization": f"Token {self._settings.api_key}", "User-Agent": USER_AGENT}
        )


def _bars(rows: object) -> list[DailyBar]:
    """EOD 행(날짜 오름차순) → 분할만 조정한 봉(adjusted=True). 행의 splitFactor는 그날부터 적용된 분할이라 각 봉의 원래
    가격을 그 뒤 봉들의 splitFactor 곱으로 나누고 거래량은 곱한다(정수로 반올림). 배당까지 조정한 adj*는 쓰지 않는다:
    DailyBar 계약(배당 조정 안 함). 순서·값이 이상한 봉은 여기서 고치지 않는다(valid_bars가 그 종목을 지연시킨다)."""
    if not isinstance(rows, list):
        raise TypeError("rows")
    bars = []
    factor = Decimal(1)
    for row in reversed(rows):
        open_, high, low, close = (_number(row[key]) / factor for key in ("open", "high", "low", "close"))
        volume = int((_number(row["volume"]) * factor).to_integral_value(ROUND_HALF_UP))
        bars.append(DailyBar(datetime.fromisoformat(row["date"]).date(), open_, high, low, close, volume, adjusted=True))
        split = _number(row["splitFactor"])
        if split != 1:  # 1을 곱하면 자릿수만 늘어난다
            factor *= split
    return bars[::-1]


def _number(value: object) -> Decimal:
    if type(value) not in (int, Decimal):  # None·문자열·bool은 숫자가 아니다
        raise TypeError("number")
    return Decimal(value)
