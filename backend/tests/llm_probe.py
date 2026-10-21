"""test_llm_guard가 하위 프로세스로만 돌리는 파일. test_ 접두사가 없어 기본 수집에서 빠진다. 실패하는 것이 정상이다."""

from m30.config import load_llm_settings
from m30.llm import LLMRequest
from m30.llm.anthropic import AnthropicLLM


def test_닫힌_로컬_포트로_Anthropic을_부른다():
    llm = AnthropicLLM(load_llm_settings(), url="https://127.0.0.1:9/v1/messages", timeout=2.0)  # 접속 거부 → 일시 실패
    llm.complete(LLMRequest("m", "s", "u", 1))
