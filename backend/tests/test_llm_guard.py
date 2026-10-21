"""입구 3: Anthropic 키 비노출. pytest를 하위 프로세스로 실제로 돌려 출력 전체(traceback·지역 변수 포함)를 본다."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
CANARY = "sk-ant-Zq9LeakCanary77"  # 가짜 키. 출력에 한 번이라도 나오면 샌 것
PROBE = ["-m", "pytest", "-p", "no:cacheprovider", "--tb=long", "--showlocals", "tests/llm_probe.py"]


def test_Anthropic_호출이_실패해도_키가_출력·예외·traceback에_남지_않는다():
    env = {**os.environ, "ANTHROPIC_API_KEY": CANARY}
    r = subprocess.run([sys.executable, *PROBE], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr

    assert r.returncode != 0
    assert "TransientSourceError" in out  # 키를 읽고 호출까지 가서 접속 단계에서 실패했다
    assert CANARY not in out
