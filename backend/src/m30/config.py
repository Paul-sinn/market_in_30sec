import os
import re
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
REVIEW_MODEL = "claude-haiku-5-5"  # 사실/예측 판정. 출시 전 claude-sonnet-5-5 (HANDOFF 3-6)
LLM_KEY_VAR = "ANTHROPIC_API_KEY"  # Anthropic 키는 이 환경 변수에서만 읽는다
SEC_UA_VAR = "SEC_USER_AGENT"  # SEC 공정 접근: 이름 + 연락 이메일. 값은 사용자가 셸·secrets에만 넣는다
TIINGO_KEY_VAR = "TIINGO_API_KEY"  # 시세(#18). 유료 구독 전에는 비어 있다 → 운영 모드는 시세 없이 돈다


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    """설정 읽기 셋 공통: 거부 경로의 traceback(pytest --showlocals)에 비밀값이 안 찍히게, 값은 repr을 숨긴 설정 안에만 두고
    env(기본 os.environ = 다른 비밀값까지 든 환경 전체)는 검사·raise 전에 지운다."""
    settings = Settings(database_url=env.get(DB_URL_VAR, ""))
    del env
    if not settings.database_url:
        raise ConfigError(f"{DB_URL_VAR} is not set")
    return settings


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
    """실제 Anthropic 클라이언트(#14)가 부른다. 가짜 LLM은 키가 필요 없다. env를 지우는 이유는 load_settings와 같다.
    공백·줄바꿈 없는 ASCII만 받는다: http.client는 잘못된 헤더 값(붙여넣기 끝 줄바꿈 등)을 예외 메시지에 그대로 넣는다."""
    settings = LLMSettings(api_key=env.get(LLM_KEY_VAR, ""))
    del env
    if not settings.api_key:
        raise ConfigError(f"{LLM_KEY_VAR} is not set")
    if not re.fullmatch(r"[\x21-\x7e]+", settings.api_key):
        raise ConfigError(f"{LLM_KEY_VAR} must be one line of printable ASCII without spaces")
    return settings


@dataclass(frozen=True)
class EdgarSettings:
    user_agent: str = field(repr=False)  # 사용자 연락처


def load_edgar_settings(env: Mapping[str, str] = os.environ) -> EdgarSettings:
    """SEC_USER_AGENT를 읽는 곳은 여기 하나. 어떤 메시지에도 값을 넣지 않는다: http.client는 잘못된 헤더 값(줄바꿈 등)을
    예외 메시지에 그대로 넣으므로 미리 막는다. '@' 검사는 연락처를 빼먹어 SEC가 403을 내기 전에 알려 준다.
    env를 지우는 이유는 load_settings와 같다(거부한 값도 repr을 숨긴 settings 안에만 있다)."""
    settings = EdgarSettings(user_agent=env.get(SEC_UA_VAR, ""))
    del env
    if not settings.user_agent:
        raise ConfigError(f"{SEC_UA_VAR} is not set")
    if not re.fullmatch(r"[\x20-\x7e]+", settings.user_agent) or "@" not in settings.user_agent:
        raise ConfigError(f"{SEC_UA_VAR} must be one line of printable ASCII with a contact email")
    return settings


@dataclass(frozen=True)
class TiingoSettings:
    api_key: str = field(repr=False)


def load_tiingo_settings(env: Mapping[str, str] = os.environ) -> TiingoSettings | None:
    """TIINGO_API_KEY를 읽는 곳은 여기 하나. 없거나 빈 값이면 None(구독 전: Actions는 없는 secret을 빈 문자열로 넣는다).
    한 줄 ASCII 검사·env를 지우는 이유는 load_llm_settings와 같다."""
    settings = TiingoSettings(api_key=env.get(TIINGO_KEY_VAR, ""))
    del env
    if not settings.api_key:
        return None
    if not re.fullmatch(r"[\x21-\x7e]+", settings.api_key):
        raise ConfigError(f"{TIINGO_KEY_VAR} must be one line of printable ASCII without spaces")
    return settings


DISCORD_VAR = "DISCORD_WEBHOOK_URL"  # 실행 요약 알림(#17). 없으면 알림만 꺼진다
DISCORD_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")


@dataclass(frozen=True)
class DiscordSettings:
    url: str = field(repr=False)  # 주소 자체가 비밀값(아는 사람은 누구나 채널에 쓸 수 있다)


def load_discord_settings(env: Mapping[str, str] = os.environ) -> DiscordSettings | None:
    """DISCORD_WEBHOOK_URL을 읽는 곳은 여기 하나. 없거나 빈 값이면 None. Discord 웹훅 HTTPS 주소 한 줄(공백 없는 출력 가능 ASCII)이
    아니면 ConfigError(값 없이). env를 지우는 이유는 load_settings와 같다."""
    settings = DiscordSettings(url=env.get(DISCORD_VAR, ""))
    del env
    if not settings.url:
        return None
    if not settings.url.startswith(DISCORD_PREFIXES) or not re.fullmatch(r"[\x21-\x7e]+", settings.url):
        raise ConfigError(f"{DISCORD_VAR} must be one line of printable ASCII starting with {DISCORD_PREFIXES[0]}")
    return settings
