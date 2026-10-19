"""앱에 나가는 문장의 문구 규칙 검사. 한 줄 = 문장 하나.
표준 라이브러리만 import한다: 스킬 실행기(check_copy.py)가 uv 없이 시스템 python3로 부른다."""

import re
import tomllib
from importlib.resources import files


def _read(name: str) -> dict:
    return tomllib.loads(files(__name__).joinpath(name).read_text(encoding="utf-8"))


# 금지어 목록은 데이터 파일에만 있다. 키가 빠지면 import 때 KeyError로 멈춘다(검사가 조용히 비지 않게)
_card, _arena = _read("card.toml"), _read("arena.toml")
CARD_BANNED = _card["banned"]
EMOTION_VERBS = _card["emotion_verbs"]
ALWAYS_BANNED = _arena["always_banned"]

SECOND_PERSON = re.compile(r"\byou(r|rs|'re|'ll|'d)?\b", re.I)
FIRST_PERSON_TRADE = re.compile(r"\b(I|I'm|I've|I'll|we|we're)\s+(\w+\s+)?(buy|bought|buying|sell|sold|selling)\b", re.I)
TRADE_WORD = re.compile(r"\b(buy|bought|buying|sell|sold|selling)\b", re.I)
NUMBER = re.compile(r"(?<![A-Za-z&])[-−+]?\$?\d[\d,]*(\.\d+)?(%|[BMK]\b)?(?![A-Za-z])")
# 숫자처럼 보이지만 값이 아닌 것: 지수 이름, 기간 표기(52-week), 날짜(10/15), 시각(7:30)
NOT_A_VALUE = re.compile(r"S&P 500|\b\d+-(day|week|month|year)\b|\b\d{1,2}/\d{1,2}\b|\b\d{1,2}:\d{2}\b", re.I)

MAX_WORDS = 15


def word_pattern(term: str) -> re.Pattern:
    # 어미 변화(soars, plunged, crashing)는 잡고, 다른 단어(buyback, seller)는 잡지 않는다
    return re.compile(rf"\b{re.escape(term)}(s|es|d|ed|ing)?\b", re.I)


def check_card(line: str) -> list[str]:
    """카드 줄·시장 한눈에·아침 알림 검사. 위반 이유 목록, 빈 리스트 = 통과."""
    issues = []
    for term in CARD_BANNED + ALWAYS_BANNED:
        if word_pattern(term).search(line):
            issues.append(f"금지어 '{term}'")
    for verb in EMOTION_VERBS:
        if word_pattern(verb).search(line):
            issues.append(f"감정 동사 '{verb}'")
    if SECOND_PERSON.search(line):
        issues.append("2인칭(you/your) — 카드는 사실만 전달")
    # 출처 꼬리표 "(SEC filing)"와 "+2 more"는 단어 수에서 뺀다
    body = re.sub(r"\([^)]*\)\s*$", "", line)
    body = re.sub(r"\+\d+ more", "", body)
    words = len(body.split())
    if words > MAX_WORDS:
        issues.append(f"{words}단어 — 최대 {MAX_WORDS}")
    numbers = NUMBER.findall(NOT_A_VALUE.sub("", body))
    if len(numbers) > 1:
        issues.append(f"숫자 {len(numbers)}개 — 줄당 하나")
    return issues


def check_arena(line: str) -> list[str]:
    """아레나 토크 검사. 위반 이유 목록, 빈 리스트 = 통과."""
    issues = []
    for term in ALWAYS_BANNED:
        if word_pattern(term).search(line):
            issues.append(f"금지어 '{term}'")
    if SECOND_PERSON.search(line):
        issues.append("2인칭(you/your) — 권유·유저 보유종목 언급 금지")
    trades = len(TRADE_WORD.findall(line))
    first_person = len(FIRST_PERSON_TRADE.findall(line))
    if trades > first_person:
        issues.append("buy/sell이 1인칭 모의 동작이 아닌 형태로 쓰임")
    return issues
