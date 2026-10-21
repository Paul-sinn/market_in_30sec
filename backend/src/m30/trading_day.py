"""거래일 계산. 날짜는 date로만 다룬다(시간대 없음, 동부 날짜)."""

from datetime import date, timedelta


def previous_trading_day(day: date) -> date:
    """day 바로 전 거래일.
    shortcut: 주말만 건너뛰고 휴장일은 모른다 → 휴장일 다음 두 거래일은 등락률·세 번째 줄이 지연. #16 거래일 달력이 이 함수를 대체한다"""
    day -= timedelta(days=1)
    while day.weekday() >= 5:  # 토·일
        day -= timedelta(days=1)
    return day
