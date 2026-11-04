"""매일 아침 실행기 워크플로(#26) 텍스트 검사. 네트워크·DB 없이 돈다(YAML 파서 의존성 없이 줄 단위로 본다: run:은 전부 한 줄)."""

import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from m30.config import ET

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "morning.yml"


def text():
    return WORKFLOW.read_text()


def test_예약_실행은_서머타임_앞뒤_모든_평일에_04시_이후_시작해_7시30분_전에_끝난다():
    crons = re.findall(r'^\s*- cron: "([^"]+)"', text(), re.M)
    assert len(crons) == 1
    minute, hour, dom, month, weekdays = crons[0].split()
    assert (dom, month, weekdays) == ("*", "*", "1-5")  # 월~금 (UTC 요일 = 아래에서 확인하는 ET 요일)
    (timeout,) = re.findall(r"^\s*timeout-minutes: (\d+)$", text(), re.M)

    day = date(2026, 1, 1)
    while day <= date(2027, 12, 31):
        if day.weekday() < 5:
            start = datetime(day.year, day.month, day.day, int(hour), int(minute), tzinfo=UTC).astimezone(ET)
            assert start.date() == day, day
            assert start.time() >= time(4, 0), day  # 공시 기간이 닫힌 뒤
            assert start + timedelta(minutes=int(timeout)) <= datetime.combine(day, time(7, 30), ET), day
        day += timedelta(days=1)


def test_수동_실행은_거래일을_비워_둘_수_있다():
    assert re.search(r"^  workflow_dispatch:\n    inputs:\n      trading_day:\n(?:        .*\n)*?        required: false$",
                     text(), re.M)


def test_비밀값은_secrets_넷뿐이고_실행_단계_env로만_넘기며_로그에_찍는_명령이_없다():
    lines = text().splitlines()
    secret_lines = [i for i, line in enumerate(lines) if "secrets." in line]
    names = [re.search(r"secrets\.([A-Z_]+)", lines[i]).group(1) for i in secret_lines]
    assert sorted(names) == ["ANTHROPIC_API_KEY", "DISCORD_WEBHOOK_URL", "SEC_USER_AGENT", "SUPABASE_DB_URL"]  # 각각 한 번씩
    (production,) = [i for i, line in enumerate(lines) if "--production" in line]
    assert all(i > production for i in secret_lines)  # 마지막 단계(실행)의 env: 아래에만. 설치 단계에는 비밀값이 없다
    assert not [line for line in lines if line.strip().startswith(("run:", "- run:")) and "${{" in line]
    for banned in ("set -x", "printenv", "continue-on-error", "|| true", "ACTIONS_STEP_DEBUG", "pull_request", "push:", "shell:"):
        assert banned not in text(), banned


def test_단계는_설치와_운영_실행_둘뿐이고_날짜는_env로만_따옴표로_넘긴다():
    # 단계를 더하면(env 덤프 등) 여기서 걸린다. 날짜는 셸 변수로만, 따옴표로 한 인자: 공백·특수문자가 인자를 늘리지 못한다
    assert re.findall(r"^\s*- run: (.*)$", text(), re.M) == [
        "uv sync --locked --no-dev",
        'uv run --no-sync python -m m30.pipeline --production ${TRADING_DAY:+"$TRADING_DAY"}',
    ]
    assert [u.split("@")[0] for u in re.findall(r"uses: (\S+)", text())] == ["actions/checkout", "astral-sh/setup-uv"]
    assert re.findall(r"^\s*TRADING_DAY: (.*)$", text(), re.M) == ["${{ inputs.trading_day }}"]
    assert text().count("inputs.") == 1


def test_실행_단계는_시작한_이벤트를_env로_넘겨_예약_실행만_완료된_거래일을_건너뛰게_한다():
    # 정시 실행은 Supabase cron의 workflow_dispatch(#43). GitHub schedule은 늦게 오는 예비라 CLI가 RUN_TRIGGER=schedule일 때만 건너뛴다
    lines = text().splitlines()
    (production,) = [i for i, line in enumerate(lines) if "--production" in line]
    assert [line.strip().split(":")[0] for line in lines[production + 1:]] == [
        "env", "TRADING_DAY", "RUN_TRIGGER", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "SEC_USER_AGENT", "DISCORD_WEBHOOK_URL",
        "PRICE_DISPLAY"]  # #56 가격 표시 플래그(vars)
    assert re.findall(r"^\s*RUN_TRIGGER: (.*)$", text(), re.M) == ["${{ github.event_name }}"]


def test_실행은_운영_모드로_한_번에_하나씩_main_전용_environment에서_SHA로_고정한_액션으로_돈다():
    assert re.search(r"^      - run: uv run --no-sync python -m m30\.pipeline --production ", text(), re.M)
    assert re.search(r"^concurrency:\n  group: morning-pipeline(  #.*)?\n  cancel-in-progress: false$", text(), re.M)
    for needed in ("permissions:\n  contents: read", "environment: production", "timeout-minutes: 60", "persist-credentials: false"):
        assert needed in text(), needed
    uses = re.findall(r"uses: (\S+)", text())
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses


def test_가격_표시_플래그는_secrets가_아닌_저장소_변수로_실행_단계에만_넘긴다():
    # #56: 비밀값 아님. 변수가 없으면 빈 문자열 → off(닫힌 쪽). 웹(Vercel)과 같은 이름
    lines = text().splitlines()
    (production,) = [i for i, line in enumerate(lines) if "--production" in line]
    flag = [i for i, line in enumerate(lines) if "PRICE_DISPLAY" in line]
    assert len(flag) == 1 and flag[0] > production
    assert re.match(r"^\s*PRICE_DISPLAY: \$\{\{ vars\.PRICE_DISPLAY \}\}(  #.*)?$", lines[flag[0]])
    assert "secrets.PRICE_DISPLAY" not in text()


# 분기 작업(#60) 워크플로. 아침 실행과 따로 돈다
QUARTERLY = WORKFLOW.parent / "quarterly.yml"


def quarterly_text():
    return QUARTERLY.read_text()


def test_분기_작업_예약은_일요일이라_평일_아침_실행과_겹치지_않고_수동_실행이_있다():
    crons = re.findall(r'^\s*- cron: "([^"]+)"', quarterly_text(), re.M)
    assert len(crons) == 1
    minute, hour, dom, month, weekdays = crons[0].split()
    assert (dom, month, weekdays) == ("*", "*", "0")  # 일요일만(UTC). 아침 실행은 월~금
    (timeout,) = re.findall(r"^\s*timeout-minutes: (\d+)(?:  #.*)?$", quarterly_text(), re.M)
    start = datetime(2026, 11, 8, int(hour), int(minute), tzinfo=UTC)  # 일요일
    assert (start + timedelta(minutes=int(timeout))).date() == start.date()  # 한도까지 돌아도 월요일 아침 실행 전에 끝난다
    assert re.search(r"^  workflow_dispatch:", quarterly_text(), re.M)
    assert "inputs." not in quarterly_text()  # 수동 실행 입력 없음


def test_분기_작업_비밀값은_DB_주소와_SEC_연락처_둘뿐이고_실행_단계_env로만_넘긴다():
    lines = quarterly_text().splitlines()
    secret_lines = [i for i, line in enumerate(lines) if "secrets." in line]
    assert sorted(re.search(r"secrets\.([A-Z_]+)", lines[i]).group(1) for i in secret_lines) == ["SEC_USER_AGENT", "SUPABASE_DB_URL"]
    (run,) = [i for i, line in enumerate(lines) if "--quarterly" in line]
    assert all(i > run for i in secret_lines)  # 실행 단계 env: 아래에만. 설치 단계에는 비밀값이 없다
    assert not [line for line in lines if line.strip().startswith(("run:", "- run:")) and "${{" in line]
    for banned in ("set -x", "printenv", "continue-on-error", "|| true", "ACTIONS_STEP_DEBUG", "pull_request", "push:", "shell:"):
        assert banned not in quarterly_text(), banned


def test_분기_작업_단계는_설치와_분기_작업_실행_둘뿐이다():
    assert re.findall(r"^\s*- run: (.*)$", quarterly_text(), re.M) == [
        "uv sync --locked --no-dev",
        "uv run --no-sync python -m m30.pipeline --quarterly",
    ]
    uses = re.findall(r"uses: (\S+)", quarterly_text())
    assert [u.split("@")[0] for u in uses] == ["actions/checkout", "astral-sh/setup-uv"]
    assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses


def test_분기_작업은_아침_실행과_다른_concurrency_그룹에서_main_전용_environment로_돈다():
    # 같은 그룹이면 2시간짜리 분기 작업 뒤에 아침 실행이 줄을 서거나 대기 중인 실행이 취소된다
    assert re.search(r"^concurrency:\n  group: quarterly-job(  #.*)?\n  cancel-in-progress: false$", quarterly_text(), re.M)
    assert "morning-pipeline" not in quarterly_text()
    for needed in ("permissions:\n  contents: read", "environment: production", "persist-credentials: false"):
        assert needed in quarterly_text(), needed
