"""거래일 계산(NYSE 달력). 날짜는 date로만 다룬다(시간대 없음, 동부 날짜)."""

from datetime import date, timedelta

# 표가 덮는 해. 매년 NYSE "Holidays & Trading Hours"(nyse.com/markets/hours-calendars)가 다음 해를 실으면 추가한다.
# 2028은 2026-10-27 기준 NYSE가 아직 싣지 않았다(test_거래일_달력은_내년_말까지_있다가 2027년에 알려 준다)
CALENDAR_YEARS = range(2025, 2028)

# 하루 종일 휴장(대체 휴장 포함). 조기 마감일(13:00 ET)은 거래일이고 종가도 정상이라 없다. 임시 휴장은 발표가 나면 손으로 넣는다
NYSE_HOLIDAYS = frozenset(
    date.fromisoformat(d)
    for d in (
        "2025-01-01", "2025-01-09",  # 01-09: Carter 국가 애도일 임시 휴장
        "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01",
        "2025-11-27", "2025-12-25",
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
        "2026-11-26", "2026-12-25",
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
        "2027-11-25", "2027-12-24",
    )
)


class CalendarError(ValueError):
    """달력 표 밖의 해. 휴장일인지 모르면 카드를 만들지 않는다(닫힌 쪽)."""

    def __init__(self, year: int) -> None:
        super().__init__(f"{year} is outside the NYSE holiday table")
        self.year = year


def is_trading_day(day: date) -> bool:
    """평일이고 NYSE_HOLIDAYS에 없다. day.year가 CALENDAR_YEARS 밖이면 CalendarError."""
    if day.year not in CALENDAR_YEARS:
        raise CalendarError(day.year)
    return day.weekday() < 5 and day not in NYSE_HOLIDAYS


def previous_trading_day(day: date) -> date:
    """day 바로 전 거래일(day가 주말·휴장일이어도 된다). 거쳐 가는 날이 표 밖이면 CalendarError."""
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day
