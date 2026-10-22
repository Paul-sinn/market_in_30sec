"""입구 3: 설정 읽기가 거부할 때 비밀값 비노출. 거부 경로 traceback(pytest --showlocals)에 환경 전체(os.environ)나 값이 찍히면
다른 비밀값까지 샌다. pytest를 하위 프로세스로 실제로 돌려 출력 전체를 본다."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
MARKERS = ("Zq9CfgCanary", "ua-canary-Q7")  # 아래 가짜 값의 일부. 출력에 한 번이라도 나오면 샌 것
CANARIES = {
    "SUPABASE_DB_URL": "postgresql://postgres:Zq9CfgCanaryPw@127.0.0.1:54322/postgres",
    "ANTHROPIC_API_KEY": "sk-ant-Zq9CfgCanaryKey",
    "SEC_USER_AGENT": "M30 Canary ua-canary-Q7@example.invalid",
}


@pytest.mark.parametrize(
    "probe, change, message",
    [
        ("test_DB_설정을_읽는다", {"SUPABASE_DB_URL": None}, "SUPABASE_DB_URL is not set"),
        ("test_Anthropic_설정을_읽는다", {"ANTHROPIC_API_KEY": None}, "ANTHROPIC_API_KEY is not set"),
        ("test_Anthropic_설정을_읽는다", {"ANTHROPIC_API_KEY": "sk-ant-Zq9CfgCanaryKey\n"}, "ANTHROPIC_API_KEY must be one line"),
        ("test_Anthropic_설정을_읽는다", {"ANTHROPIC_API_KEY": "sk-ant-Zq9Cfg CanaryKey"}, "ANTHROPIC_API_KEY must be one line"),
        ("test_SEC_설정을_읽는다", {"SEC_USER_AGENT": None}, "SEC_USER_AGENT is not set"),
        ("test_SEC_설정을_읽는다", {"SEC_USER_AGENT": "M30 Canary ua-canary-Q7 no email"}, "SEC_USER_AGENT must be one line"),
        ("test_SEC_설정을_읽는다", {"SEC_USER_AGENT": "M30 Canary ua-canary-Q7@x.invalid\r\nX-Injected: 1"},
         "SEC_USER_AGENT must be one line"),
    ],
    ids=["db_missing", "llm_missing", "llm_newline", "llm_space", "sec_missing", "sec_no_email", "sec_newline"],
)
def test_설정_읽기가_거부해도_환경의_비밀값과_거부한_값이_traceback_지역_변수에_남지_않는다(probe, change, message):
    env = {k: v for k, v in os.environ.items() if k not in CANARIES} | CANARIES
    for name, value in change.items():
        if value is None:
            del env[name]
        else:
            env[name] = value
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--tb=long", "--showlocals", f"tests/config_probe.py::{probe}"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60,
    )
    out = r.stdout + r.stderr

    assert r.returncode != 0
    assert "ConfigError" in out and message in out  # 그 거부 경로까지 실제로 갔다
    for marker in MARKERS:
        assert marker not in out
