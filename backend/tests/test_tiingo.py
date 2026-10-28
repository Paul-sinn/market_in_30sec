"""Tiingo 실제 시세 어댑터(#18). 입구 1(아침 파이프라인 + TiingoPriceSource + 가짜 opener) + 어댑터 경계 직접 테스트
(test_edgar와 같은 방식: 응답 → 봉 변환과 요청 모양). 네트워크 없이 돈다.

응답은 녹화가 아니라 손으로 만든 모양이다(docs/vendors/tiingo.md 2-1: 봉 필드 13개, 날짜 오름차순, date는
"YYYY-MM-DDT00:00:00.000Z", 분할일 봉에 splitFactor, 배당락일 봉에 divCash). adj* 값은 일부러 원래 값의 절반으로 넣는다:
어댑터가 배당 조정값(adj*)을 쓰면 테스트가 틀린다."""

import http.client
import io
import json
import traceback
import urllib.error
import urllib.response
from datetime import date
from decimal import Decimal
from email.message import Message

import pytest

from m30.adapters import AccessDeniedError, RateLimitedError, Source, SourceError, TransientSourceError, tiingo
from m30.adapters.edgar import _NoRedirect
from m30.adapters.fake import FakeEventSource, FakeFilingSource, FakeHoldingsSource, FakeIndicatorSource, FakeLLM, Scenario
from m30.adapters.prices import DailyBar
from m30.adapters.tiingo import TiingoPriceSource
from m30.config import ConfigError, load_tiingo_settings
from m30.models import Coverage, LineStatus
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.pipeline.lines import UPDATE_DELAYED
from m30.pipeline.morning import MorningPipeline

TOKEN = "tiingo-Canary-7Kq2xW"  # 가짜 토큰. 출력·예외에 한 번이라도 나오면 샌 것
FRI = date(2026, 10, 16)  # 직전 거래일 10-15, 그 앞 10-14


def test_Tiingo_토큰은_TIINGO_API_KEY_환경_변수에서만_읽고_설정을_찍어도_보이지_않는다():
    settings = load_tiingo_settings({"TIINGO_API_KEY": TOKEN})

    assert settings.api_key == TOKEN
    assert TOKEN not in repr(settings)


@pytest.mark.parametrize("env", [{}, {"TIINGO_API_KEY": ""}], ids=["missing", "empty"])
def test_Tiingo_토큰이_없으면_시세_출처가_없는_것이고_오류가_아니다(env):
    assert load_tiingo_settings(env) is None  # 구독 전(Actions에 secret 없음 = 빈 문자열)


@pytest.mark.parametrize("value", [f"{TOKEN}\n", f"Token {TOKEN}", f"{TOKEN}한"], ids=["newline", "space", "non_ascii"])
def test_Tiingo_토큰이_한_줄_ASCII가_아니면_값을_빼고_설정_오류다(value):
    with pytest.raises(ConfigError) as raised:
        load_tiingo_settings({"TIINGO_API_KEY": value})

    assert str(raised.value) == "TIINGO_API_KEY must be one line of printable ASCII without spaces"


def row(day, close, *, open=None, high=None, low=None, volume=1000, split=1.0, div=0.0):
    """Tiingo EOD 봉 한 행. open·high·low를 안 주면 close. adj*는 원래 값의 절반(쓰면 틀린다)."""
    o, h, low_ = (close if v is None else v for v in (open, high, low))
    return {"date": f"{day}T00:00:00.000Z", "close": close, "high": h, "low": low_, "open": o, "volume": volume,
            "adjClose": close / 2, "adjHigh": h / 2, "adjLow": low_ / 2, "adjOpen": o / 2, "adjVolume": volume * 2,
            "divCash": div, "splitFactor": split}


def body(*rows):
    return json.dumps(list(rows)).encode()


def bar(day, open, high, low, close, volume):
    return DailyBar(date.fromisoformat(day), *(Decimal(str(v)) for v in (open, high, low, close)), volume, adjusted=True)


class TiingoOpener:
    """tiingo._OPENER 자리. 받은 Request를 남기고, 주소의 티커 → 응답 본문(bytes) 또는 예외로 답한다."""

    def __init__(self, responses):
        self.requests, self._responses = [], responses

    def open(self, request, timeout):
        self.requests.append(request)
        outcome = self._responses[request.full_url.split("/")[5]]  # https://api.tiingo.com/tiingo/daily/<티커>/prices?…
        if isinstance(outcome, Exception):
            raise outcome
        return urllib.response.addinfourl(io.BytesIO(outcome), Message(), request.full_url, 200)


def source(monkeypatch, responses):
    opener = TiingoOpener(responses)
    monkeypatch.setattr(tiingo, "_OPENER", opener)
    return TiingoPriceSource(load_tiingo_settings({"TIINGO_API_KEY": TOKEN})), opener


def test_Tiingo_요청은_HTTPS로_종목마다_한_번_기간을_넣고_토큰은_URL이_아니라_Authorization_헤더로_보낸다(monkeypatch):
    prices, opener = source(monkeypatch, {"AAPL": body(row("2026-10-15", 101))})

    prices.daily_bars("AAPL", date(2025, 10, 9), date(2026, 10, 15))

    [request] = opener.requests
    assert request.full_url == "https://api.tiingo.com/tiingo/daily/AAPL/prices?startDate=2025-10-09&endDate=2026-10-15"
    assert request.get_header("Authorization") == f"Token {TOKEN}"
    assert request.get_header("User-agent").startswith("m30/")  # 기본 Python-urllib가 아니다
    assert request.get_method() == "GET"


def test_Tiingo_봉은_원래_시가·고가·저가·종가·거래량을_분할_조정가로_옮긴다(monkeypatch):
    prices, _ = source(monkeypatch, {"AAPL": body(row("2026-10-15", 101.25, open=100.5, high=102.75, low=99.5, volume=45123456))})

    assert prices.daily_bars("AAPL", date(2025, 10, 9), date(2026, 10, 15)) == [
        bar("2026-10-15", "100.5", "102.75", "99.5", "101.25", 45123456)
    ]


def test_10대1·2대1_분할_앞_봉은_뒤_분할_배수의_곱으로_나눠_이어지고_거래량은_곱하며_배당은_반영하지_않는다(monkeypatch):
    prices, _ = source(monkeypatch, {"NVDA": body(
        row("2026-10-05", 2000, open=1990, high=2010, low=1980, volume=100),
        row("2026-10-06", 2020, volume=150),
        row("2026-10-07", 203, volume=1000, split=10.0),  # 이날부터 10:1. 원래 종가가 10분의 1로 뛴다
        row("2026-10-08", 204, volume=1100, div=0.5),  # 배당락일: 원래 종가 그대로(배당 조정 안 함)
        row("2026-10-09", 102.5, volume=2000, split=2.0),  # 이날부터 2:1
    )})

    assert prices.daily_bars("NVDA", date(2025, 10, 9), date(2026, 10, 9)) == [
        bar("2026-10-05", "99.5", "100.5", "99", "100", 2000),  # ÷ 20, 거래량 × 20
        bar("2026-10-06", "101", "101", "101", "101", 3000),
        bar("2026-10-07", "101.5", "101.5", "101.5", "101.5", 2000),  # ÷ 2
        bar("2026-10-08", "102", "102", "102", "102", 2200),
        bar("2026-10-09", "102.5", "102.5", "102.5", "102.5", 2000),
    ]


def test_역분할_앞_봉은_가격을_곱하고_거래량은_반올림한_정수다(monkeypatch):
    prices, _ = source(monkeypatch, {"XYZ": body(row("2026-10-08", 1.5, volume=1005), row("2026-10-09", 15.5, split=0.1))})

    assert prices.daily_bars("XYZ", date(2025, 10, 9), date(2026, 10, 9)) == [
        bar("2026-10-08", "15", "15", "15", "15", 101),  # 1:10 역분할: 1.5 ÷ 0.1, 거래량 1005 × 0.1 = 100.5 → 101
        bar("2026-10-09", "15.5", "15.5", "15.5", "15.5", 1000),
    ]


def run(store, monkeypatch, responses):
    """티커 → Tiingo 응답(본문 또는 예외)으로 FRI 아침 파이프라인을 돌린다. 시세 말고는 가짜(공시·일정 없음).
    돌려주는 값: 실행 요약, 티커 → 저장된 카드, opener(받은 요청)."""
    prices, opener = source(monkeypatch, responses)
    scenario = Scenario(coverage=[Coverage(t, t) for t in responses], prices={})
    store.upsert_coverage(scenario.coverage)
    store.add_default_tickers(FRI, [c.ticker for c in scenario.coverage])  # 유저 없음 → 시나리오 커버 범위 전체가 대상
    summary = MorningPipeline(
        prices=prices,
        events=FakeEventSource(scenario),
        filings=FakeFilingSource(scenario),
        indicators=FakeIndicatorSource(scenario),
        holdings=FakeHoldingsSource(scenario),
        llm=FakeLLM(scenario),
        store=store,
        sleep=lambda seconds: None,
    ).run(FRI)
    return summary, {c.ticker: c for c in store.list_cards(FRI)}, opener


def test_분할일_등락률은_분할_조정한_전일_종가로_배당락일_등락률은_원래_종가로_계산한다(store, monkeypatch):
    summary, cards, opener = run(store, monkeypatch, {
        "NFLX": body(row("2026-10-14", 1000), row("2026-10-15", 101, split=10.0)),  # 원래 값이면 −89.9%
        # 배당 조정값이면 (69.3 − 69.5) / 69.5 = −0.3%
        "KO": body(row("2026-10-14", 70) | {"adjClose": 69.5}, row("2026-10-15", 69.3, div=0.5) | {"adjClose": 69.3}),
    })

    assert {t: (c.change_pct, c.change_status) for t, c in cards.items()} == {
        "NFLX": (Decimal("1.0"), LineStatus.CHECKED_FOUND),
        "KO": (Decimal("-1.0"), LineStatus.CHECKED_FOUND),
    }
    assert summary.failures == ()
    # 종목마다 요청 1회, 53주(52주 사실 + 휴장일 여유)
    assert [r.full_url.split("?")[1] for r in opener.requests] == ["startDate=2025-10-10&endDate=2026-10-15"] * 2


def http_error(status):
    """서버 오류 응답. 최악을 가정해 주소·사유·본문에 토큰을 넣는다(어댑터가 무엇도 옮기면 안 된다)."""
    url = f"https://api.tiingo.com/tiingo/daily/AAPL/prices?token={TOKEN}"
    return urllib.error.HTTPError(url, status, f"reason {TOKEN}", Message(), io.BytesIO(TOKEN.encode()))


NORMAL_DAY = body(row("2026-10-14", 100), row("2026-10-15", 101))
FAILURES = {  # AAPL 응답 → (어댑터 예외 종류, 메시지, AAPL 요청 수, 실패 사유)
    "http_401": (http_error(401), AccessDeniedError, "tiingo http 401", 1, FailureReason.ACCESS_DENIED),
    "http_403": (http_error(403), AccessDeniedError, "tiingo http 403", 1, FailureReason.ACCESS_DENIED),
    "http_429": (http_error(429), RateLimitedError, "tiingo http 429", 4, FailureReason.RETRIES_EXHAUSTED),
    "http_503": (http_error(503), TransientSourceError, "tiingo http 503", 4, FailureReason.RETRIES_EXHAUSTED),
    "http_404": (http_error(404), SourceError, "tiingo http 404", 1, FailureReason.ERROR),  # 모르는 티커
    "http_301": (http_error(301), SourceError, "tiingo http 301", 1, FailureReason.ERROR),  # 리다이렉트를 따라가지 않은 결과
    "timeout": (TimeoutError(TOKEN), TransientSourceError, "tiingo timeout", 4, FailureReason.RETRIES_EXHAUSTED),
    "refused": (urllib.error.URLError(ConnectionRefusedError(TOKEN)), TransientSourceError, "tiingo connection failed", 4,
                FailureReason.RETRIES_EXHAUSTED),
    "cut_off": (http.client.IncompleteRead(TOKEN.encode()), TransientSourceError, "tiingo connection failed", 4,
                FailureReason.RETRIES_EXHAUSTED),
    # 커버 종목은 모두 1년 넘게 상장: 53주가 통째로 비면 벤더 장애·조회 오류다(#18 qa 6c). 조용한 지연으로 묻지 않는다
    "empty_list": (b"[]", SourceError, "tiingo no bars", 1, FailureReason.ERROR),
    "bad_json": (b'[{"date": "2026-10-15', SourceError, "tiingo response shape", 1, FailureReason.ERROR),
    "not_a_list": (b'{"detail": "Error: Ticker not found"}', SourceError, "tiingo response shape", 1, FailureReason.ERROR),
    "deep_json": (b"[" * 100_000, SourceError, "tiingo response shape", 1, FailureReason.ERROR),
    "close_null": (body(row("2026-10-14", 100), row("2026-10-15", 101) | {"close": None}), SourceError,
                   "tiingo response shape", 1, FailureReason.ERROR),
    "close_string": (body(row("2026-10-14", 100), row("2026-10-15", 101) | {"close": "101"}), SourceError,
                     "tiingo response shape", 1, FailureReason.ERROR),
    "no_split_factor": (body(row("2026-10-14", 100), {k: v for k, v in row("2026-10-15", 101).items() if k != "splitFactor"}),
                        SourceError, "tiingo response shape", 1, FailureReason.ERROR),
    "split_factor_0": (body(row("2026-10-14", 100), row("2026-10-15", 101, split=0)), SourceError, "tiingo response shape",
                       1, FailureReason.ERROR),
    "bad_date": (body(row("2026-10-14", 100), row("2026-10-15", 101) | {"date": "10/15/2026"}), SourceError,
                 "tiingo response shape", 1, FailureReason.ERROR),
}


@pytest.mark.parametrize("outcome, error, message, calls, reason", FAILURES.values(), ids=FAILURES.keys())
def test_Tiingo_호출이_실패하거나_응답이_깨지면_그_종목만_지연이고_메시지에_토큰·주소가_없다(
    store, monkeypatch, outcome, error, message, calls, reason
):
    prices, _ = source(monkeypatch, {"AAPL": outcome})
    with pytest.raises(SourceError) as raised:
        prices.daily_bars("AAPL", date(2025, 10, 10), date(2026, 10, 15))
    assert (type(raised.value), str(raised.value)) == (error, message)
    got = raised.value  # 원래 예외(주소·헤더)가 이어져 찍히지 않는다: 끊었거나(from None) 처음부터 없다
    assert got.__cause__ is None and (got.__suppress_context__ or got.__context__ is None)
    assert TOKEN not in "".join(traceback.format_exception(raised.value))

    summary, cards, opener = run(store, monkeypatch, {"AAPL": outcome, "MSFT": NORMAL_DAY})

    denied = error is AccessDeniedError
    assert [r.full_url.split("/")[5] for r in opener.requests] == ["AAPL"] * calls + ([] if denied else ["MSFT"])
    assert summary.failures == tuple(
        SourceFailure(Source.PRICES, t, reason) for t in ["AAPL", *(["MSFT"] if denied else [])]
    )
    assert (cards["AAPL"].change_pct, cards["AAPL"].change_status) == (None, LineStatus.DELAYED)
    assert cards["AAPL"].price_fact_line.text == UPDATE_DELAYED
    if not denied:  # 401·403은 이번 실행에서 시세 출처를 더 부르지 않는다(키 오류)
        assert (cards["MSFT"].change_pct, cards["MSFT"].change_status) == (Decimal("1.0"), LineStatus.CHECKED_FOUND)


BAD_BARS = {  # Tiingo가 보낼 수 있는 이상한 값(JSON NaN·Infinity 포함)
    "close_NaN": row("2026-10-15", float("nan")),
    "high_Infinity": row("2026-10-15", 101, high=float("inf")),
    "close_0": row("2026-10-15", 0),
    "close_above_high": row("2026-10-15", 101, high=100.5),
    "low_above_open": row("2026-10-15", 101, open=99, low=100),
}


@pytest.mark.parametrize("bad", BAD_BARS.values(), ids=BAD_BARS.keys())
def test_Tiingo_봉_값이_NaN·무한대·0·OHLC_불일치면_그_종목만_받은_값_오류로_지연이다(store, monkeypatch, bad):
    summary, cards, _ = run(store, monkeypatch, {"AAPL": body(row("2026-10-14", 100), bad), "MSFT": NORMAL_DAY})

    assert summary.failures == (SourceFailure(Source.PRICES, "AAPL", FailureReason.INVALID_DATA),)
    assert (cards["AAPL"].change_pct, cards["AAPL"].price_fact_line.text) == (None, UPDATE_DELAYED)
    assert cards["MSFT"].change_pct == Decimal("1.0")


def test_Tiingo_리다이렉트는_따라가지_않는다():  # Authorization 헤더가 다른 호스트·http로 따라가지 않게
    assert any(isinstance(h, _NoRedirect) for h in tiingo._OPENER.handlers)  # 실제로 쓰는 opener에 끼워져 있다
