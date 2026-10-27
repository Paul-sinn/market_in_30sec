"""실제 출처가 아직 없는 자리(운영 모드 전용). 가짜 데이터를 만들지 않고 각 인터페이스 계약의 '없음'을 돌려준다.
예외를 내지 않는다: 미연결은 출처 실패가 아니다(실패로 기록되면 워크플로가 매일 실패로 끝난다)."""

from datetime import date

from m30.adapters.indicators import IndicatorRelease
from m30.adapters.prices import DailyBar


class NoPriceSource:  # 운영 모드에서 TIINGO_API_KEY가 없을 때(유료 구독 전, #18)
    def daily_bars(self, ticker: str, start: date, end: date) -> list[DailyBar]:
        """항상 [] → 등락률 delayed(값 없음), 세 번째 줄 Update delayed."""
        return []


class NoEventSource:  # #21이 실제 일정 어댑터로 바꾼다
    def upcoming_events(self, ticker: str, start: date, end: date) -> None:
        """항상 None(미지원) → 두 번째 줄 Not covered yet."""
        return None


class NoIndicatorSource:
    def releases(self, start: date, end: date) -> list[IndicatorRelease]:
        """항상 [] → indicator_release 0행. 카드 줄 없음.
        shortcut: 출처가 없는데 '확인함·없음'을 돌려준다, 지표를 읽는 기능(#11) 전에 실제 출처로 바꾼다."""
        return []
