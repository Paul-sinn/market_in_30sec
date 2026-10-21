"""DB 연결 안전장치: 접속 실패 시 비밀번호 비노출, 로컬 전용 가드. pytest·CLI를 하위 프로세스로 실제로 돌려 출력 전체를 본다."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from psycopg.conninfo import make_conninfo

BACKEND = Path(__file__).resolve().parent.parent
CANARY = "Zq9LeakCanary77"  # 가짜 비밀번호. 출력에 한 번이라도 나오면 샌 것
PYTEST_DB_TEST = ["-m", "pytest", "-p", "no:cacheprovider", "--tb=long", "--showlocals",
                  "tests/test_schema.py::test_RLS가_꺼진_테이블이_없다"]
CLI = ["-m", "m30.pipeline", "2026-10-16", "--scenario", "scenarios/first_card.json"]


def run(args, database_url):
    env = {**os.environ, "SUPABASE_DB_URL": database_url}
    r = subprocess.run([sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("args", [PYTEST_DB_TEST, CLI], ids=["pytest", "CLI"])
def test_DB_연결이_실패해도_비밀번호가_출력·예외·traceback에_남지_않는다(settings, args):
    code, out = run(args, make_conninfo(settings.database_url, password=CANARY))  # 로컬 DB, 틀린 비밀번호

    assert code != 0
    assert "DB에 연결하지 못했습니다" in out  # 가드가 아니라 접속 단계까지 가서 실패했다
    assert CANARY not in out


@pytest.mark.parametrize(
    "args, message",
    [(PYTEST_DB_TEST, "SUPABASE_DB_URL이 로컬 DB가 아닙니다"), (CLI, "SUPABASE_DB_URL이 로컬 DB가 아니라 중단합니다")],
    ids=["pytest", "CLI"],
)
def test_로컬이_아닌_DB_주소면_접속하기_전에_멈춘다(args, message):
    code, out = run(args, f"postgresql://postgres:{CANARY}@db.m30-test.invalid:5432/postgres")  # .invalid는 어디로도 안 간다

    assert code != 0
    assert message in out  # 가드 문구 = 접속 시도 전에 멈췄다 (가드가 없으면 접속 실패 문구가 대신 나온다)
    assert CANARY not in out
