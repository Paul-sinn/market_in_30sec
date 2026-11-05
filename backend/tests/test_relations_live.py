"""live: 실제 SEC 10-K + 실제 Sonnet으로 연관 종목 추출(#64)의 발췌·응답·이름 맞추기를 본다. 기본 실행에서 빠진다(-m live). DB 없음.
실험 회사 8개(경쟁·고객·공급 예가 다 있다)마다 submissions + 최신 10-K 전체 제출 파일(요청 간격 1초) → business_excerpt → Sonnet 1회
(깨지면 1회 더) → parse_mentions → 고정 작은 커버 범위(큰 회사 약 30개, N-PORT식 이름)로 match_name. 비용 약 $0.3.
단언은 불리언만: 실패 메시지에 본문·회사 이름·키가 찍히지 않게. -s 출력은 티커·CIK·글자 수·건수·초·토큰뿐(회사 이름·문장 없음).
실행: 값은 명령 줄 안에서만(파일에 쓰지 않는다)
  SEC_USER_AGENT="<연락처가 든 User-Agent>" ANTHROPIC_API_KEY="<키>" uv run pytest -q -s -m live tests/test_relations_live.py"""

import os
import time

import pytest

from m30.adapters.edgar import ANNUAL_REPORT_FILE_MAX, QUARTERLY_INTERVAL, EdgarAnnualReportSource, EdgarClient, Throttle
from m30.config import LLM_KEY_VAR, SEC_UA_VAR, load_edgar_settings, load_llm_settings
from m30.llm import LLMBudget
from m30.llm.anthropic import AnthropicLLM
from m30.models import Coverage
from m30.pipeline.relations import Excerpt, MatchMiss, business_excerpt, company_index, match_name, parse_mentions, relation_request

pytestmark = [pytest.mark.live, pytest.mark.skipif(not (os.environ.get(SEC_UA_VAR) and os.environ.get(LLM_KEY_VAR)),
                                                   reason=f"{SEC_UA_VAR} and {LLM_KEY_VAR} are needed")]

# 실험 회사: (티커, CIK, coverage.name). 이름은 커버 범위처럼 N-PORT 이름에서 주식 종류·법인 꼬리를 뗀 것
FILERS = [("AAPL", "0000320193", "Apple"), ("MSFT", "0000789019", "Microsoft"), ("GOOGL", "0001652044", "Alphabet"),
          ("JPM", "0000019617", "JPMorgan Chase"), ("XOM", "0000034088", "Exxon Mobil"), ("KO", "0000021344", "Coca-Cola"),
          ("NVDA", "0001045810", "NVIDIA"), ("QCOM", "0000804328", "QUALCOMM")]
# 상대가 될 큰 회사들. CIK는 자리값(맞추기 결과를 세는 데만 쓴다, 실험 회사 CIK와 겹치지 않는다)
OTHERS = ["Amazon.com", "Meta Platforms", "Broadcom", "Advanced Micro Devices", "Intel", "Texas Instruments", "Cisco Systems",
          "Oracle", "International Business Machines", "Salesforce", "Adobe", "Walmart", "PepsiCo", "Procter & Gamble", "Chevron",
          "ConocoPhillips", "Bank of America", "Wells Fargo", "Citigroup", "Goldman Sachs Group", "Morgan Stanley", "Visa",
          "Mastercard", "Micron Technology", "Applied Materials", "Hewlett Packard Enterprise", "Dell Technologies",
          "Keurig Dr Pepper", "Monster Beverage"]
OTHER_TICKERS = ["AMZN", "META", "AVGO", "AMD", "INTC", "TXN", "CSCO", "ORCL", "IBM", "CRM", "ADBE", "WMT", "PEP", "PG", "CVX", "COP",
                 "BAC", "WFC", "C", "GS", "MS", "V", "MA", "MU", "AMAT", "HPE", "DELL", "KDP", "MNST"]
COVERAGE = [Coverage(t, name, cik=cik) for t, cik, name in FILERS] + [
    Coverage(t, name, cik=f"{9_000_000_000 + n:010d}") for n, (t, name) in enumerate(zip(OTHER_TICKERS, OTHERS, strict=True))]


def fold(text):
    return " ".join(text.casefold().replace("’", "'").split())  # parse_mentions의 이름 ∈ 문장 비교와 같은 정규화


def test_실제_10_K와_Sonnet으로_발췌를_보내_근거_문장_안의_이름만_받고_커버_범위와_맞춘다():
    source = EdgarAnnualReportSource(
        EdgarClient(load_edgar_settings(), throttle=Throttle(QUARTERLY_INTERVAL), max_bytes=ANNUAL_REPORT_FILE_MAX).get)
    budget = LLMBudget(AnthropicLLM(load_llm_settings(), timeout=120.0), 2 * len(FILERS))
    index = company_index(COVERAGE)

    read_all, found_item1, sent, parsed, grounded, matched_filers = True, 0, 0, 0, True, set()
    for ticker, cik, name in FILERS:
        try:
            listing = source.listing(cik)
            report = source.annual_report(cik, listing.accession)
        except Exception:  # noqa: BLE001 — 예외 메시지(주소·헤더)를 찍지 않고 불리언으로만 남긴다
            read_all = False
            continue
        excerpt = business_excerpt(report.body)
        if not isinstance(excerpt, Excerpt):
            print(f"{ticker} cik={cik} gap={excerpt}")
            continue
        found_item1 += 1
        sent += 1
        started, before = time.monotonic(), dict(budget.tokens)
        try:
            result = parse_mentions(budget.complete(relation_request(name, excerpt)), excerpt)
            if result is None:
                result = parse_mentions(budget.complete(relation_request(name, excerpt)), excerpt)
        except Exception:  # noqa: BLE001 — 메시지를 찍지 않는다
            result = None
        seconds = time.monotonic() - started
        if result is None:
            print(f"{ticker} cik={cik} parse=failed seconds={seconds:.1f}")
            continue
        parsed += 1
        mentions, dropped = result
        grounded &= all(fold(m.name) in fold(m.evidence) and m.evidence in excerpt.sentences for m in mentions)
        hits = [match_name(m.name, index) for m in mentions]
        matched = [h for h in hits if not isinstance(h, MatchMiss) and h != cik]
        if matched:
            matched_filers.add(ticker)
        print(f"{ticker} cik={cik} excerpt_sentences={len(excerpt.sentences)} excerpt_chars={sum(map(len, excerpt.sentences))}"
              f" truncated={excerpt.truncated} mentions={len(mentions)} dropped={dropped} matched={len(matched)}"
              f" unmatched={hits.count(MatchMiss.UNMATCHED)} ambiguous={hits.count(MatchMiss.AMBIGUOUS)}"
              f" self={sum(h == cik for h in hits)} seconds={seconds:.1f}"
              f" in={budget.tokens['input_tokens'] - before['input_tokens']} out={budget.tokens['output_tokens'] - before['output_tokens']}")
    print(f"llm_calls={budget.calls} tokens={budget.tokens}")

    assert read_all, "L1: submissions or 10-K read failed"
    assert found_item1 >= len(FILERS) - 1, "L2: Item 1 section not found in two or more 10-Ks"
    assert parsed == sent, "L3: a reply did not parse twice"
    assert grounded, "L3: a kept name is not inside its evidence sentence, or evidence is not an excerpt sentence"
    assert len(matched_filers & {"MSFT", "NVDA", "QCOM"}) >= 2, "L4: fewer than two of MSFT·NVDA·QCOM matched a covered company"
