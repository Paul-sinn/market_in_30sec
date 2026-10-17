#!/usr/bin/env python3
"""앱에 나가는 문장을 규칙으로 검사한다. 한 줄 = 문장 하나.

Usage:
    python3 check_copy.py --mode card  FILE   # 카드 줄, 시장 한눈에, 아침 알림
    python3 check_copy.py --mode arena FILE   # 아레나 토크
    echo "Apple rose 3%." | python3 check_copy.py --mode card -

Exit code: 0 = 위반 없음, 1 = 위반 있음. 스크립트가 못 잡는 규칙(사실/예측 구분,
근거 출처의 정확성)은 사람이나 copy-reviewer가 따로 판정한다.
"""

import argparse
import re
import sys

# HANDOFF 3-3 금지어. 카드·알림·시장 한눈에 공통
CARD_BANNED = [
    "buy", "sell", "should", "bullish", "bearish", "likely to rise", "upside",
    "downside", "opportunity", "undervalued", "overvalued", "momentum",
    "breakout", "rally ahead",
]
EMOTION_VERBS = ["soar", "plunge", "skyrocket", "crash", "tank"]

# 아레나: 캐릭터 말투(bullish, momentum 등)와 1인칭 모의 동작은 허용.
# 아래는 어디서든 차단
ALWAYS_BANNED = [
    "you should", "you must", "guarantee", "risk-free", "can't lose",
    "cannot lose", "sure thing", "easy money", "get rich", "double your money",
]
SECOND_PERSON = re.compile(r"\byou(r|rs|'re|'ll|'d)?\b", re.I)
FIRST_PERSON_TRADE = re.compile(r"\b(I|I'm|I've|I'll|we|we're)\s+(\w+\s+)?(buy|bought|buying|sell|sold|selling)\b", re.I)
TRADE_WORD = re.compile(r"\b(buy|bought|buying|sell|sold|selling)\b", re.I)
NUMBER = re.compile(r"(?<![A-Za-z&])[-−+]?\$?\d[\d,]*(\.\d+)?(%|[BMK]\b)?(?![A-Za-z])")
# 숫자처럼 보이지만 값이 아닌 것: 지수 이름, 기간 표기(52-week), 날짜(10/15)
NOT_A_VALUE = re.compile(r"S&P 500|\b\d+-(day|week|month|year)\b|\b\d{1,2}/\d{1,2}\b", re.I)

MAX_WORDS = 15


def word_pattern(term: str) -> re.Pattern:
    # 어미 변화(soars, plunged, crashing)는 잡고, 다른 단어(buyback, seller)는 잡지 않는다
    return re.compile(rf"\b{re.escape(term)}(s|es|d|ed|ing)?\b", re.I)


def check_card(line: str) -> list[str]:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["card", "arena"], required=True)
    parser.add_argument("file", help="검사할 파일. '-'이면 표준 입력")
    args = parser.parse_args()

    stream = sys.stdin if args.file == "-" else open(args.file, encoding="utf-8")
    check = check_card if args.mode == "card" else check_arena

    violations = 0
    for num, raw in enumerate(stream, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        issues = check(line)
        if issues:
            violations += 1
            print(f"[위반] {num}: {line}\n        → " + "; ".join(issues))
    print(f"\n위반 {violations}줄")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
