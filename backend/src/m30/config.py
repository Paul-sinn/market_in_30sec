import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import psycopg
from psycopg.conninfo import conninfo_to_dict

ET = ZoneInfo("America/New_York")  # 파이프라인 시각(04:00, 07:45, 16:30)이 전부 동부 기준
DB_URL_VAR = "SUPABASE_DB_URL"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
