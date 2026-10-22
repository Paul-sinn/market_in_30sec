"""가짜 시세·일정·공시·지표·LLM 어댑터. 시나리오 JSON 파일에서 데이터를 읽는다."""

import json
from collections import Counter
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from m30.adapters import AccessDeniedError, RateLimitedError, Source, SourceError, TransientSourceError
from m30.adapters.events import CorporateEvent, Earnings, EarningsTiming, ExDividend
from m30.adapters.filings import Filing, FilingForm
from m30.adapters.indicators import IndicatorRelease
from m30.adapters.prices import DailyBar
from m30.llm import LLMRequest
from m30.models import Coverage

REQUIRED_KEYS = {"coverage", "prices"}
OPTIONAL_KEYS = {"events", "filings", "indicators", "llm_replies", "failures"}  # 다음 티켓은 선택 키로 더한다
BAR_KEYS = {f.name for f in fields(DailyBar)}
PRICE_KEYS = {"open", "high", "low", "close"}
EVENT_KEYS = {"earnings": {"kind", "day", "confirmed", "timing"}, "ex_dividend": {"kind", "day", "amount"}}
FILING_KEYS = {"accession", "form", "accepted_at", "items", "body", "exhibit99"}
FILING_OPTIONAL_KEYS = {"report_date"}  # "YYYY-MM-DD" 또는 null
INDICATOR_KEYS = {"name", "released_at"}
FAILURE_KEYS = {"source", "subject", "error", "times"}
FAILURE_ERRORS = {"transient": TransientSourceError, "access_denied": AccessDeniedError, "error": SourceError,
                  "rate_limited": RateLimitedError}
NO_SUBJECT = {Source.INDICATORS, Source.LLM}  # 대상 없이 출처 전체에 거는 실패. LLM은 호출 순서대로 앞의 times번


@dataclass(frozen=True)
class FailurePlan:
    error: str  # FAILURE_ERRORS의 키
    times: int | None = None  # 이만큼 실패한 뒤 정상. None = 계속 실패


@dataclass(frozen=True)
class Scenario:
    coverage: list[Coverage]
    prices: dict[str, list[DailyBar]]  # 티커 → 날짜 오름차순
    events: dict[str, list[CorporateEvent]] = field(default_factory=dict)  # 키가 없는 티커 = 일정 미지원
    filings: dict[str, list[Filing]] = field(default_factory=dict)  # CIK → 공시. 키가 없는 CIK = []
    indicators: list[IndicatorRelease] = field(default_factory=list)
    llm_replies: list[str] = field(default_factory=list)  # 호출 순서대로
    # (출처, 대상) → 실패 계획. 대상: 시세·일정은 티커, 공시는 CIK, 지표·LLM은 None
    failures: dict[tuple[Source, str | None], FailurePlan] = field(default_factory=dict)


def load_scenario(path: Path) -> Scenario:
    path = Path(path)
    raw = json.loads(path.read_text(), parse_float=Decimal)
    if not REQUIRED_KEYS <= set(raw) <= REQUIRED_KEYS | OPTIONAL_KEYS:
        raise ValueError(
            f"{path.name}: top-level keys must be {sorted(REQUIRED_KEYS)} plus optional {sorted(OPTIONAL_KEYS)},"
            f" got {sorted(raw)}"
        )
    prices = {}
    for ticker, rows in raw["prices"].items():
        bars = sorted((_bar(path, ticker, row) for row in rows), key=lambda b: b.day)
        days = [b.day for b in bars]
        if len(set(days)) != len(days):
            raise ValueError(f"{path.name}: {ticker} has two bars on the same day")
        prices[ticker] = bars
    events = {
        ticker: [_event(path, ticker, row) for row in rows] for ticker, rows in raw.get("events", {}).items()
    }
    return Scenario(
        coverage=[_coverage(row) for row in raw["coverage"]],
        prices=prices,
        events=events,
        filings={cik: [_filing(path, cik, row) for row in rows] for cik, rows in raw.get("filings", {}).items()},
        indicators=[_indicator(path, row) for row in raw.get("indicators", [])],
        # default=float: parse_float=Decimal로 읽은 숫자를 JSON 숫자로 되돌린다
        llm_replies=[r if isinstance(r, str) else json.dumps(r, default=float) for r in raw.get("llm_replies", [])],
        failures=_failures(path, raw.get("failures", [])),
    )


def _failures(path: Path, rows: list) -> dict[tuple[Source, str | None], FailurePlan]:
    plans = {}
    for row in rows:
        if not {"source", "error"} <= set(row) <= FAILURE_KEYS:
            raise ValueError(f"{path.name}: failure keys must be source, error plus optional subject, times, got {sorted(row)}")
        if row["source"] not in tuple(Source):
            raise ValueError(f"{path.name}: failure key 'source' must be one of {[s.value for s in Source]}")
        source, subject, times = Source(row["source"]), row.get("subject"), row.get("times")
        if isinstance(subject, str) == (source in NO_SUBJECT):
            need = "must not have" if source in NO_SUBJECT else "needs a string"
            raise ValueError(f"{path.name}: {source} failure {need} key 'subject'")
        if row["error"] not in FAILURE_ERRORS:
            raise ValueError(f"{path.name}: failure key 'error' must be one of {sorted(FAILURE_ERRORS)}")
        if times is not None and (isinstance(times, bool) or not isinstance(times, int) or times < 1):
            raise ValueError(f"{path.name}: failure key 'times' must be an integer of 1 or more")
        if (source, subject) in plans:
            raise ValueError(f"{path.name}: two failures for {source} {subject or ''}".rstrip())
        plans[(source, subject)] = FailurePlan(row["error"], times)
    return plans


def _coverage(row: dict) -> Coverage:
    if row.get("leverage") is not None:
        row = {**row, "leverage": Decimal(row["leverage"])}
    return Coverage(**row)


def _aware(path: Path, where: str, value: object) -> datetime:
    at = datetime.fromisoformat(value) if isinstance(value, str) else None
    if at is None or at.utcoffset() is None:
        raise ValueError(f"{path.name}: {where} must be an ISO date-time with a time zone")
    return at


def _filing(path: Path, cik: str, row: dict) -> Filing:
    if not FILING_KEYS <= set(row) <= FILING_KEYS | FILING_OPTIONAL_KEYS:
        raise ValueError(
            f"{path.name}: filing of {cik} keys must be {sorted(FILING_KEYS)} plus optional {sorted(FILING_OPTIONAL_KEYS)},"
            f" got {sorted(row)}"
        )
    where = f"filing {row['accession']} of {cik}"
    if row["form"] not in tuple(FilingForm):
        raise ValueError(f"{path.name}: {where} key 'form' must be one of {[f.value for f in FilingForm]}")
    if not isinstance(row["items"], list) or not all(isinstance(i, str) for i in row["items"]):
        raise ValueError(f"{path.name}: {where} key 'items' must be a list of strings")
    for key in ("accession", "body", "exhibit99"):
        if not isinstance(row[key], str) and (key == "accession" or row[key] is not None):
            raise ValueError(f"{path.name}: {where} key '{key}' must be a string" + ("" if key == "accession" else " or null"))
    report_date = row.get("report_date")
    try:
        report_date = None if report_date is None else date.fromisoformat(report_date)
    except (TypeError, ValueError):
        raise ValueError(f"{path.name}: {where} key 'report_date' must be a YYYY-MM-DD date or null") from None
    return Filing(
        accession=row["accession"],
        cik=cik,
        form=FilingForm(row["form"]),
        accepted_at=_aware(path, f"{where} key 'accepted_at'", row["accepted_at"]),
        items=tuple(row["items"]),
        body=row["body"],
        exhibit99=row["exhibit99"],
        raw=json.dumps(row, ensure_ascii=False, sort_keys=True),
        report_date=report_date,
    )


def _indicator(path: Path, row: dict) -> IndicatorRelease:
    if set(row) != INDICATOR_KEYS:
        raise ValueError(f"{path.name}: indicator keys must be {sorted(INDICATOR_KEYS)}, got {sorted(row)}")
    if not isinstance(row["name"], str):
        raise ValueError(f"{path.name}: indicator key 'name' must be a string")
    return IndicatorRelease(
        name=row["name"],
        released_at=_aware(path, f"indicator {row['name']} key 'released_at'", row["released_at"]),
        raw=json.dumps(row, ensure_ascii=False, sort_keys=True),
    )


def _event(path: Path, ticker: str, row: dict) -> CorporateEvent:
    keys = EVENT_KEYS.get(row.get("kind"))
    if keys is None:
        raise ValueError(f"{path.name}: {ticker} event key 'kind' must be one of {sorted(EVENT_KEYS)}")
    if set(row) != keys:
        raise ValueError(f"{path.name}: {ticker} {row['kind']} keys must be {sorted(keys)}, got {sorted(row)}")
    day = date.fromisoformat(row["day"])
    if row["kind"] == "earnings":
        if not isinstance(row["confirmed"], bool):
            raise ValueError(f"{path.name}: {ticker} earnings key 'confirmed' must be true or false")
        if row["timing"] not in (None, *EarningsTiming):
            timings = [t.value for t in EarningsTiming]
            raise ValueError(f"{path.name}: {ticker} earnings key 'timing' must be one of {timings} or null")
        timing = None if row["timing"] is None else EarningsTiming(row["timing"])
        return Earnings(day=day, confirmed=row["confirmed"], timing=timing)
    amount = row["amount"]
    if isinstance(amount, bool) or not isinstance(amount, int | Decimal) or amount <= 0:
        raise ValueError(f"{path.name}: {ticker} ex_dividend key 'amount' must be a number greater than 0")
    return ExDividend(day=day, amount=Decimal(amount))


def _bar(path: Path, ticker: str, row: dict) -> DailyBar:
    if set(row) != BAR_KEYS:
        raise ValueError(f"{path.name}: {ticker} bar keys must be {sorted(BAR_KEYS)}, got {sorted(row)}")
    if not isinstance(row["adjusted"], bool):
        raise ValueError(f"{path.name}: {ticker} bar key 'adjusted' must be true or false")
    return DailyBar(
        day=date.fromisoformat(row["day"]),
        **{k: Decimal(row[k]) for k in PRICE_KEYS},
        volume=int(row["volume"]),
        adjusted=row["adjusted"],
    )


class _Failures:
    """실패 계획대로 예외를 낸다. 대상마다 times번 실패한 뒤 정상(가짜를 만들 때마다 처음부터 센다)."""

    def __init__(self, scenario: Scenario, source: Source) -> None:
        self._source = source
        self._plans = {subject: plan for (s, subject), plan in scenario.failures.items() if s is source}
        self._failed: Counter[str | None] = Counter()

    def check(self, subject: str | None) -> None:
        plan = self._plans.get(subject)
        if plan is None or (plan.times is not None and self._failed[subject] >= plan.times):
            return
        self._failed[subject] += 1
        raise FAILURE_ERRORS[plan.error](f"fake {self._source} {plan.error}")


def _in_range(row: object, start: date, end: date) -> bool:
    """날짜가 start~end면 True. 날짜가 아닌 이상한 값은 거르지 않고 넘겨 파이프라인 검증이 받게 한다."""
    day = getattr(row, "day", None)
    return type(day) is not date or start <= day <= end


class FakePriceSource:
    def __init__(self, scenario: Scenario) -> None:
        self._prices = scenario.prices
        self._failures = _Failures(scenario, Source.PRICES)
        self.calls: list[str] = []

    def daily_bars(self, ticker: str, start: date, end: date) -> list[DailyBar]:
        self.calls.append(ticker)
        self._failures.check(ticker)
        return [b for b in self._prices.get(ticker, []) if _in_range(b, start, end)]


class FakeEventSource:
    def __init__(self, scenario: Scenario) -> None:
        self._events = scenario.events
        self._failures = _Failures(scenario, Source.EVENTS)
        self.calls: list[str] = []

    def upcoming_events(self, ticker: str, start: date, end: date) -> list[CorporateEvent] | None:
        self.calls.append(ticker)
        self._failures.check(ticker)
        if ticker not in self._events:
            return None
        return [e for e in self._events[ticker] if _in_range(e, start, end)]


class FakeFilingSource:
    """기간으로 거르지 않고 그 CIK의 공시를 전부 돌려준다: 파이프라인의 기간 거르기를 시험하려고(어댑터가 범위를 어긴 경우와 같다)."""

    def __init__(self, scenario: Scenario) -> None:
        self._filings = scenario.filings
        self._failures = _Failures(scenario, Source.SEC_FILINGS)
        self.calls: list[str] = []

    def filings(self, cik: str, since: datetime, until: datetime) -> list[Filing]:
        self.calls.append(cik)
        self._failures.check(cik)
        return list(self._filings.get(cik, []))


class FakeIndicatorSource:
    """FakeFilingSource와 같은 이유로 날짜로 거르지 않는다."""

    def __init__(self, scenario: Scenario) -> None:
        self._releases = scenario.indicators
        self._failures = _Failures(scenario, Source.INDICATORS)
        self.calls: list[None] = []

    def releases(self, start: date, end: date) -> list[IndicatorRelease]:
        self.calls.append(None)
        self._failures.check(None)
        return list(self._releases)


_NO_REPLY = object()


class FakeLLM:
    """정해진 응답을 호출 순서대로 돌려주고 받은 요청을 기록한다. 실패한 시도는 응답을 쓰지 않는다."""

    def __init__(self, scenario: Scenario) -> None:
        self._replies = iter(scenario.llm_replies)
        self._failures = _Failures(scenario, Source.LLM)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        self._failures.check(None)
        reply = next(self._replies, _NO_REPLY)  # None도 응답으로 돌려준다(이상한 값 시험)
        if reply is _NO_REPLY:  # 시나리오 작성 실수. SourceError로 감추지 않는다
            raise AssertionError(f"scenario has no llm reply for request {len(self.requests)}")
        return reply
