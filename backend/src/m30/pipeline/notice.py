"""아침 알림 문구(#12): 유저 한 명의 한 문장. LLM을 부르지 않고 그날 카드의 줄로 조합한다. 고정 문구는 copy-reviewer 검수 대상."""

import re
from collections.abc import Mapping, Sequence
from datetime import date

from m30.copy_rules import SOURCE_TAG, check_card
from m30.models import CardLine, LineStatus, Plan, StockCard
from m30.pipeline.lines import is_today_event

# 후보가 없는 날과 금지어 검사에 걸린 날. "아무 일 없음"으로 단정하지 않는다(지연·미지원도 여기로 온다)
QUIET_NOTICE = "Today's stock cards are ready"

NOTICE_MAX = 100  # 글자 수. DB CHECK도 같은 값

_CARD_MORE = re.compile(r"\s*\+\d+ more$")


def morning_notice(cards: Sequence[StockCard], importance: Mapping[str, int], plan: Plan, trading_day: date) -> str:
    """cards = 유저의 잠기지 않은 내 종목의 그날 카드. importance = 티커 → 첫 번째 줄 공시의 내부 중요도.
    "TICKER: <문장> +N more". N = 오늘 일정이나 첫 번째 줄 소식이 있는 다른 내 종목 수(가격 사실만 있는 종목은 세지 않는다)."""
    found = []  # (순위 키, 티커, 문장). ① 오늘 일정 → ② 내부 중요도 높은 첫 번째 줄 → ③ 가격 사실(Plus만), 같으면 티커 순
    for card in (c for c in cards if not c.publish_suspended):  # 발행 중단 카드는 후보도 N도 아니다. 지연·미지원 줄은 _found가 뺀다
        if _found(card.event_line) and is_today_event(card.event_line.text, trading_day):
            found.append(((0, 0), card.ticker, card.event_line.text))
        if _found(card.news_line):
            found.append(((1, -importance.get(card.ticker, 0)), card.ticker, _news_sentence(card.news_line.text)))
        if plan is Plan.PLUS and _found(card.price_fact_line):  # 무료 유저에게 세 번째 줄은 잠금(#9)
            found.append(((2, 0), card.ticker, card.price_fact_line.text))
    if not found:
        return QUIET_NOTICE
    _, ticker, sentence = min(found)
    more = len({t for (rank, _), t, _ in found if rank < 2} - {ticker})
    tail = f" +{more} more" if more else ""
    full = f"{ticker}: {sentence}{tail}"
    notice = full if len(full) <= NOTICE_MAX else f"{ticker}: {_cut(sentence, NOTICE_MAX - len(full) + len(sentence))}{tail}"
    # 자르기 전과 뒤를 둘 다 검사한다(닫힌 쪽): 잘려 나간 꼬리의 금지어도, 잘라서 생긴 위반도 고정 문구로
    return QUIET_NOTICE if check_card(full, notice=True) or check_card(notice, notice=True) else notice


def _cut(sentence: str, room: int) -> str:
    """room자(… 포함) 안에서 단어 경계로 자르고 …를 붙인다. 경계가 없는 한 단어면 글자에서 자른다."""
    head = sentence[:room]
    kept = head.rsplit(" ", 1)[0] if " " in head else head[:-1]
    return kept.rstrip(" ,;:") + "…"


def _found(line: CardLine | None) -> bool:
    return line is not None and line.status is LineStatus.CHECKED_FOUND


def _news_sentence(text: str) -> str:
    """카드 첫 번째 줄에서 끝 출처 꼬리표와 그 종목의 +N more를 뗀다(알림의 +N more는 다른 종목 수)."""
    return _CARD_MORE.sub("", SOURCE_TAG.sub("", text).rstrip())
