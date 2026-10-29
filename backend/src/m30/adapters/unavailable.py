"""실제 출처가 아직 없는 자리(운영 모드 전용). 가짜 데이터를 만들지 않고 각 인터페이스 계약의 '없음'을 돌려준다.
예외를 내지 않는다: 미연결은 출처 실패가 아니다(실패로 기록되면 워크플로가 매일 실패로 끝난다)."""

from datetime import date

from m30.adapters.prices import DailyBar


class NoPriceSource:  # 운영 모드에서 TIINGO_API_KEY가 없을 때(유료 구독 전, #18)
    def daily_bars(self, ticker: str, start: date, end: date) -> list[DailyBar]:
        """항상 [] → 등락률 delayed(값 없음), 세 번째 줄 Update delayed."""
        return []


class NoEventSource:  # #21이 실제 일정 어댑터로 바꾼다
    def upcoming_events(self, ticker: str, start: date, end: date) -> None:
        """항상 None(미지원) → 두 번째 줄 Not covered yet."""
        return None


class NoHoldingsSource:  # #10 B가 실제 N-PORT 어댑터로 바꾼다
    def latest_report(self, fund: str) -> None:
        """항상 None(미지원) → ETF 첫 번째 줄 Not covered yet."""
        return None


class NoIndicatorSource:  # 지표 일정 실제 어댑터 티켓이 바꾼다
    def releases(self, start: date, end: date) -> None:
        """항상 None(미지원) → indicator_release 0행, 시장 한눈에 지표 일정 줄 Not covered yet."""
        return None
