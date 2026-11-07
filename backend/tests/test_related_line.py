"""입구 1: 세 번째 줄 연관 소식(#67). 시나리오 + 연관 종목 행 + 가짜 출처·LLM → MorningPipeline.run → 저장소 읽기 함수·실행 요약·가짜 기록.
생성 대상은 시나리오 커버 범위(run이 기본 종목으로 넣는다). 연관 종목은 그 전에 커버 범위에만 넣어 카드 대상이 아니다."""

import dataclasses
import json
import subprocess
import sys
from datetime import datetime

import pytest

from m30.adapters import Source
from m30.adapters.fake import FailurePlan
from m30.adapters.filings import AnnualReport
from m30.config import ET
from m30.models import (
    Classification,
    Coverage,
    HoldItem,
    HoldLine,
    HoldStage,
    LineStatus,
    NewsKind,
    RelatedTicker,
    Relation,
    RelationBasis,
)
from m30.pipeline.classify import CLASSIFY_SYSTEM
from m30.pipeline.newsline import NEWSLINE_SYSTEM, RETRY_COPY_WORD
from m30.pipeline.review import FACTCHECK_SYSTEM
from conftest import SCENARIOS
from test_collect_classify import AAPL, FRI, filing, label, reply, run, scenario
from test_morning_pipeline import run_rows

BACKEND = SCENARIOS.parent
NVDA = Coverage("NVDA", "NVIDIA Corporation", cik="0001045810")
INTC = Coverage("INTC", "Intel Corporation", cik="0000050863")
AMD = Coverage("AMD", "Advanced Micro Devices, Inc.", cik="0000002488")
TSM = Coverage("TSM", "Taiwan Semiconductor Manufacturing Co Ltd", cik="0001046179")
QCOM = Coverage("QCOM", "Qualcomm Inc", cik="0000804328")
FACT = json.dumps({"label": "fact"})
AMD_EARNINGS = "AMD reported third quarter revenue of $7.7 billion."


def relate(store, relations, others=(AMD, TSM, QCOM)):
    """others = 연관 종목 후보(커버 범위에만, 생성 대상 아님). relations = {티커: [(연관 종목, 관계), …]} rank 순.
    근거는 관계에 맞게: peer = 업종, 그 밖 = 그 종목의 10-K(접수번호 {cik}-25-000001)."""
    store.upsert_coverage([*others, *(c for c in relations if c not in others)])
    rows = {}
    for cov, related in relations.items():
        accession = None
        if any(relation is not Relation.PEER for _, relation in related):
            accession = f"{cov.cik}-25-000001"
            store.save_annual_report(AnnualReport(accession, cov.cik, datetime(2025, 10, 31, tzinfo=ET), "Item 1. Business"))
        rows[cov.ticker] = [
            RelatedTicker(cov.ticker, other.ticker, relation, RelationBasis.SIC if relation is Relation.PEER else RelationBasis.OWN_10K,
                          rank, None if relation is Relation.PEER else accession, None if relation is Relation.PEER else "Evidence.")
            for rank, (other, relation) in enumerate(related, 1)
        ]
    store.replace_relations(rows)


def sentence(text):
    return json.dumps({"sentence": text})


def related(card):
    """(문구, 상태, 출처 범위, 건수)."""
    line = card.related_line
    return line.text, line.status, line.source_scope, card.related_line_filing_count


def cards(store):
    return {c.ticker: c for c in store.list_cards(FRI)}


def test_연관_종목의_그날_공시가_관계_단어로_시작하는_세_번째_줄이_된다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})
    amd = filing(1, cik=AMD.cik, items=("2.02",), exhibit99=AMD_EARNINGS)

    run(store, scenario([NVDA], [amd], [reply(label(1, "AMD", kind="earnings", importance=5)),
                                         sentence("AMD reported Q3 revenue of $7.7B"), FACT]))

    assert related(cards(store)["NVDA"]) == (
        "Competitor AMD reported Q3 revenue of $7.7B (SEC filing)", LineStatus.CHECKED_FOUND, "SEC filings", 1)



def amd5(n=1, at="2026-10-15T10:00:00-04:00"):
    """AMD 실적 공시(항목 2.02). 분류 중요도는 테스트가 정한다."""
    return filing(n, at, cik=AMD.cik, items=("2.02",), exhibit99=AMD_EARNINGS)


AMD_LINE = "AMD reported Q3 revenue of $7.7B"
AMD_REPLIES = (sentence(AMD_LINE), FACT)  # 분류 뒤: 연관 1등 초안 → 판정


def test_연관_종목_공시만_더_받고_연관도_대상도_아닌_회사는_받지_않으며_연관_종목_카드는_만들지_않는다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR), (TSM, Relation.SUPPLIER)]})
    amd = amd5()

    ran = run(store, scenario([NVDA], [amd], [reply(label(1, "AMD", kind="earnings", importance=5)), *AMD_REPLIES]))

    assert ran.filings.calls == [AMD.cik, NVDA.cik, TSM.cik]  # CIK 순. QCOM은 커버 범위에만 있다
    assert list(cards(store)) == ["NVDA"]
    assert store.list_classifications(FRI) == [Classification(amd.accession, "AMD", NewsKind.EARNINGS, 5, False)]
    assert (ran.summary.filing_ciks, ran.summary.related_ciks) == (3, 2)


def test_같은_공시가_여러_카드의_연관_소식이면_분류·문장·판정은_한_번이고_두_줄은_관계_단어만_다르다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)], AAPL: [(AMD, Relation.SUPPLIER)]})

    ran = run(store, scenario([AAPL, NVDA], [amd5()], [reply(label(1, "AMD", kind="earnings", importance=5)), *AMD_REPLIES]))

    assert {t: c.related_line.text for t, c in cards(store).items()} == {
        "AAPL": "Supplier AMD reported Q3 revenue of $7.7B (SEC filing)",
        "NVDA": "Competitor AMD reported Q3 revenue of $7.7B (SEC filing)",
    }
    assert [r.system for r in ran.llm.requests] == [CLASSIFY_SYSTEM, NEWSLINE_SYSTEM, FACTCHECK_SYSTEM]


def test_연관_소식_문장_요청은_첫_번째_줄_요청과_같고_카드_종목·관계를_모른다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)], AAPL: [(AMD, Relation.SUPPLIER)]})

    ran = run(store, scenario([AAPL, NVDA], [amd5()], [reply(label(1, "AMD", kind="earnings", importance=5)), *AMD_REPLIES]))

    [request] = [r for r in ran.llm.requests if r.system == NEWSLINE_SYSTEM]
    data = json.loads(request.user.split("<news>\n", 1)[1].split("\n</news>", 1)[0])
    assert data["company"] == "Advanced Micro Devices, Inc."
    assert [w for w in ("NVIDIA", "NVDA", "Apple", "AAPL", "ompetitor", "upplier", "relat") if w in request.user] == []


AT = "2026-10-15T{}:00:00-04:00"


def f(n, cov, hour, text):
    return filing(n, AT.format(hour), cik=cov.cik, exhibit99=text)


AMD_CFO = "AMD named a new chief financial officer"
AMD_DEAL = "AMD signed a supply agreement with a cloud provider"
TSM_PLANT = "TSMC opened a new chip plant in Arizona"


def acc(cov, n):
    return f"{cov.cik}-26-{n:06d}"


@pytest.mark.parametrize(
    "filings, labels, line_reply, expected, ranked",
    [
        ([(1, AMD, 10, AMD_CFO)], [(1, "AMD", 3, False)], None,
         ("No major related filings found", LineStatus.CHECKED_NONE, "SEC filings", None), []),
        ([(1, AMD, 10, AMD_CFO), (2, TSM, 11, TSM_PLANT)], [(1, "AMD", 4, False), (2, "TSM", 5, False)], TSM_PLANT,
         (f"Supplier {TSM_PLANT} +1 more (SEC filing)", LineStatus.CHECKED_FOUND, "SEC filings", 2), [acc(TSM, 2), acc(AMD, 1)]),
        ([(1, AMD, 10, AMD_CFO), (2, TSM, 11, TSM_PLANT)], [(1, "AMD", 4, False), (2, "TSM", 4, False)], AMD_CFO,
         (f"Competitor {AMD_CFO} +1 more (SEC filing)", LineStatus.CHECKED_FOUND, "SEC filings", 2), [acc(AMD, 1), acc(TSM, 2)]),
        ([(1, AMD, 10, AMD_CFO), (2, AMD, 11, AMD_DEAL)], [(1, "AMD", 4, False), (2, "AMD", 4, False)], AMD_DEAL,
         (f"Competitor {AMD_DEAL} +1 more (SEC filing)", LineStatus.CHECKED_FOUND, "SEC filings", 2), [acc(AMD, 2), acc(AMD, 1)]),
        ([(1, AMD, 10, AMD_CFO), (2, TSM, 11, TSM_PLANT), (3, QCOM, 12, "Qualcomm named a new chief executive")],
         [(1, "AMD", 5, True), (2, "TSM", 4, False), (3, "QCOM", 4, False)], TSM_PLANT,
         (f"Supplier {TSM_PLANT} +1 more (SEC filing)", LineStatus.CHECKED_FOUND, "SEC filings", 2), [acc(TSM, 2), acc(QCOM, 3)]),
        ([(1, AMD, 10, AMD_CFO), (2, TSM, 11, TSM_PLANT)], [(2, "TSM", 3, False)], None,
         ("Update delayed", LineStatus.DELAYED, "SEC filings", None), []),
    ],
    ids=["중요도_3만이면_없음", "중요도_높은_쪽이_1등", "같은_중요도면_관계_순서", "같은_관계면_늦게_접수된_쪽",
         "의견글은_후보·건수_밖이고_peer는_supplier_뒤", "후보가_없고_미분류가_있으면_지연"],
)
def test_세_번째_줄_1등은_중요도_4_이상_중_중요도·관계·접수_시각_순이고_나머지는_더_있음_건수다(store, filings, labels, line_reply,
                                                                                    expected, ranked):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR), (TSM, Relation.SUPPLIER), (QCOM, Relation.PEER)]})
    replies = [reply(*(label(n, t, importance=i, opinion=o) for n, t, i, o in labels))]
    if line_reply:
        replies += [sentence(line_reply), FACT]

    ran = run(store, scenario([NVDA], [f(*row) for row in filings], replies))

    assert related(cards(store)["NVDA"]) == expected
    assert [c.accession for c in ran.summary.related["NVDA"].candidates] == ranked  # 1등 = 초안을 받은 공시
    if ranked:
        [request] = [r for r in ran.llm.requests if r.system == NEWSLINE_SYSTEM]
        assert dict(filings_text(filings))[ranked[0]] in request.user


def filings_text(filings):
    return [(acc(cov, n), text) for n, cov, _, text in filings]


def test_카드_종목_자신이_걸린_공시는_연관_회사와_같이_냈어도_첫_번째_줄_몫이라_세_번째_줄_후보도_건수도_아니다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})
    own = f(1, NVDA, 10, "NVIDIA named a new chief financial officer")
    joint = dataclasses.replace(own, cik=AMD.cik)  # 공동 제출: 같은 접수번호가 두 CIK에서 온다 → 연결 티커 AMD·NVDA
    replies = [reply(label(1, "NVDA", importance=5), label(2, "AMD", importance=4)),
               sentence("NVIDIA named a new chief financial officer"), FACT, sentence(AMD_CFO), FACT]

    run(store, scenario([NVDA], [own, joint, f(2, AMD, 11, AMD_CFO)], replies))

    nvda = cards(store)["NVDA"]
    assert (nvda.news_line.text, nvda.news_line_filing_count) == ("NVIDIA named a new chief financial officer (SEC filing)", 1)
    assert related(nvda) == (f"Competitor {AMD_CFO} (SEC filing)", LineStatus.CHECKED_FOUND, "SEC filings", 1)


FAIL_TSM = {(Source.SEC_FILINGS, TSM.cik): FailurePlan("error")}


def test_연관_회사_하나라도_공시를_못_받으면_그_카드의_세_번째_줄만_지연이고_다른_카드·첫_번째_줄은_그대로다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR), (TSM, Relation.SUPPLIER)], INTC: [(AMD, Relation.COMPETITOR)]})

    ran = run(store, scenario([INTC, NVDA], [amd5()], [reply(label(1, "AMD", kind="earnings", importance=5)), *AMD_REPLIES],
                              failures=FAIL_TSM))

    saved = cards(store)
    assert related(saved["NVDA"]) == ("Update delayed", LineStatus.DELAYED, "SEC filings", None)
    assert related(saved["INTC"]) == ("Competitor AMD reported Q3 revenue of $7.7B (SEC filing)", LineStatus.CHECKED_FOUND,
                                      "SEC filings", 1)
    assert saved["NVDA"].news_line.status is LineStatus.CHECKED_NONE
    assert [f.subject for f in ran.summary.failures] == [TSM.cik]


def test_재실행에서_연관_회사_공시를_못_받으면_앞_실행이_확인한_세_번째_줄을_그대로_둔다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR), (TSM, Relation.SUPPLIER)]})
    classified = reply(label(1, "AMD", kind="earnings", importance=5))
    run(store, scenario([NVDA], [amd5()], [classified, *AMD_REPLIES]))
    before = cards(store)["NVDA"]

    run(store, scenario([NVDA], [amd5()], [classified], failures=FAIL_TSM))  # 지연이라 초안·판정을 부르지 않는다

    after = cards(store)["NVDA"]
    assert (after.related_line, after.related_line_filing_count) == (before.related_line, 1)  # 확인 시각까지 그대로


ARM = Coverage("ARM", "Arm Holdings plc")  # CIK 없음
SPY = Coverage("SPY", "SPDR S&P 500 ETF", holdings_ticker="SPY")


def test_연관_종목이_없거나_CIK가_없거나_ETF면_세_번째_줄은_미지원이고_연관_공시를_받지_않는다(store):
    relate(store, {INTC: [(ARM, Relation.PEER)], SPY: [(AMD, Relation.PEER)]}, others=(AMD, ARM))  # ETF 행은 코드가 무시한다

    ran = run(store, scenario([INTC, NVDA, SPY], [amd5()]))

    assert {t: related(c) for t, c in cards(store).items()} == dict.fromkeys(
        ["INTC", "NVDA", "SPY"], ("Not covered yet", LineStatus.UNSUPPORTED, None, None))
    assert AMD.cik not in ran.filings.calls
    assert ran.llm.requests == []


BAD = "AMD reported Q3 revenue of $7.7B with an impact on rivals"
STILL_BAD = "AMD reported Q3 revenue of $7.7B that could affect rivals"
RELATED_REPLACEMENT = "Competitor Advanced Micro Devices reported quarterly results (SEC filing)"


def held_day(news_replies, related_replies):
    """NVDA 자기 공시(중요도 5, 첫 번째 줄) + AMD 실적 공시(중요도 5, 세 번째 줄). 분류 뒤 첫 번째 줄 응답 → 세 번째 줄 응답."""
    own = filing(1, AT.format(10), cik=NVDA.cik, exhibit99="NVIDIA agreed to acquire a startup.")
    labels = reply(label(1, "NVDA", kind="deal", importance=5), label(2, "AMD", kind="earnings", importance=5))
    return scenario([NVDA], [own, amd5(2, AT.format(11))], [labels, *news_replies, *related_replies])


BUY = sentence("NVIDIA agreed to buy a startup")
NEWS_PASS = (sentence("NVIDIA agreed to acquire a startup"), FACT)
NEWS_HELD = (BUY, BUY)
RELATED_HELD = (sentence(BAD), sentence(STILL_BAD))
NVDA_ACC, AMD_ACC = f"{NVDA.cik}-26-000001", f"{AMD.cik}-26-000002"
NEWS_HOLD = HoldItem("NVDA", FRI, NVDA_ACC, HoldStage.COPY_RULES, "NVIDIA agreed to buy a startup",
                     ("1 copy_rules: 금지어 'buy'", "2 copy_rules: 금지어 'buy'"), "NVIDIA filed a company update (SEC filing)")
RELATED_HOLD = HoldItem("NVDA", FRI, AMD_ACC, HoldStage.COPY_RULES, STILL_BAD,
                        ("1 copy_rules: 금지어 'impact on'", "2 copy_rules: 금지어 'could affect'"), RELATED_REPLACEMENT,
                        line=HoldLine.RELATED)


def test_연관_소식이_영향_표현이면_이유를_넣어_재생성하고_또_걸리면_관계_단어를_붙인_대체_줄과_보류함_행이다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})

    ran = run(store, held_day(NEWS_HELD, RELATED_HELD))

    first, second = [r for r in ran.llm.requests if r.system == NEWSLINE_SYSTEM and "Advanced Micro" in r.user]
    assert RETRY_COPY_WORD.format(word="impact on") in second.user and second.user.startswith(first.user)
    assert related(cards(store)["NVDA"]) == (RELATED_REPLACEMENT, LineStatus.CHECKED_FOUND, "SEC filings", 1)
    assert store.list_hold_items(FRI) == [RELATED_HOLD, NEWS_HOLD]  # 첫 번째 줄 행과 따로(종목, 접수번호 순)


@pytest.mark.parametrize(
    "news_replies, related_replies, left",
    [(NEWS_HELD, (sentence(AMD_LINE), FACT), [NEWS_HOLD]), (NEWS_PASS, RELATED_HELD, [RELATED_HOLD])],
    ids=["세_번째_줄이_통과하면_그_행만_지운다", "첫_번째_줄이_통과하면_그_행만_지운다"],
)
def test_재실행에서_통과한_줄의_대기_행만_지우고_다른_줄_행은_그대로다(store, news_replies, related_replies, left):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})
    run(store, held_day(NEWS_HELD, RELATED_HELD))

    run(store, held_day(news_replies, related_replies))

    assert store.list_hold_items(FRI) == left


HUMAN = "Competitor AMD reported Q3 revenue (SEC filing)"


def test_세_번째_줄을_재발행하면_재실행이_덮지_않고_첫_번째_줄은_재발행_행이_없으니_다시_만든다(store, admin):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})
    run(store, held_day(NEWS_HELD, RELATED_HELD))
    with admin.transaction():
        admin.execute("set local role service_role")
        admin.execute("update public.hold_queue set edited_text = %s, state = 'republished' where line = 'related'", (HUMAN,))

    run(store, held_day(NEWS_PASS, RELATED_HELD))

    nvda = cards(store)["NVDA"]
    assert related(nvda) == (HUMAN, LineStatus.CHECKED_FOUND, "SEC filings", 1)
    assert nvda.news_line.text == "NVIDIA agreed to acquire a startup (SEC filing)"
    assert [(h.line, h.state) for h in store.list_hold_items(FRI)] == [(HoldLine.RELATED, "republished")]


def test_실행당_LLM_호출_상한에_연관_1등_공시마다_4를_더한다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)], AAPL: [(AMD, Relation.SUPPLIER)], INTC: [(TSM, Relation.COMPETITOR)]})
    tsm = f(2, TSM, 11, TSM_PLANT)
    replies = [reply(label(1, "AMD", kind="earnings", importance=5), label(2, "TSM", importance=4)),
               sentence(AMD_LINE), sentence(TSM_PLANT), FACT, FACT]

    ran = run(store, scenario([AAPL, INTC, NVDA], [amd5(), tsm], replies))

    assert ran.summary.llm_call_limit == 3 * 4 + 1 + 4 * 2  # 대상 3 × 4 + 묶음 1 + 연관 1등 공시 2(AMD는 두 카드가 같이 쓴다)


def test_상한이_다하면_세_번째_줄은_호출_상한_대체_줄과_보류함_행이고_첫_번째_줄은_먼저_처리된다(store):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})
    own = filing(1, AT.format(10), cik=NVDA.cik, exhibit99="NVIDIA named a new chief financial officer.")
    labels = reply(label(1, "NVDA", kind="leadership", importance=5), label(2, "AMD", kind="earnings", importance=5))
    cfo = sentence("NVIDIA named a new chief financial officer")
    forecast = json.dumps({"label": "forecast"})
    # 상한 1 × 4 + 1 + 4 = 9: 분류 깨짐·분류, 첫 번째 줄 초안 깨짐·초안, 판정 깨짐·forecast, 재생성 깨짐·재생성, 판정 깨짐 → 세 번째 줄 차례에 0
    ran = run(store, scenario([NVDA], [own, amd5(2, AT.format(11))], ["x", labels, "x", cfo, "x", forecast, "x", cfo, "x"]))

    assert ran.summary.llm_calls == ran.summary.llm_call_limit == 9
    assert related(cards(store)["NVDA"]) == (RELATED_REPLACEMENT, LineStatus.CHECKED_FOUND, "SEC filings", 1)
    holds = {h.line: (h.stage, h.draft_text, h.rules) for h in store.list_hold_items(FRI)}
    assert holds == {
        HoldLine.NEWS: (HoldStage.FACT_CHECK, "NVIDIA named a new chief financial officer",
                        ("1 fact_check: forecast", "2 fact_check: call_limit")),
        HoldLine.RELATED: (HoldStage.DRAFT, None, ("1 draft: call_limit",)),
    }


def test_종목_예외_대체_카드의_세_번째_줄은_주식이면_지연이고_ETF면_미지원이다(store, monkeypatch):
    real = store.save_card

    def save_card(card, holds, related_holds=None):
        if related_holds is not None:  # 정상 카드 저장만 실패(대체 카드는 보류함을 넘기지 않는다)
            raise RuntimeError("bug")
        real(card, holds, related_holds)

    monkeypatch.setattr(store, "save_card", save_card)

    run(store, scenario([NVDA, SPY]))

    assert {t: related(c) for t, c in cards(store).items()} == {
        "NVDA": ("Update delayed", LineStatus.DELAYED, "SEC filings", None),
        "SPY": ("Not covered yet", LineStatus.UNSUPPORTED, None, None),
    }


def test_실행_기록과_요약에_세_번째_줄_상태별_카드_수와_연관_초안·검수_건수가_남는다(store, admin):
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})

    run(store, held_day(NEWS_HELD, RELATED_HELD))

    [(_, _, record)] = run_rows(admin)
    assert record["lines"]["related"] == {"checked_found": 1, "checked_none": 0, "delayed": 0, "unsupported": 0}
    assert {k: record["counts"][k] for k in ("filing_ciks", "related_ciks", "related_drafts", "related_review_pass_first",
                                             "related_review_pass_retry", "related_review_replaced")} == {
        "filing_ciks": 2, "related_ciks": 1, "related_drafts": 1, "related_review_pass_first": 0, "related_review_pass_retry": 0,
        "related_review_replaced": 1}
    assert STILL_BAD not in json.dumps(record) and "Advanced Micro" not in json.dumps(record)


CANARY = "AMD reported Q3 revenue of $7.7B with an impact on CanaryRivalQz"  # 검수 전 문장. 공개 로그에 나오면 샌 것


def test_CLI는_세_번째_줄_초안·검수_결과를_종목별_코드로만_찍고_문장·회사_이름은_찍지_않는다(store, tmp_path):
    # 입구: 시나리오 CLI를 하위 프로세스로(로컬 DB). 연관 종목 행은 먼저 심는다. AMD도 생성 대상이라 첫 번째 줄을 먼저 쓴다
    relate(store, {NVDA: [(AMD, Relation.COMPETITOR)]})
    amd = amd5()
    path = tmp_path / "related.json"
    path.write_text(json.dumps({
        "coverage": [{"ticker": t.ticker, "name": t.name, "cik": t.cik} for t in (AMD, NVDA)],
        "prices": {},
        "filings": {AMD.cik: [{"accession": amd.accession, "form": "8-K", "accepted_at": "2026-10-15T10:00:00-04:00",
                               "items": ["2.02"], "body": None, "exhibit99": AMD_EARNINGS}]},
        "llm_replies": [{"items": [label(1, "AMD", kind="earnings", importance=5)]}, {"sentence": AMD_LINE}, {"label": "fact"},
                        {"sentence": CANARY}, {"sentence": CANARY}],  # 분류 → AMD 첫 번째 줄·판정 → NVDA 세 번째 줄·재생성
    }))
    r = subprocess.run([sys.executable, "-m", "m30.pipeline", "2026-10-16", "--scenario", str(path)],
                       cwd=BACKEND, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr

    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert {"related_drafts: NVDA=ok", "related_review: NVDA=hold:copy_rules+retry"} <= set(lines)
    assert "related[checked_found=1 unsupported=1]" in next(line for line in lines if line.startswith("lines: "))
    assert [c for c in ("CanaryRivalQz", "Advanced Micro", "Competitor") if c in out] == []
