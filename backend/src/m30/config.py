import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import psycopg
from psycopg.conninfo import conninfo_to_dict

ET = ZoneInfo("America/New_York")  # 파이프라인 시각(04:00, 07:45, 16:30)이 전부 동부 기준
DB_URL_VAR = "SUPABASE_DB_URL"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# 모델 ID는 이 파일에만 둔다. 개발 중엔 전부 haiku. #6·#7·#11이 여기에 상수를 더한다
CLASSIFY_MODEL = "claude-haiku-5-5"
NEWSLINE_MODEL = "claude-haiku-5-5"  # 첫 번째 줄. 출시 전 claude-sonnet-5-5 (HANDOFF 3-6)
LLM_KEY_VAR = "ANTHROPIC_API_KEY"  # Anthropic 키는 이 환경 변수에서만 읽는다


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    url = env.get(DB_URL_VAR, "")
    if not url:
        raise ConfigError(f"{DB_URL_VAR} is not set")
    return Settings(database_url=url)


def is_local_db(database_url: str) -> bool:
    try:
        host = conninfo_to_dict(database_url).get("host")
    except psycopg.ProgrammingError:
        return False  # 파싱 오류 메시지에 주소 일부가 섞일 수 있어 삼키고 "로컬 아님"으로 닫는다
    return host in LOCAL_HOSTS


@dataclass(frozen=True)
class LLMSettings:
    api_key: str = field(repr=False)


def load_llm_settings(env: Mapping[str, str] = os.environ) -> LLMSettings:
    """실제 Anthropic 클라이언트(#14)가 부른다. 가짜 LLM은 키가 필요 없다."""
    key = env.get(LLM_KEY_VAR, "")
    if not key:
        raise ConfigError(f"{LLM_KEY_VAR} is not set")
    return LLMSettings(api_key=key)
