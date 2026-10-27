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
SOURCE_TAG = re.compile(r"\((" + "|".join(map(re.escape, _card["source_tags"])) + r")\)\s*$")

SECOND_PERSON = re.compile(r"\byou(r|rs|'re|'ll|'d)?\b", re.I)
FIRST_PERSON_TRADE = re.compile(r"\b(I|I'm|I've|I'll|we|we're)\s+(\w+\s+)?(buy|bought|buying|sell|sold|selling)\b", re.I)
TRADE_WORD = re.compile(r"\b(buy|bought|buying|sell|sold|selling)\b", re.I)
NUMBER = re.compile(r"(?<![A-Za-z&])[-−+]?\$?\d[\d,]*(\.\d+)?(%|[BMK]\b)?(?![A-Za-z])")
# 숫자처럼 보이지만 값이 아닌 것: 지수 이름, 기간 표기(52-week), 날짜(10/15), 시각(7:30), 공시 서식(8-K, 10-Q, 8-K/A)·항목(Item 2.02)
NOT_A_VALUE = re.compile(
    r"S&P 500|\b\d+-(day|week|month|year)\b|\b\d{1,2}/\d{1,2}\b|\b\d{1,2}:\d{2}\b|\b\d{1,2}-[KQ]\b|\bItem \d\.\d{2}\b", re.I
)
NUMBER_WORDS = _card["number_words"]
_TENS, _UNITS = [w for w in NUMBER_WORDS if w.endswith("ty")], NUMBER_WORDS[:9]  # twenty…ninety, one…nine(목록 앞 아홉 개)
# 십 단위-일 단위(twenty-five)는 한 숫자. 다른 하이픈 뒤(twelve-month, ten-for-one)는 \b에서 끊겨 기수만 센다
NUMBER_WORD = re.compile(rf"\b(({'|'.join(_TENS)})-({'|'.join(_UNITS)})|{'|'.join(NUMBER_WORDS)})\b", re.I)
ONE_OFF = re.compile(r"\bone-(time|off)\b", re.I)  # 값이 아닌 형용사. 지우고 숫자 단어를 센다

HANGUL = re.compile(r"[가-힣]")
MAX_WORDS = 15


_PLAIN = str.maketrans({"‘": "'", "’": "'", "ʼ": "'", "\u2010": "-", "\u2011": "-"})


def _normalize(line: str) -> str:
    # LLM 출력에 흔한 굽은 아포스트로피·특수 하이픈·특수 공백(NBSP 등, \s가 유니코드 공백을 잡는다)을
    # 금지어 목록·정규식이 쓰는 보통 글자로 맞추고 연속 공백은 한 칸으로 줄인다
    return re.sub(r"\s+", " ", line.translate(_PLAIN))


def word_pattern(term: str) -> re.Pattern:
    if HANGUL.search(term):
        # 한국어는 완성형 그대로, 앞뒤에 다른 한글 음절이 붙지 않을 때만 잡는다: "의사세요"·"너도 사랑해"는 통과, "사세요ㅋㅋ"는 차단
        return re.compile(rf"(?<![가-힣]){re.escape(term)}(?![가-힣])")
    # 어미 변화(soars, plunged, crashing, plunging, opportunities, rallied)는 잡고, 다른 단어(buyback, seller)는 잡지 않는다
    forms = [re.escape(term) + "(s|es|d|ed|ing)?"]
    if term.endswith("e"):
        forms.append(re.escape(term[:-1]) + "ing")
    if term.endswith("y"):
        forms.append(re.escape(term[:-1]) + "i(es|ed)")
    return re.compile(rf"\b({'|'.join(forms)})\b", re.I)


def check_card(line: str) -> list[str]:
    """카드 줄·시장 한눈에·아침 알림 검사. 위반 이유 목록, 빈 리스트 = 통과."""
    line = _normalize(line)
    issues = []
    for term in CARD_BANNED + ALWAYS_BANNED:
        if word_pattern(term).search(line):
            issues.append(f"금지어 '{term}'")
    for verb in EMOTION_VERBS:
        if word_pattern(verb).search(line):
            issues.append(f"감정 동사 '{verb}'")
    if SECOND_PERSON.search(line):
        issues.append("2인칭(you/your) — 카드는 사실만 전달")
    # 줄 끝 출처 꼬리표(정해진 목록만)와 "+2 more"는 단어 수에서 뺀다. 다른 괄호는 본문으로 센다
    body = SOURCE_TAG.sub("", line)
    body = re.sub(r"\+\d+ more", "", body)
    words = len(body.split())
    if words > MAX_WORDS:
        issues.append(f"{words}단어 — 최대 {MAX_WORDS}")
    text = NOT_A_VALUE.sub("", body)
    numbers = len(NUMBER.findall(text)) + len(NUMBER_WORD.findall(ONE_OFF.sub("", text)))
    if numbers > 1:
        issues.append(f"숫자 {numbers}개 — 줄당 하나")
    return issues


def check_arena(line: str) -> list[str]:
    """아레나 토크 검사. 위반 이유 목록, 빈 리스트 = 통과."""
    line = _normalize(line)
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
