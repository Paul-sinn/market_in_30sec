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
        "env", "TRADING_DAY", "RUN_TRIGGER", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "SEC_USER_AGENT", "DISCORD_WEBHOOK_URL"]
    assert re.findall(r"^\s*RUN_TRIGGER: (.*)$", text(), re.M) == ["${{ github.event_name }}"]


def test_실행은_운영_모드로_한_번에_하나씩_main_전용_environment에서_SHA로_고정한_액션으로_돈다():
    assert re.search(r"^      - run: uv run --no-sync python -m m30\.pipeline --production ", text(), re.M)
    assert re.search(r"^concurrency:\n  group: morning-pipeline(  #.*)?\n  cancel-in-progress: false$", text(), re.M)
    for needed in ("permissions:\n  contents: read", "environment: production", "timeout-minutes: 60", "persist-credentials: false"):
        assert needed in text(), needed
    uses = re.findall(r"uses: (\S+)", text())
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses
