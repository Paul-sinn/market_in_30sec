"""카드에 나가는 코드 줄(첫 번째 줄의 데이터 상태 문구, 두 번째·세 번째 줄)과 고정 문구. 화면 문구는 이 파일에만 둔다(copy-reviewer 검수 대상)."""

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

from m30.adapters.events import CorporateEvent, Earnings, EarningsTiming
from m30.adapters.prices import DailyBar
from m30.models import CardLine, LineStatus, TickerNews
from m30.pipeline.compute import format_per_share, streak, week52_gaps

# 데이터 상태 문구 (card-copy-rules "데이터 상태 문구")
NO_FILINGS = "No new SEC filings found"
NO_EVENTS = "No confirmed events found"
NO_PRICE_FACTS = "No additional price highlights"  # 가격 데이터가 정상인데 표시 조건에 맞는 사실이 없음
UPDATE_DELAYED = "Update delayed"
NOT_COVERED = "Not covered yet"

# 출처 범위 (카드 하단 "Checked 7:30 AM ET · …"에 쓰인다)
NEWS_SCOPE = "SEC filings"
HOLDINGS_SCOPE = "SEC filings of top holdings"  # ETF 편입 보고를 못 읽은 지연 줄 전용(웹 하단은 확인된 줄만 범위를 보여 준다)
EVENT_SCOPE = "Earnings and dividend calendar"
PRICE_SCOPE = "Daily prices"

# 기준값 (사용자 결정 U1·U3·U4, 2026-10-18)
EVENT_WINDOW = timedelta(days=365)  # U1 = C: 기간 제한 없이 가장 가까운 일정. 조회만 1년 앞까지
STREAK_MIN = 3  # U3: 연속 상승·하락 3일 이상
NEAR_52W_PCT = Decimal("10.0")  # U4 = B: 52주 고점·저점 10% 이내

# 대체 줄: 검수를 통과하지 못한 첫 번째 줄 대신. 8-K 항목 번호로 소식 종류만 밝힌다(보도자료 제목·서식 이름은 쓰지 않는다)
REPLACEMENT_PHRASES = (
    ("2.02", "reported quarterly results"),
    ("5.02", "announced a leadership update"),  # 이사 선임·퇴임, 임원 보수만 다룬 5.02에도 참(executive change는 아님)
    ("1.01", "signed a major agreement"),
    ("2.01", "completed an acquisition or sale"),
)  # 항목이 여럿이면 이 순서로 처음 맞는 것
REPLACEMENT_OTHER = "filed a company update"  # U2: 옛 "filed an 8-K report"는 서식 이름 금지(#22)와 충돌
REPLACEMENT_AMENDED = "updated an earlier report"  # U2: 8-K/A는 항목과 관계없이(없던 인사 변화를 새로 알리지 않게)

_THE = re.compile(r"^The\s+", re.I)
_LEGAL_TAIL = re.compile(
    r"(?:\s*,\s*|\s+)(?:(?:&|and)\s+)?(?:Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|Ltd\.?|Limited|plc|N\.V\.|S\.A\.|L\.P\.)$",
    re.I,
)

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # 고정 튜플: 서버 로캘이 바뀌어도 요일 표기가 같다
TIMING_TEXT = {EarningsTiming.BEFORE_OPEN: "before open", EarningsTiming.AFTER_CLOSE: "after close"}


def holdings_scope(companies: int) -> str:
    """ETF 첫 번째 줄 범위(#10 D6): 확인한 편입 회사 수만 말한다. 10개 중 8개만 찾았는데 전부로 읽히지 않게."""
    return f"SEC filings of {companies} top holding{'' if companies == 1 else 's'}"


def news_template_line(news: TickerNews, checked_at: datetime, scope: str = NEWS_SCOPE) -> CardLine | None:
    """LLM 없이 정해지는 첫 번째 줄(스펙 #6 D2 표). None = 후보가 있다 → 초안·검수(#7)를 기다리는 축소판.
    scope: 확인함·지연 줄의 출처 범위(ETF는 holdings_scope·HOLDINGS_SCOPE)."""
    if news.status is LineStatus.UNSUPPORTED:
        return CardLine(NOT_COVERED, LineStatus.UNSUPPORTED, checked_at, None)
    if news.status is LineStatus.CHECKED_NONE:
        return CardLine(NO_FILINGS, LineStatus.CHECKED_NONE, checked_at, scope)
    if news.status is LineStatus.DELAYED or not news.candidates:
        # U4 = A: 공시가 있는데 후보가 없으면(전부 의견글 = 회사 공시라 분류 오류) "없음"으로 단정하지 않는다
        return delayed_line(scope, checked_at)
    return None


def company_short_name(name: str) -> str:
    """앞 'The '와 끝 법인 꼬리(Inc.·Corp.·Co.·Company·Ltd.·plc 등, 앞 쉼표·&·and 포함)를 반복해서 뗀다. 남는 게 없으면 원래 이름.
    'Best Buy Co., Inc.' → 'Best Buy'. 대체 줄과 종목명 가리기가 같이 쓴다(첫 번째 줄 지시문도 꼬리를 떼고 쓰게 한다)."""
    short = name
    while (cut := _LEGAL_TAIL.sub("", _THE.sub("", short, count=1), count=1)) != short:
        short = cut
    return short.strip() or name


def replacement_sentence(company: str, items: Sequence[str], amended: bool) -> str:
    """대체 줄 문장. 끝 마침표·꼬리표·+N more 없음(조립은 newsline.news_text)."""
    if amended:
        phrase = REPLACEMENT_AMENDED
    else:
        phrase = next((p for item, p in REPLACEMENT_PHRASES if item in items), REPLACEMENT_OTHER)
    return f"{company_short_name(company)} {phrase}"


def event_line(events: Sequence[CorporateEvent] | None, trading_day: date, checked_at: datetime) -> CardLine:
    """None → 미지원. 아니면 [trading_day, trading_day + EVENT_WINDOW] 안에서 가장 가까운 일정 하나
    (같은 날이면 실적, 같은 실적이면 확정 먼저)를 템플릿으로, 없으면 확인함·없음. D-N은 달력일(U2 = A)."""
    if events is None:
        return CardLine(NOT_COVERED, LineStatus.UNSUPPORTED, checked_at, None)
    upcoming = [e for e in events if trading_day <= e.day <= trading_day + EVENT_WINDOW]  # 어댑터가 범위를 어겨도
    if not upcoming:
        return CardLine(NO_EVENTS, LineStatus.CHECKED_NONE, checked_at, EVENT_SCOPE)
    event = min(upcoming, key=lambda e: (e.day, 0, not e.confirmed) if isinstance(e, Earnings) else (e.day, 1, False))
    return CardLine(_event_text(event, trading_day), LineStatus.CHECKED_FOUND, checked_at, EVENT_SCOPE)


def _event_text(event: CorporateEvent, trading_day: date) -> str:
    day = f"{event.day.month}/{event.day.day}"
    if not isinstance(event, Earnings):
        return f"Ex-dividend {day} · {format_per_share(event.amount)}/share"
    timing = "" if event.timing is None else f" {TIMING_TEXT[event.timing]}"
    est = "" if event.confirmed else " (est.)"
    return f"Earnings {WEEKDAYS[event.day.weekday()]} {day}{timing}{est} (D-{(event.day - trading_day).days})"


def is_today_event(text: str, trading_day: date) -> bool:
    """_event_text로 만든 두 번째 줄이 trading_day 일정인지. 실적은 (D-0), 배당락은 M/D로 읽는다.
    shortcut: 일정 창 끝(정확히 365일 뒤) 같은 M/D 배당락도 오늘로 읽힌다, 카드에 일정 날짜 컬럼이 생기면 그 값으로."""
    return text.endswith("(D-0)") or text.startswith(f"Ex-dividend {trading_day.month}/{trading_day.day} ")


def price_fact_line(bars: Sequence[DailyBar], checked_at: datetime) -> CardLine:
    """bars는 bars_usable 통과분. 아래 순서(U5 = A)로 처음 맞는 사실 하나, 없으면 확인함·없음.
    52주 이력이 없으면(상장 1년 미만) 52주 사실은 건너뛴다. 반올림해서 0.0이면 "같음"이다."""
    below, above = week52_gaps(bars) or (None, None)
    days = streak(bars)
    facts = [
        (below == 0, "At 52-week high"),
        (above == 0, "At 52-week low"),
        (days >= STREAK_MIN, f"Up {days} days in a row"),
        (days <= -STREAK_MIN, f"Down {-days} days in a row"),
        (below is not None and below <= NEAR_52W_PCT, f"{below}% below 52-week high"),
        (above is not None and above <= NEAR_52W_PCT, f"{above}% above 52-week low"),
    ]
    text = next((text for found, text in facts if found), None)
    if text is None:
        return CardLine(NO_PRICE_FACTS, LineStatus.CHECKED_NONE, checked_at, PRICE_SCOPE)
    return CardLine(text, LineStatus.CHECKED_FOUND, checked_at, PRICE_SCOPE)


def delayed_line(source_scope: str, checked_at: datetime) -> CardLine:
    return CardLine(UPDATE_DELAYED, LineStatus.DELAYED, checked_at, source_scope)


def leverage_tag(leverage: Decimal | None) -> str | None:
    """None → None. 3.00 → "3x · resets daily", -3.00 → "−3x inverse · resets daily"(U+2212), 1.50 → "1.5x · resets daily"."""
    if leverage is None:
        return None
    multiple = format(abs(leverage).normalize(), "f")  # normalize만 쓰면 10.00이 1E+1이 된다
    return f"{multiple}x · resets daily" if leverage > 0 else f"\u2212{multiple}x inverse · resets daily"
