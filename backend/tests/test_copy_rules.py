"""문구 규칙(금지어 검사) 경계값과 스킬 실행기. DB 없이 돈다."""

import subprocess
import sys
from pathlib import Path

import pytest

from m30.copy_rules import check_arena, check_card, check_quiet_fact, check_related

EXAMPLES = Path(__file__).resolve().parent / "copy_examples"
SKILL_RUNNER = Path(__file__).resolve().parents[2] / ".claude/skills/card-copy-rules/scripts/check_copy.py"


def example_lines(name: str) -> list[str]:
    """CLI와 같은 규칙: 빈 줄과 "# " 줄은 뺀다. 빈 파일이 '전부 통과'로 보이지 않게 0줄이면 실패."""
    lines = [s for raw in (EXAMPLES / name).read_text(encoding="utf-8").splitlines() if (s := raw.strip()) and not s.startswith("# ")]
    assert lines, f"{name}에 예시 문장이 없다"
    return lines


def test_통과_예시_문장은_카드_문구_규칙에_걸리지_않는다():
    caught = {line: issues for line in example_lines("card_pass.txt") if (issues := check_card(line))}
    assert caught == {}


def test_차단_예시_문장은_하나도_빠짐없이_카드_문구_규칙에_걸린다():
    assert [line for line in example_lines("card_block.txt") if not check_card(line)] == []


# 티켓 #3·#22 완료 기준이 이름 붙인 문장 + 단어 수·2인칭 경계 문장. 파일에서 지우면 그 규칙이 무검사가 된다
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
        "Apple announced its board of directors elected a new chair at the annual shareholder meeting (SEC filing)",
        "Microsoft announced its board of directors elected a new chair at the annual meeting +2 more (Company)",
        # 티켓 #22: 서식·항목 이름(F5), 한국어 권유와 글자가 겹치는 정상 문장
        "Apple filed an 8-K with Q3 revenue of $94B (SEC filing)",
        "Apple filed an 8-K/A with Q3 revenue of $94B (SEC filing)",
        "Apple filed a 10-Q with Q3 revenue of $94B (SEC filing)",
        "Apple filed Item 2.02 with Q3 revenue of $94B (SEC filing)",
        "너도 사랑해",
        "그분은 의사세요",
        # 티켓 #12: 아침 알림 고정 문구
        "Today's stock cards are ready",
    ],
    "card_block.txt": [
        "Tesla shares soared after the launch (Company)",
        "You should look at this stock",
        "This is a guaranteed winner",
        "Analysts say buy",
        "Apple announced that its board of directors elected a new chair at the annual shareholder meeting (Company)",
        "Your stock filed a new report (SEC filing)",
        # 티켓 #22: F4 괄호 우회, F1·F2 활용형, F3 굽은 아포스트로피, F7 해시태그, F6 연도, 한국어 권유
        "Apple rose 3% (up 5% this week)",
        "Apple rose 3% (Company, 20 analysts upgraded, target $250, up 12% this month)",
        "Apple announced its board of directors elected a new chair at the annual shareholder meeting (per Reuters)",
        "AMD shares plunging after earnings",
        "Big opportunities ahead for Apple",
        "Intel shares tumbling after the forecast (Company)",
        "This can’t lose",
        "#NVDA you should buy now",
        "Apple reported Q3 2026 revenue of $94B (Company)",
        "너도 사",
        "NVDA 지금 사세요",
        "지금 사세요ㅋㅋ",
        # #22 수정 1: 줄 중간 꼬리표, 항목 번호 우회, skyrocket
        "Apple (Company) announced its board of directors elected a new chair at the annual shareholder meeting",
        "Apple rose 3% Item 5.5% more",
        "Palantir shares skyrocketed after earnings (Company)",
        # 티켓 #12: 아침 알림 티커 자리의 금지어
        "BUY: Apple named a new CFO",
    ],
    # 티켓 #66: 알아두기 금지 표현 8개(각각 차단), 피봇 예시를 U1 동사로 고친 문장(통과)
    "quiet_fact_pass.txt": ["NVIDIA makes chips for data centers and gaming (Annual report)"],
    "quiet_fact_block.txt": [
        "Apple is the largest maker of smartphones",
        "Apple is the second-largest maker of smartphones",
        "Apple is a top maker of smartphones",
        "Apple is a leading maker of smartphones",
        "Apple is the biggest maker of smartphones",
        "Apple earns most of its revenue from phones",
        "Apple offers more than phones and computers",
        "Apple is the fastest growing phone maker",
    ],
}


@pytest.mark.parametrize("name", REQUIRED_EXAMPLES, ids=["통과_예시", "차단_예시", "알아두기_통과_예시", "알아두기_차단_예시"])
def test_완료_기준이_이름_붙인_예시_문장은_예시_파일에서_빠지지_않는다(name):
    lines = example_lines(name)
    assert [s for s in REQUIRED_EXAMPLES[name] if s not in lines] == []


@pytest.mark.parametrize(
    "line, card, arena",
    [
        ("I'm bullish on my mock NVDA position", ["금지어 'bullish'"], []),
        ("This is a guaranteed winner", ["금지어 'guarantee'"], ["금지어 'guarantee'"]),
        ("NVDA 지금 사세요", ["금지어 '사세요'"], ["금지어 '사세요'"]),
    ],
    ids=["카드_전용_금지어", "어디서나_차단", "한국어_권유는_어디서나_차단"],
)
def test_카드는_아레나_금지어도_검사하고_아레나는_카드_금지어를_허용한다(line, card, arena):
    assert (check_card(line), check_arena(line)) == (card, arena)


@pytest.mark.parametrize(
    "line, card, arena",
    [
        ("This can’t lose", ["금지어 'can't lose'"], ["금지어 'can't lose'"]),
        ("I’m buying my mock NVDA position", ["금지어 'buy'"], []),
    ],
    ids=["수익_보장_미탐", "아레나_1인칭_모의_동작_오탐"],
)
def test_굽은_아포스트로피는_곧은_아포스트로피와_같게_판정한다(line, card, arena):
    assert (check_card(line), check_arena(line)) == (card, arena)


def test_문장_첫머리_대문자_Buy도_카드_금지어와_아레나_권유_동작으로_잡는다():
    assert (check_card("Buy NVDA now"), check_arena("Buy NVDA now")) == (
        ["금지어 'buy'"],
        ["buy/sell이 1인칭 모의 동작이 아닌 형태로 쓰임"],
    )


@pytest.mark.parametrize(
    "line, banned",
    [
        ("This can\u2018t lose", "can't lose"),  # 여는 따옴표(\u2018)를 아포스트로피로 씀
        ("This can\u02bct lose", "can't lose"),  # 수정자 아포스트로피(\u02bc)
        ("Tesla can’t   lose", "can't lose"),  # 공백 여러 칸
        ("This is risk\u2011free", "risk-free"),  # 줄바꿈 없는 하이픈
        ("This is risk\u2010free", "risk-free"),  # 유니코드 하이픈
        ("NVDA is a sure\u00a0thing", "sure thing"),  # 줄바꿈 없는 공백(NBSP)
        ("너도\u00a0사", "너도 사"),
    ],
    ids=["여는_따옴표", "수정자_아포스트로피", "연속_공백", "줄바꿈_없는_하이픈", "유니코드_하이픈", "NBSP", "한국어_NBSP"],
)
def test_따옴표·공백·하이픈의_유니코드_변형도_금지어로_잡는다(line, banned):
    assert (check_card(line), check_arena(line)) == ([f"금지어 '{banned}'"], [f"금지어 '{banned}'"])


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
    "line",
    [
        "Apple hired twenty-five staff and paid $2B (SEC filing)",
        "Tesla reported trailing twelve-month revenue above $100B (SEC filing)",
        "Apple announced a ten-for-one stock split (SEC filing)",
    ],
    ids=["십_단위_복합은_하나", "기수_뒤_하이픈_단어는_기수만", "10-for-1처럼_둘"],
)
def test_하이픈으로_이은_숫자_단어는_십_단위_복합만_한_숫자로_센다(line):
    assert check_card(line) == ["숫자 2개 — 줄당 하나"]


@pytest.mark.parametrize(
    "mode, line, code, expected",
    [
        ("card", "No new SEC filings found", 0, "위반 0줄"),
        ("card", "Analysts say buy", 1, "[위반] 1: Analysts say buy\n        → 금지어 'buy'"),
        ("arena", "I'm bullish on my mock NVDA position", 0, "위반 0줄"),
        ("arena", "#NVDA you should buy now", 1, "[위반] 1: #NVDA you should buy now"),
        ("card", "# Analysts say buy", 0, "위반 0줄"),
    ],
    ids=["card_통과", "card_위반", "arena_통과", "해시태그로_시작하는_문장은_검사", "샵_공백_주석_줄은_건너뜀"],
)
def test_스킬_실행기는_외부_패키지_없이_서버_문구_규칙으로_검사하고_종료_코드로_알린다(mode, line, code, expected):
    # -I -S: 사이트 패키지 없이 실행 = psycopg 없는 시스템 python3와 같은 조건
    r = subprocess.run([sys.executable, "-I", "-S", str(SKILL_RUNNER), "--mode", mode, "-"],
                       input=line + "\n", capture_output=True, text=True, timeout=30)
    assert (r.returncode, expected in r.stdout) == (code, True), r.stdout + r.stderr


TICKER_15 = "NVDA: Nvidia announced its board of directors elected a new chair at the annual shareholder meeting"  # 티커 + 15단어


def test_카드_줄은_맨_앞_티커도_단어로_센다():
    # 첫 번째 줄은 LLM 초안이라 "NVDA: "로 시작해도 15단어 제한을 비켜 가면 안 된다(#12 수정 1)
    assert check_card(TICKER_15) == ["16단어 — 최대 15"]


@pytest.mark.parametrize("line, issues", [
    (TICKER_15, []),
    ("Revenue grew strongly this quarter: Apple named a new CFO and opened a new office downtown", ["16단어 — 최대 15"]),
], ids=["대문자_티커는_뺀다", "대문자_티커가_아닌_접두는_센다"])
def test_아침_알림은_맨_앞_대문자_티커만_단어_수에서_뺀다(line, issues):
    assert check_card(line, notice=True) == issues


# 알아두기(#66): 카드 규칙 전부 + 숫자 0개 + 순위·비교 표현 + 괄호 없음

def test_통과_예시_문장은_알아두기_문구_규칙에_걸리지_않는다():
    caught = {line: issues for line in example_lines("quiet_fact_pass.txt") if (issues := check_quiet_fact(line))}
    assert caught == {}


def test_차단_예시_문장은_하나도_빠짐없이_알아두기_문구_규칙에_걸린다():
    assert [line for line in example_lines("quiet_fact_block.txt") if not check_quiet_fact(line)] == []


@pytest.mark.parametrize(
    "line, issue",
    [
        ("Apple was founded in 1976", "숫자 — 알아두기는 숫자·연도 없음"),
        ("Apple operates in three regions", "숫자 — 알아두기는 숫자·연도 없음"),
        ("Apple is the second-largest maker of smartphones", "순위·비교·수량 'second'"),
        ("Apple is larger than its rivals", "순위·비교·수량 'than'"),
        ("Apple makes phones (iPhone) and computers", "괄호 — 출처 꼬리표는 웹이 붙인다"),
        ("NVIDIA sells chips for data centers and gaming (Annual report)", "금지어 'sell'"),
        ("Apple serves millions of customers worldwide", "순위·비교·수량 'million'"),
        ("Apple has hundreds of stores", "순위·비교·수량 'hundred'"),
        ("Apple makes better chips", "순위·비교·수량 'better'"),
    ],
    ids=["연도", "숫자_단어", "하이픈_순위", "비교급", "괄호", "카드_금지어", "수량_어림_복수형", "숫자_단어_목록_밖_복수형", "than_없는_비교급"],
)
def test_알아두기는_이유를_코드로_남긴다(line, issue):
    assert issue in check_quiet_fact(line)


def test_알아두기는_one_time처럼_값이_아닌_숫자_단어는_세지_않는다():
    assert check_quiet_fact("Apple offers one-time repair services") == []


def test_알아두기_꼬리표는_카드_줄_단어_수에서도_빠진다():
    fifteen = "Apple announced its board of directors elected a new chair at the annual shareholder meeting"
    assert (check_card(f"{fifteen} (Annual report)"), check_quiet_fact(f"{fifteen} (Annual report)")) == ([], [])


@pytest.mark.parametrize(
    "line, code, expected",
    [
        ("NVIDIA makes chips for data centers and gaming (Annual report)", 0, "위반 0줄"),
        ("Apple is the largest maker of smartphones", 1, "[위반] 1: Apple is the largest maker of smartphones\n        → 순위·비교·수량 'largest'"),
    ],
    ids=["통과", "위반"],
)
def test_스킬_실행기의_quiet_fact_모드는_외부_패키지_없이_알아두기_규칙으로_검사한다(line, code, expected):
    r = subprocess.run([sys.executable, "-I", "-S", str(SKILL_RUNNER), "--mode", "quiet-fact", "-"],
                       input=line + "\n", capture_output=True, text=True, timeout=30)
    assert (r.returncode, expected in r.stdout) == (code, True), r.stdout + r.stderr


# 세 번째 줄 연관 소식(#67): 카드 규칙 전부 + 영향·방향 표현(ADR-0005). 맨 앞 관계 단어는 코드가 붙여 단어 수에서 뺀다

@pytest.mark.parametrize(
    "line, banned",
    [
        ("Competitor AMD reported results that could affect Nvidia (SEC filing)", "could affect"),
        ("Competitor AMD reported a big impact on the chip market (SEC filing)", "impact on"),
        ("Supplier TSMC announced a plant that is good for customers (SEC filing)", "good for"),
        ("Customer Apple filed results that are bad for suppliers (SEC filing)", "bad for"),
        ("Competitor AMD announced prices that put pressure on rivals (SEC filing)", "pressure on"),
        ("Peer Intel said it will benefit from new rules (SEC filing)", "benefit from"),
        ("Competitor AMD named a chip seen as a threat to rivals (SEC filing)", "threat to"),
        ("Peer Intel said it benefited from new rules (SEC filing)", "benefited from"),
        # 조동사만 바꾼 영향 문장(#67 copy-reviewer 항목 3)
        ("Competitor AMD reported results that may affect Nvidia (SEC filing)", "may affect"),
        ("Competitor AMD reported results that might affect rivals (SEC filing)", "might affect"),
        ("Competitor AMD reported results that will affect rivals (SEC filing)", "will affect"),
        ("Competitor AMD said the deal would affect rivals (SEC filing)", "would affect"),
        ("Customer Apple said lower orders may impact suppliers (SEC filing)", "may impact"),
        ("Customer Apple said lower orders might impact suppliers (SEC filing)", "might impact"),
        ("Customer Apple said lower orders could impact suppliers (SEC filing)", "could impact"),
        ("Customer Apple said lower orders will impact suppliers (SEC filing)", "will impact"),
        ("Customer Apple said lower orders would impact suppliers (SEC filing)", "would impact"),
        ("Competitor AMD cut prices in a move that could hurt rivals (SEC filing)", "could hurt"),
        ("Competitor AMD cut prices in a move that may hurt rivals (SEC filing)", "may hurt"),
        ("Competitor AMD cut prices in a move that might hurt rivals (SEC filing)", "might hurt"),
        ("Competitor AMD cut prices in a move that will hurt rivals (SEC filing)", "will hurt"),
        ("Competitor AMD cut prices in a move that would hurt rivals (SEC filing)", "would hurt"),
        # 방향 표현
        ("Supplier TSMC opened a new plant in good news for chip buyers (SEC filing)", "good news for"),
        ("Customer Apple cut orders in bad news for suppliers (SEC filing)", "bad news for"),
        ("Supplier TSMC raised capacity, positive for chip buyers (SEC filing)", "positive for"),
        ("Customer Apple cut orders, negative for suppliers (SEC filing)", "negative for"),
        ("Supplier TSMC opened a new plant in a win for chip buyers (SEC filing)", "win for"),
        ("Customer Apple cut orders in a blow to suppliers (SEC filing)", "blow to"),
        ("Competitor AMD launched a chip seen as a risk to rivals (SEC filing)", "risk to"),
        ("Competitor AMD launched a chip seen among the risks to rivals (SEC filing)", "risks to"),
        ("Supplier TSMC opened a new plant in a boost for chip buyers (SEC filing)", "boost for"),
        ("Customer Apple cut orders, a headwind for suppliers (SEC filing)", "headwind for"),
        ("Customer Apple cut orders, among the headwinds for suppliers (SEC filing)", "headwinds for"),
        ("Supplier TSMC raised capacity, a tailwind for chip buyers (SEC filing)", "tailwind for"),
        ("Supplier TSMC raised capacity, among the tailwinds for chip buyers (SEC filing)", "tailwinds for"),
        ("Customer Apple said lower orders could weigh on suppliers (SEC filing)", "weigh on"),
        ("Customer Apple said lower orders weigh on suppliers (SEC filing)", "weigh on"),
        ("Customer Apple said lower orders weighs on suppliers (SEC filing)", "weighs on"),
        ("Customer Apple said lower orders weighed on suppliers (SEC filing)", "weighed on"),
        ("Customer Apple said lower orders are weighing on suppliers (SEC filing)", "weighing on"),
    ],
    ids=["could_affect", "impact_on", "good_for", "bad_for", "pressure_on", "benefit_from", "threat_to", "benefited_from",
         "may_affect", "might_affect", "will_affect", "would_affect",
         "may_impact", "might_impact", "could_impact", "will_impact", "would_impact",
         "could_hurt", "may_hurt", "might_hurt", "will_hurt", "would_hurt",
         "good_news_for", "bad_news_for", "positive_for", "negative_for", "win_for", "blow_to", "risk_to", "risks_to",
         "boost_for", "headwind_for", "headwinds_for", "tailwind_for", "tailwinds_for",
         "could_weigh_on", "weigh_on", "weighs_on", "weighed_on", "weighing_on"],
)
def test_연관_소식은_영향·방향_표현을_금지어로_잡는다(line, banned):
    assert f"금지어 '{banned}'" in check_related(line)


FIFTEEN = "AMD announced its board of directors elected a new chair at the annual shareholder meeting"  # 15단어


@pytest.mark.parametrize("line, issues", [
    (f"Competitor {FIFTEEN} (SEC filing)", []),
    (f"Competitor {FIFTEEN} today (SEC filing)", ["16단어 — 최대 15"]),
    (f"Rival {FIFTEEN} (SEC filing)", ["16단어 — 최대 15"]),
], ids=["관계_단어_더하기_15단어", "관계_단어_더하기_16단어", "목록_밖_단어는_센다"])
def test_연관_소식은_맨_앞_관계_단어만_단어_수에서_뺀다(line, issues):
    assert check_related(line) == issues


def test_연관_소식_금지_표현은_첫_번째_줄_검사에는_넣지_않는다():
    assert check_card("Apple reported a one-time impact on Q3 revenue of $1B (SEC filing)") == []


def test_통과_예시_문장은_연관_소식_문구_규칙에_걸리지_않는다():
    caught = {line: issues for line in example_lines("related_pass.txt") if (issues := check_related(line))}
    assert caught == {}


def test_차단_예시_문장은_하나도_빠짐없이_연관_소식_문구_규칙에_걸린다():
    assert [line for line in example_lines("related_block.txt") if not check_related(line)] == []


@pytest.mark.parametrize(
    "line, code, expected",
    [
        ("Competitor AMD reported Q3 revenue of $7.7B +1 more (SEC filing)", 0, "위반 0줄"),
        ("Competitor AMD reported results that could affect Nvidia (SEC filing)", 1, "→ 금지어 'could affect'"),
    ],
    ids=["통과", "위반"],
)
def test_스킬_실행기의_related_모드는_외부_패키지_없이_연관_소식_규칙으로_검사한다(line, code, expected):
    r = subprocess.run([sys.executable, "-I", "-S", str(SKILL_RUNNER), "--mode", "related", "-"],
                       input=line + "\n", capture_output=True, text=True, timeout=30)
    assert (r.returncode, expected in r.stdout) == (code, True), r.stdout + r.stderr
