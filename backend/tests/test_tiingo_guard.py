"""입구 3: Tiingo 토큰 비노출. pytest를 하위 프로세스로 실제로 돌려 출력 전체(traceback·지역 변수 포함)를 본다."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
CANARY = "tiingoGuardCanary31"  # 가짜 토큰. 출력에 한 번이라도 나오면 샌 것
PROBE = ["-m", "pytest", "-p", "no:cacheprovider", "--tb=long", "--showlocals", "tests/tiingo_probe.py"]


@pytest.mark.parametrize(
    "token, raised",
    [
        (CANARY, ["TransientSourceError", "AccessDeniedError"]),  # 접속 거부(실제 urllib 경로), Tiingo 401
        (f"{CANARY}\r\nX-Injected: 1", ["ConfigError", "TIINGO_API_KEY must be one line"]),  # 설정에서 거부
    ],
    ids=["sent", "rejected_newline"],
)
def test_Tiingo_호출이_실패하거나_설정이_거부해도_토큰이_출력·예외·traceback에_남지_않는다(token, raised):
    env = {**os.environ, "TIINGO_API_KEY": token}
    r = subprocess.run([sys.executable, *PROBE], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr

    assert r.returncode != 0
    for name in raised:  # 그 경로까지 실제로 갔다(설정 읽기 → 요청, 또는 설정 거부)
        assert name in out
    assert CANARY not in out
