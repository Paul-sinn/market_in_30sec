"""test_newsline이 하위 프로세스로만 돌리는 파일. test_ 접두사가 없어 기본 수집에서 빠진다.
품질 확인 CLI(m30.pipeline.__main__.main, --quality)를 그대로 돌리고, 실제 Anthropic 자리(AnthropicLLM)만 시나리오의 llm_replies를
돌려주는 가짜 LLM으로 바꾼다(네트워크 없음. 키 읽기·로컬 가드·출력은 실제 경로).
사용법: python tests/quality_probe.py 2026-10-16 --scenario <경로> --quality"""

import sys
from pathlib import Path


def main(args):
    import m30.pipeline.__main__ as cli
    from m30.adapters.fake import FakeLLM, load_scenario

    path = Path(args[args.index("--scenario") + 1])
    cli.AnthropicLLM = lambda settings: FakeLLM(load_scenario(path))  # settings = load_llm_settings()가 읽은 키(캐너리)
    return cli.main(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
