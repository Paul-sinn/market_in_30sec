"""live: 실제 SEC 10-K + 실제 Sonnet(생성)·판정 모델로 알아두기(#66)의 발췌·생성·코드 검사·판정을 본다. 기본 실행에서 빠진다(-m live).
DB 없음. 실험 회사 8개마다 submissions + 최신 10-K 전체 제출 파일(요청 간격 1초) → item1_lines → 생성 1회(깨지면 1회 더) → screen_facts
→ 판정 1회(깨지면 1회 더). 비용 약 $0.2.
단언은 불리언만(실패 메시지에 본문·키가 찍히지 않게). -s 출력은 로컬 전용이라(live는 Actions에서 돌지 않는다) 티커·건수·초·토큰과 함께
통과·탈락 문장과 이유를 찍는다(copy-reviewer 표본, U4 판정 지시문이 현재형 설명을 떨어뜨리지 않는지).
실행: 값은 명령 줄 안에서만(파일에 쓰지 않는다)
  SEC_USER_AGENT="<연락처가 든 User-Agent>" ANTHROPIC_API_KEY="<키>" uv run pytest -q -s -m live tests/test_quiet_facts_live.py"""

import json
import os
import time

import pytest

from m30.adapters.edgar import ANNUAL_REPORT_FILE_MAX, QUARTERLY_INTERVAL, EdgarAnnualReportSource, EdgarClient, Throttle
from m30.config import LLM_KEY_VAR, SEC_UA_VAR, load_edgar_settings, load_llm_settings
from m30.copy_rules import check_quiet_fact
from m30.llm import LLMBudget
from m30.llm.anthropic import AnthropicLLM
from m30.pipeline.lines import company_short_name
from m30.pipeline.quiet_facts import (
    QUIET_EXCERPT_MAX,
    clean_fact,
    parse_quiet_drafts,
    parse_quiet_labels,
    quiet_check_request,
    quiet_fact_request,
    screen_facts,
)
from m30.pipeline.relations import item1_lines
from m30.pipeline.review import mask_names, name_terms

pytestmark = [pytest.mark.live, pytest.mark.skipif(not (os.environ.get(SEC_UA_VAR) and os.environ.get(LLM_KEY_VAR)),
                                                   reason=f"{SEC_UA_VAR} and {LLM_KEY_VAR} are needed")]

# 실험 회사: (티커, CIK, coverage.name). 이름은 커버 범위처럼 N-PORT 이름에서 주식 종류·법인 꼬리를 뗀 것
TARGETS = [("AAPL", "0000320193", "Apple"), ("MSFT", "0000789019", "Microsoft"), ("NVDA", "0001045810", "NVIDIA"),
           ("AMZN", "0001018724", "Amazon.com"), ("JPM", "0000019617", "JPMorgan Chase"), ("XOM", "0000034088", "Exxon Mobil"),
           ("KO", "0000021344", "Coca-Cola"), ("JNJ", "0000200406", "Johnson & Johnson")]
PASS_MIN = 5  # Item 1을 찾은 회사마다 통과 사실 수 하한


def test_실제_10_K와_LLM으로_알아두기를_만들면_회사마다_통과한_사실이_다섯_개_이상이다():
    source = EdgarAnnualReportSource(
        EdgarClient(load_edgar_settings(), throttle=Throttle(QUARTERLY_INTERVAL), max_bytes=ANNUAL_REPORT_FILE_MAX).get)
    budget = LLMBudget(AnthropicLLM(load_llm_settings(), timeout=120.0), 4 * len(TARGETS))

    read_all, found_item1, parsed, enough = True, 0, 0, True
    for ticker, cik, name in TARGETS:
        try:
            report = source.annual_report(cik, source.listing(cik).accession)
        except Exception:  # noqa: BLE001 — 예외 메시지(주소·헤더)를 찍지 않고 불리언으로만 남긴다
            read_all = False
            continue
        lines = item1_lines(report.body)
        if lines is None:
            print(f"{ticker} cik={cik} gap=no_item1")
            continue
        found_item1 += 1
        short, terms = company_short_name(name), name_terms([ticker], {ticker: name})
        started, before = time.monotonic(), dict(budget.tokens)
        request = quiet_fact_request(short, "\n".join(lines)[:QUIET_EXCERPT_MAX])
        try:
            drafts = parse_quiet_drafts(budget.complete(request)) or parse_quiet_drafts(budget.complete(request))
            kept, fmt, rules = screen_facts(drafts[0], short, terms) if drafts else ([], 0, 0)
            labels = None
            if kept:
                check = quiet_check_request(kept)
                labels = parse_quiet_labels(budget.complete(check), len(kept))
                if labels is None:
                    labels = parse_quiet_labels(budget.complete(check), len(kept))
        except Exception:  # noqa: BLE001 — 메시지를 찍지 않는다
            drafts = labels = None
        seconds = time.monotonic() - started
        if drafts is None or (kept and labels is None):
            print(f"{ticker} cik={cik} parse=failed seconds={seconds:.1f}")
            enough = False
            continue
        parsed += 1
        passed = [t for n, t in enumerate(kept, 1) if labels and labels.get(n) == "fact"]
        enough &= len(passed) >= PASS_MIN
        tokens = {k: budget.tokens[k] - before[k] for k in budget.tokens}
        print(f"{ticker} cik={cik} drafts={len(drafts[0])} dropped=format:{fmt + drafts[1]},rules:{rules},"
              f"check:{len(kept) - len(passed)} passed={len(passed)} seconds={seconds:.1f} tokens={tokens}")
        for kind, raw in drafts[0]:  # 문장은 json.dumps: 한 줄 유지, 제어 문자 무력화
            text = clean_fact(raw)
            n = kept.index(text) + 1 if text in kept else None
            verdict = (labels.get(n, "missing") if labels else "-") if n else "; ".join(check_quiet_fact(mask_names(text, terms))) or "format"
            print(f"  {kind} {verdict} {json.dumps(text, ensure_ascii=False)}")

    assert read_all
    assert found_item1 >= len(TARGETS) - 1
    assert parsed == found_item1  # 생성·판정 응답을 전부 읽었다
    assert enough
