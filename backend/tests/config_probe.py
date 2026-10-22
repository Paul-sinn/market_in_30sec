"""test_config_guard가 하위 프로세스로만 돌리는 파일. test_ 접두사가 없어 기본 수집에서 빠진다. 거부되어 실패하는 것이 정상이다.
설정 읽기 함수 셋을 기본 환경(os.environ)으로 부른다. guard가 한 변수를 빼거나 틀리게 넣고 나머지 비밀값 자리에 canary를 둔다."""

from m30.config import load_edgar_settings, load_llm_settings, load_settings


def test_DB_설정을_읽는다():
    load_settings()


def test_Anthropic_설정을_읽는다():
    load_llm_settings()


def test_SEC_설정을_읽는다():
    load_edgar_settings()
