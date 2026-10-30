"""live: 실제 Haiku 호출(약 23회). 기본 실행에서 빠진다. 기관 문장에 사실/예측 판정 지시문이 맞는지(#50 완료 기준 5)와 녹화 기관
발표로 쓴 소식 줄을 본다. 문장은 공공 데이터라 -s로 찍는다(copy-reviewer 검수용, 로컬 실행만). 키는 명령 줄에서만:
  ANTHROPIC_API_KEY="…" uv run pytest -q -s -m live tests/test_glance_live.py"""

import time
from datetime import date

import pytest

from m30.adapters import Source
from m30.adapters.gov_news import AGENCY_NAMES, GovNewsSource
from m30.config import ET, load_llm_settings
from m30.copy_rules import check_card
from m30.llm import LLMBudget
from m30.llm.anthropic import AnthropicLLM
from m30.models import LineStatus
from m30.pipeline.collect import SourceCalls, filing_window
from m30.pipeline.glance import GLANCE_CALLS, market_news_line
from m30.pipeline.review import FactLabel, factcheck_request, parse_factcheck_reply
from production_probe import gov_day
from test_edgar import RecordedGet

pytestmark = pytest.mark.live

FACTCHECK_SAMPLES = (  # 스펙 #50 5장. 기관 문장도 회사 문장과 같은 라벨이어야 한다
    ("Bureau of Labor Statistics reported consumer prices rose 0.6%", FactLabel.FACT),
    ("Federal Reserve kept its policy rate unchanged", FactLabel.FACT),
    ("Federal Reserve issued its policy statement", FactLabel.FACT),  # 제목만 있는 연준 성명(#50 수정 1)
    ("Bureau of Economic Analysis reported GDP grew 3.4%", FactLabel.FACT),
    ("Census Bureau reported retail sales rose 0.4%", FactLabel.FACT),
    ("Federal Reserve released minutes of its September meeting", FactLabel.FACT),
    ("Federal Reserve released new economic projections", FactLabel.FACT),
    ("Federal Reserve expects to cut rates twice next year", FactLabel.FORECAST),
    ("Federal Reserve projected unemployment will reach 4.5%", FactLabel.FORECAST),
    ("Bureau of Labor Statistics reported a strong jobs report", FactLabel.OPINION),
    ("Federal Reserve made a good decision for stocks", FactLabel.OPINION),
)


def sender(limit):
    budget = LLMBudget(AnthropicLLM(load_llm_settings()), limit)
    calls = SourceCalls(time.sleep)  # 아침 파이프라인과 같은 재시도(529 등)
    return lambda subject, request: calls.call(Source.LLM, subject, lambda: budget.complete(request), lambda t: isinstance(t, str))


def test_실제_Haiku_판정은_기관_문장에도_사실·예측·의견을_기대대로_가른다():
    send = sender(len(FACTCHECK_SAMPLES))

    got = [parse_factcheck_reply(send("factcheck", factcheck_request(sentence))) for sentence, _ in FACTCHECK_SAMPLES]

    for (sentence, expected), label in zip(FACTCHECK_SAMPLES, got):
        print(f"factcheck {'ok ' if label == expected else 'BAD'} {label} {sentence}")
    assert [i for i, ((_, expected), label) in enumerate(zip(FACTCHECK_SAMPLES, got)) if label != expected] == []


@pytest.mark.parametrize("day", [16, 29, 30], ids=["10_16_PPI·소매판매", "10_29_FOMC_성명", "10_30_BEA_GDP·소득지출"])
def test_실제_Haiku가_녹화_기관_발표로_쓴_소식_줄은_검수를_통과하면_기관_이름으로_시작하고_문구_규칙을_지킨다(day):
    trading_day = date(2026, 10, day)
    since, until = filing_window(trading_day)
    items = GovNewsSource(RecordedGet(gov_day())).items(since, until)

    line, draft, rules, code = market_news_line(
        LineStatus.CHECKED_FOUND, items, trading_day, until.astimezone(ET), sender(GLANCE_CALLS))

    print(f"glance {trading_day} {code} {line.status} {line.text!r} draft={draft!r} rules={list(rules)}")
    assert line.status in (LineStatus.CHECKED_FOUND, LineStatus.DELAYED)
    if line.status is LineStatus.CHECKED_FOUND:
        assert check_card(line.text) == []
        assert line.text.startswith(tuple(AGENCY_NAMES.values()))
        assert "FOMC" not in line.text  # 지시문: FOMC 대신 Fed(10/29 성명 제목에 FOMC가 있다)
