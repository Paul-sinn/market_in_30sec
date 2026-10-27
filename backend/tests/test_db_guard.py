"""DB 연결 안전장치: 접속 실패 시 비밀번호 비노출, 로컬 전용 가드. pytest·CLI를 하위 프로세스로 실제로 돌려 출력 전체를 본다."""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from m30.config import Settings
from m30.db.store import connect

BACKEND = Path(__file__).resolve().parent.parent
CANARY = "Zq9LeakCanary77"  # 가짜 비밀번호. 출력에 한 번이라도 나오면 샌 것
PYTEST_DB_TEST = ["-m", "pytest", "-p", "no:cacheprovider", "--tb=long", "--showlocals",
                  "tests/test_schema.py::test_RLS가_꺼진_테이블이_없다"]
CLI = ["-m", "m30.pipeline", "2026-10-16", "--scenario", "scenarios/first_card.json"]


def run(args, database_url):
    env = {**os.environ, "SUPABASE_DB_URL": database_url}
    r = subprocess.run([sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("args", [PYTEST_DB_TEST, CLI], ids=["pytest", "CLI"])
def test_DB_연결이_실패해도_비밀번호가_출력·예외·traceback에_남지_않는다(settings, args):
    code, out = run(args, make_conninfo(settings.database_url, password=CANARY))  # 로컬 DB, 틀린 비밀번호

    assert code != 0
    assert "DB에 연결하지 못했습니다" in out  # 가드가 아니라 접속 단계까지 가서 실패했다
    assert CANARY not in out


@pytest.mark.parametrize(
    "args, message",
    [(PYTEST_DB_TEST, "SUPABASE_DB_URL이 로컬 DB가 아닙니다"), (CLI, "SUPABASE_DB_URL이 로컬 DB가 아니라 중단합니다")],
    ids=["pytest", "CLI"],
)
def test_로컬이_아닌_DB_주소면_접속하기_전에_멈춘다(args, message):
    code, out = run(args, f"postgresql://postgres:{CANARY}@db.m30-test.invalid:5432/postgres")  # .invalid는 어디로도 안 간다

    assert code != 0
    assert message in out  # 가드 문구 = 접속 시도 전에 멈췄다 (가드가 없으면 접속 실패 문구가 대신 나온다)
    assert CANARY not in out


# 운영 모드(#26). 세 비밀값은 테스트가 직접 넣거나 지운다(개발자 셸의 실제 키를 쓰지 않는다)
REMOTE_URL = f"postgresql://postgres:{CANARY}@db.m30-test.invalid:5432/postgres"
KEY_CANARY = "sk-ant-KeyCanary93"
UA_CANARY = "M30 Canary uaCanary41@example.invalid"  # '@' 포함 한 줄 ASCII라 load_edgar_settings를 통과한다
CANARIES = (CANARY, KEY_CANARY, UA_CANARY)
SECRETS = {"SUPABASE_DB_URL": REMOTE_URL, "ANTHROPIC_API_KEY": KEY_CANARY, "SEC_USER_AGENT": UA_CANARY}


def run_cli(args, secrets=SECRETS):
    env = {k: v for k, v in os.environ.items() if k not in SECRETS} | secrets
    r = subprocess.run([sys.executable, "-m", "m30.pipeline", *args], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def test_운영_모드를_켜면_원격_DB_주소도_가드를_지나_접속_단계까지_가고_비밀값은_출력에_없다():
    code, out = run_cli(["--production", "2026-10-16"])

    assert code == 1
    assert "DB에 연결하지 못했습니다" in out  # .invalid 주소라 접속 단계에서 실패
    assert "로컬 DB가 아니라" not in out
    assert not [c for c in CANARIES if c in out]


@pytest.mark.parametrize(
    "url, reason",
    [
        (f"postgresql://postgres:{CANARY}%zz@127.0.0.1:54322/postgres", "bad_url"),  # 파싱 오류 메시지는 비밀번호를 그대로 담는다
        (None, "auth_failed"),  # 로컬 DB, 틀린 비밀번호
        (f"postgresql://postgres:{CANARY}@127.0.0.1:1/postgres", "refused"),  # 닫힌 로컬 포트
        (REMOTE_URL, "host_not_found"),  # .invalid는 오프라인에서도 바로 실패한다
    ],
    ids=["bad_url", "auth_failed", "refused", "host_not_found"],
)
def test_운영_모드_DB_연결_실패는_고정_문구와_이유_코드_한_줄만_찍고_주소·비밀값은_찍지_않는다(settings, url, reason):
    url = url or make_conninfo(settings.database_url, password=CANARY)
    code, out = run_cli(["--production", "2026-10-16"], SECRETS | {"SUPABASE_DB_URL": url})

    assert code == 1
    assert len(out.strip().splitlines()) == 1  # 원래 psycopg 메시지(호스트·사용자) 줄이 섞이지 않았다
    assert out.startswith("SUPABASE_DB_URL로 DB에 연결하지 못했습니다")
    assert out.strip().endswith(f"(reason={reason})")
    assert not [c for c in CANARIES if c in out]
    assert "127.0.0.1" not in out and "m30-test.invalid" not in out  # 호스트(원래 메시지에 있다)


@pytest.mark.parametrize("url", [REMOTE_URL + "\n", REMOTE_URL + " ", " " + REMOTE_URL, REMOTE_URL + "\r\n"],
                         ids=["trailing_newline", "trailing_space", "leading_space", "trailing_crlf"])
def test_운영_모드_DB_URL에_붙여넣기_공백이_있으면_접속하지_않고_bad_url로_알린다(url):
    code, out = run_cli(["--production", "2026-10-16"], SECRETS | {"SUPABASE_DB_URL": url})

    assert code == 1
    assert out.strip().endswith("(reason=bad_url)")  # 접속했다면 .invalid라 host_not_found가 나온다
    assert not [c for c in CANARIES if c in out]


def test_운영_모드와_시나리오는_같이_쓸_수_없다():
    code, out = run_cli(["--production", "--scenario", "scenarios/first_card.json", "2026-10-16"])

    assert code == 2
    assert "not allowed with" in out


def test_모드를_고르지_않으면_실행하지_않는다():
    code, out = run_cli(["2026-10-16"])

    assert code == 2
    assert "one of the arguments --scenario --production is required" in out


def test_시나리오_모드는_거래일이_있어야_한다():
    code, out = run_cli(["--scenario", "scenarios/first_card.json"])

    assert code == 2
    assert "trading_day is required with --scenario" in out


@pytest.mark.parametrize("missing", list(SECRETS))
def test_운영_모드에서_비밀값_하나가_없으면_DB에_붙기_전에_이름만_알리고_멈춘다(missing):
    code, out = run_cli(["--production", "2026-10-16"], {k: v for k, v in SECRETS.items() if k != missing})

    assert code == 2
    assert f"{missing} is not set" in out
    assert "DB에 연결하지 못했습니다" not in out
    assert not [c for c in CANARIES if c in out]


def test_운영_모드에서_주말이면_DB에_붙지_않고_성공으로_끝난다():
    code, out = run_cli(["--production", "2026-10-17"])  # 토요일

    assert code == 0
    assert "2026-10-17은 주말이라 카드를 만들지 않습니다" in out
    assert "DB에 연결하지 못했습니다" not in out


def test_운영_모드에서_공시_기간이_아직_안_닫힌_날짜면_DB에_붙기_전에_멈춘다():
    code, out = run_cli(["--production", "2099-01-02"])  # 금요일, 미래

    assert code == 2
    assert "2099-01-02 공시 기간은 그날 04:00 ET에 닫힙니다" in out
    assert "DB에 연결하지 못했습니다" not in out


POOLER = "aws-0-us-west-1.pooler.m30-test.invalid"


@pytest.mark.parametrize("hosts", [f"{POOLER}:6543", f"{POOLER}:06543", f"{POOLER}:5432,{POOLER}:6543"],
                         ids=["6543", "leading_zero", "multi_host"])
def test_원격_DB_주소가_트랜잭션_풀러_6543이면_접속하기_전에_세션_풀러를_쓰라고_멈춘다(hosts):
    url = f"postgresql://postgres.m30test:{CANARY}@{hosts}/postgres"
    code, out = run_cli(["--production", "2026-10-16"], SECRETS | {"SUPABASE_DB_URL": url})

    assert code == 2
    assert "트랜잭션 풀러(포트 6543)" in out
    assert "DB에 연결하지 못했습니다" not in out  # 접속 시도 전 (.invalid라 시도했으면 접속 실패 문구가 나온다)
    assert not [c for c in CANARIES if c in out]


class RecordedConnect:
    """psycopg.connect 자리(C1, 스펙 #26이 정한 connect 단위 검사: sslmode는 출력으로 보이지 않는다). 받은 인자와 실행한 SQL을 남긴다."""

    def __init__(self):
        self.kwargs, self.sql = None, []

    def __call__(self, conninfo, **kwargs):
        self.kwargs = kwargs
        return self

    def execute(self, sql):
        self.sql.append(sql)

    def close(self):
        pass


@pytest.mark.parametrize(
    "url, sslmode",
    [
        ("postgresql://postgres.m30test:pw@aws-0-us-west-1.pooler.m30-test.invalid:5432/postgres?sslmode=disable", "require"),
        ("postgresql://postgres:postgres@127.0.0.1:54322/postgres", None),
    ],
    ids=["remote", "local"],
)
def test_원격_DB는_URL과_관계없이_암호화_연결을_요구하고_로컬은_그대로다(monkeypatch, url, sslmode):
    fake = RecordedConnect()
    monkeypatch.setattr(psycopg, "connect", fake)

    connect(Settings(database_url=url))

    assert fake.kwargs.get("sslmode") == sslmode
    assert fake.sql == ["set role service_role"]


@pytest.mark.parametrize("module", ["m30.pipeline.production", "m30.pipeline.__main__"])
def test_운영_경로는_가짜_어댑터와_시나리오를_불러오지_않는다(module):
    code = f"import sys, {module}; sys.exit('m30.adapters.fake' in sys.modules)"
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60)

    assert r.returncode == 0, r.stderr


def test_운영_모드에서_Anthropic_키_끝에_줄바꿈이_있으면_DB에_붙기_전에_값_없이_멈춘다():
    code, out = run_cli(["--production", "2026-10-16"], SECRETS | {"ANTHROPIC_API_KEY": KEY_CANARY + "\n"})  # 붙여넣기 실수

    assert code == 2
    assert "ANTHROPIC_API_KEY must be one line" in out
    assert "DB에 연결하지 못했습니다" not in out
    assert not [c for c in CANARIES if c in out]


def test_품질_확인_모드에서_Anthropic_키가_없으면_DB에_붙기_전에_이름만_알리고_멈춘다():
    secrets = {k: v for k, v in SECRETS.items() if k != "ANTHROPIC_API_KEY"}
    code, out = run_cli(["2026-10-16", "--scenario", "scenarios/filings_day.json", "--quality"], secrets)

    assert code == 2
    assert "ANTHROPIC_API_KEY is not set" in out
    assert "DB에 연결하지 못했습니다" not in out and "로컬 DB가 아니라" not in out  # DB 설정·가드보다 먼저 멈췄다
    assert not [c for c in CANARIES if c in out]


def test_운영_모드_품질_확인은_로컬이_아닌_DB면_접속하기_전에_멈춘다():
    code, out = run_cli(["--production", "2026-10-16", "--quality"])  # 원격 캐너리 주소

    assert code == 2
    assert "--quality는 로컬 DB에서만 씁니다" in out
    assert "DB에 연결하지 못했습니다" not in out  # .invalid라 접속을 시도했으면 접속 실패 문구가 나온다
    assert not [c for c in CANARIES if c in out]
