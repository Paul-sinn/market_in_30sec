"""문구 규칙(금지어 검사) 경계값과 스킬 실행기. DB 없이 돈다."""

import subprocess
import sys
from pathlib import Path

import pytest

from m30.copy_rules import check_arena, check_card

EXAMPLES = Path(__file__).resolve().parent / "copy_examples"
SKILL_RUNNER = Path(__file__).resolve().parents[2] / ".claude/skills/card-copy-rules/scripts/check_copy.py"


def example_lines(name: str) -> list[str]:
    """CLI와 같은 규칙: 빈 줄과 # 줄은 뺀다. 빈 파일이 '전부 통과'로 보이지 않게 0줄이면 실패."""
    lines = [s for raw in (EXAMPLES / name).read_text(encoding="utf-8").splitlines() if (s := raw.strip()) and not s.startswith("#")]
    assert lines, f"{name}에 예시 문장이 없다"
    return lines


def test_통과_예시_문장은_카드_문구_규칙에_걸리지_않는다():
    caught = {line: issues for line in example_lines("card_pass.txt") if (issues := check_card(line))}
    assert caught == {}


def test_차단_예시_문장은_하나도_빠짐없이_카드_문구_규칙에_걸린다():
    assert [line for line in example_lines("card_block.txt") if not check_card(line)] == []


# 티켓 #3 완료 기준 3·개정 기준이 이름 붙인 문장 + 단어 수·2인칭 경계 문장. 파일에서 지우면 그 규칙이 무검사가 된다
REQUIRED_EXAMPLES = {
    "card_pass.txt": [
        "Microsoft announced a $60B share buyback (SEC filing)",
        "Intel named a new seller of chips",
        "Apple reported quarterly results. (SEC filing)",
        "Apple announced an executive change. (SEC filing)",
        "Apple signed a major agreement. (SEC filing)",
        "Apple completed an acquisition or sale. (SEC filing)",
        "Apple filed an 8-K report. (SEC filing)",
        "No additional price highlights",
        "Summary arrives tomorrow morning",
        "No new SEC filings found",
        "No confirmed events found",
        "Update delayed",
        "Not covered yet",
        "Market closed today",
        "Checked 7:30 AM ET · SEC filings",
        "Apple announced its board of directors elected a new chair at the annual shareholder meeting (Company)",
        "Microsoft announced its board of directors elected a new chair at the annual meeting +2 more (Company)",
    ],
    "card_block.txt": [
        "Tesla shares soared after the launch (Company)",
        "You should look at this stock",
        "This is a guaranteed winner",
        "Analysts say buy",
        "Apple announced that its board of directors elected a new chair at the annual shareholder meeting (Company)",
        "Your stock filed a new report (SEC filing)",
    ],
}


@pytest.mark.parametrize("name", REQUIRED_EXAMPLES, ids=["통과_예시", "차단_예시"])
def test_완료_기준이_이름_붙인_예시_문장은_예시_파일에서_빠지지_않는다(name):
    lines = example_lines(name)
    assert [s for s in REQUIRED_EXAMPLES[name] if s not in lines] == []


@pytest.mark.parametrize(
    "line, card, arena",
    [
        ("I'm bullish on my mock NVDA position", ["금지어 'bullish'"], []),
        ("This is a guaranteed winner", ["금지어 'guarantee'"], ["금지어 'guarantee'"]),
    ],
    ids=["카드_전용_금지어", "어디서나_차단"],
)
def test_카드는_아레나_금지어도_검사하고_아레나는_카드_금지어를_허용한다(line, card, arena):
    assert (check_card(line), check_arena(line)) == (card, arena)


@pytest.mark.parametrize(
    "line",
    [
        "S&P 500 (SPY) rose 1.2% yesterday",
        "Apple closed 8% below its 52-week high",
        "Ex-dividend 12/21 · $0.70/share",
        "Apple rose 1.3% by 7:30 AM ET",
    ],
    ids=["지수_이름", "기간", "날짜", "시각"],
)
def test_값이_하나뿐이면_지수_이름·기간·날짜·시각_표기는_숫자로_세지_않는다(line):
    # 값이 하나 있는 줄이라, 표기를 값으로 하나라도 세면 숫자 2개 이상이 되어 걸린다
    assert check_card(line) == []


def test_값이_아닌_표기를_빼고도_값이_두_개면_숫자_개수에_걸린다():
    assert check_card("S&P 500 (SPY) rose 1.2% and QQQ rose 0.8%") == ["숫자 2개 — 줄당 하나"]


@pytest.mark.parametrize(
    "mode, line, code, expected",
    [
        ("card", "No new SEC filings found", 0, "위반 0줄"),
        ("card", "Analysts say buy", 1, "[위반] 1: Analysts say buy\n        → 금지어 'buy'"),
        ("arena", "I'm bullish on my mock NVDA position", 0, "위반 0줄"),
    ],
    ids=["card_통과", "card_위반", "arena_통과"],
)
def test_스킬_실행기는_외부_패키지_없이_서버_문구_규칙으로_검사하고_종료_코드로_알린다(mode, line, code, expected):
    # -I -S: 사이트 패키지 없이 실행 = psycopg 없는 시스템 python3와 같은 조건
    r = subprocess.run([sys.executable, "-I", "-S", str(SKILL_RUNNER), "--mode", mode, "-"],
                       input=line + "\n", capture_output=True, text=True, timeout=30)
    assert (r.returncode, expected in r.stdout) == (code, True), r.stdout + r.stderr
