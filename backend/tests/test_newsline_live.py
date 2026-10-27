"""live: 실제 Haiku 호출. 기본 실행에서 빠진다(pyproject addopts "-m 'not live'"). 품질 확인용이라 문장 품질은 판정하지 않고,
문장을 출력하지 않는다. 실행: ANTHROPIC_API_KEY를 셸에서 export한 뒤 uv run pytest -q -m live tests/test_newsline_live.py"""

import time
from datetime import date

import pytest

from m30.adapters import Source
from m30.adapters.fake import load_scenario
from m30.config import load_llm_settings
from m30.llm import LLMBudget
from m30.llm.anthropic import AnthropicLLM
from m30.models import LineStatus, NewsCandidate, NewsKind, TickerNews
from m30.pipeline.classify import FilingItem
from m30.pipeline.collect import SourceCalls
from m30.pipeline.newsline import DraftProblem, write_news_drafts

pytestmark = pytest.mark.live


def test_실제_Haiku가_첫_번째_줄_초안을_정해진_JSON_모양으로_돌려준다(filings_day):
    [aapl] = [f for f in load_scenario(filings_day).filings["0000320193"] if f.accession == "0000320193-26-000101"]
    budget = LLMBudget(AnthropicLLM(load_llm_settings()), 4)
    calls = SourceCalls(time.sleep)  # 아침 파이프라인과 같은 재시도(529 등)

    drafts = write_news_drafts(
        {"AAPL": TickerNews(LineStatus.CHECKED_FOUND, (NewsCandidate(aapl.accession, NewsKind.EARNINGS, 5, False),))},
        {aapl.accession: FilingItem(aapl, ("AAPL",), "Apple Inc.")},
        date(2026, 10, 16),
        lambda subject, request: calls.call(Source.LLM, subject, lambda: budget.complete(request), lambda t: isinstance(t, str)),
    )

    problem = drafts["AAPL"].problem  # 초안을 통째로 단언하면 실패 메시지에 문장이 찍힌다
    # EMPTY: 사고가 max_tokens를 다 써 text 없이 끝난 응답(#14 실측)도 여기서 잡는다
    assert problem not in {DraftProblem.EMPTY, DraftProblem.JSON_INVALID, DraftProblem.LLM_FAILED, DraftProblem.CALL_LIMIT}
