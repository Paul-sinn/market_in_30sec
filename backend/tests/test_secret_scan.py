"""커밋 전 비밀값 검사(#17 D6) 텍스트 검사. gitleaks 없이 돈다: 레포 규칙 정규식은 Python re와 RE2에서 같게 도는 문법만 써서
여기서 re로 확인한다. 실제 gitleaks 동작(기본 규칙·오탐)은 secret-scan 워크플로 첫 실행에서 본다.
샘플 비밀값은 실행 중에 만든다(소스에 키 모양 문자열을 두면 이 파일이 검사에 걸린다). 16진수라 'canary'를 우연히 만들 수 없다."""

import os
import re
import secrets
import stat
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".gitleaks.toml"
HOOK = ROOT / ".githooks" / "pre-commit"
WORKFLOW = ROOT / ".github" / "workflows" / "secret-scan.yml"


def config():
    return tomllib.loads(CONFIG.read_text())


def rule(rule_id):
    [found] = [r for r in config()["rules"] if r["id"] == rule_id]
    return found


def leak(rule_id, text):
    """레포 규칙이 찾은 비밀값(secretGroup, 없으면 전체 일치). 못 찾으면 None. 키워드가 없으면 gitleaks는 정규식을 돌리지 않는다."""
    r = rule(rule_id)
    if not any(k in text.lower() for k in r["keywords"]):
        return None
    found = re.search(r["regex"], text)
    return found and found.group(r.get("secretGroup", 0))


def allowed(secret):
    """전역 allowlist의 값 정규식(기본 대상 = 찾은 비밀값)에 걸리는지."""
    return any(re.search(p, secret) for a in config()["allowlists"] for p in a.get("regexes", []))


def test_gitleaks_설정은_기본_규칙에_레포_규칙_셋을_더한다():
    assert config()["extend"] == {"useDefault": True}
    assert [r["id"] for r in config()["rules"]] == ["m30-postgres-url-password", "m30-discord-webhook", "m30-supabase-secret-key"]


def test_레포_규칙은_DB_비밀번호·Discord_웹훅·Supabase_비밀_키를_찾고_allowlist에_걸리지_않는다():
    password, token, key = secrets.token_hex(16), secrets.token_hex(34), secrets.token_hex(20)
    samples = {
        "m30-postgres-url-password": (f"SUPABASE_DB_URL=postgresql://postgres.abcdefghijklmnop:{password}"
                                      "@aws-0-us-east-1.pooler.supabase.com:5432/postgres", password),
        "m30-discord-webhook": (f"url = 'https://discord.com/api/webhooks/123456789012345678/{token}'",
                                f"https://discord.com/api/webhooks/123456789012345678/{token}"),
        "m30-supabase-secret-key": (f'key: "sb_secret_{key}"', f"sb_secret_{key}"),
    }
    for rule_id, (text, secret) in samples.items():
        assert leak(rule_id, text) == secret, rule_id
        assert not allowed(secret), rule_id


def test_로컬_Supabase_기본_주소와_테스트_캐너리·환경_변수_이름은_비밀값으로_보지_않는다():
    assert leak("m30-postgres-url-password", "postgresql://postgres:postgres@127.0.0.1:54322/postgres") is None  # 8자
    assert leak("m30-postgres-url-password", 'f"postgresql://postgres:{CANARY}@127.0.0.1:1/postgres"') is None  # f-문자열 자리
    assert allowed("Zq9CfgCanaryPw") and allowed("WebhookCanary88")
    assert allowed("SUPABASE_SERVICE_ROLE_KEY")  # README의 --override-name auth.service_role_key=SUPABASE_SERVICE_ROLE_KEY
    paths = [p for a in config()["allowlists"] for p in a.get("paths", [])]
    for path in ("web/package-lock.json", "backend/uv.lock", "backend/tests/edgar_responses/CIK0000320193.json", ".gitleaks.toml"):
        assert any(re.search(p, path) for p in paths), path
    assert not any(re.search(p, "backend/src/m30/config.py") for p in paths)


def test_pre_commit_훅은_실행_파일이고_스테이지된_변경만_값을_가려_검사한다():
    assert HOOK.stat().st_mode & stat.S_IXUSR
    text = HOOK.read_text()
    assert text.startswith("#!/bin/sh\n")
    assert "exec gitleaks git --pre-commit --staged --redact --no-banner --config .gitleaks.toml" in text


def test_gitleaks가_없으면_pre_commit_훅이_커밋을_막는다():
    r = subprocess.run([str(HOOK)], cwd=ROOT, env={**os.environ, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
                       timeout=10)

    assert r.returncode == 1
    assert "gitleaks not found" in r.stderr and "commit blocked" in r.stderr


def test_secret_scan_워크플로는_고정한_버전과_체크섬으로_받은_gitleaks로_전체_이력을_값을_가려_검사한다():
    text = WORKFLOW.read_text()
    assert re.search(r"^on:\n  push:\n  pull_request:\n", text, re.M)
    assert "permissions:\n  contents: read" in text
    assert "secrets." not in text  # 공개 로그. 비밀값 없이 돈다
    assert re.search(r"^\s*GITLEAKS_VERSION: \d+\.\d+\.\d+$", text, re.M)
    assert re.search(r"^\s*GITLEAKS_SHA256: [0-9a-f]{64}$", text, re.M)
    assert "sha256sum -c" in text
    assert "fetch-depth: 0" in text and "persist-credentials: false" in text
    [scan] = [line for line in text.splitlines() if "gitleaks git" in line]
    assert "--redact" in scan and "--config .gitleaks.toml" in scan
    uses = re.findall(r"uses: (\S+)", text)
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses
