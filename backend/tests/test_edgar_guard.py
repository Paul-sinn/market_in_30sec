"""입구 3: SEC User-Agent(사용자 연락처) 비노출. pytest를 하위 프로세스로 실제로 돌려 출력 전체(traceback·지역 변수 포함)를 본다."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
MARKER = "ua-canary-Q7"  # 가짜 연락처의 일부. 출력에 한 번이라도 나오면 샌 것
PROBE = ["-m", "pytest", "-p", "no:cacheprovider", "--tb=long", "--showlocals", "tests/edgar_probe.py"]


@pytest.mark.parametrize(
    "agent, raised",
    [
        ("M30 Canary ua-canary-Q7@example.invalid", ["TransientSourceError", "AccessDeniedError"]),  # 접속 거부, SEC 403
        ("M30 Canary ua-canary-Q7 no email", ["ConfigError", "SEC_USER_AGENT must be one line"]),  # 설정에서 거부
        ("M30 Canary ua-canary-Q7@example.invalid\r\nX-Injected: 1", ["ConfigError", "SEC_USER_AGENT must be one line"]),
    ],
    ids=["sent", "rejected_no_email", "rejected_newline"],
)
def test_SEC_호출이_실패하거나_설정이_거부해도_User_Agent가_출력·예외·traceback에_남지_않는다(agent, raised):
    env = {**os.environ, "SEC_USER_AGENT": agent}
    r = subprocess.run([sys.executable, *PROBE], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr

    assert r.returncode != 0
    for name in raised:  # 그 경로까지 실제로 갔다(설정 읽기 → 접속, 또는 설정 거부)
        assert name in out
    assert MARKER not in out
