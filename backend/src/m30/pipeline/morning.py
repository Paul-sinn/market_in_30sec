"""아침 파이프라인. 바깥 인터페이스는 run 하나."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from m30.adapters import Source, SourceError
from m30.adapters.events import EventSource
from m30.adapters.filings import FilingForm, FilingSource
from m30.adapters.indicators import IndicatorSource
from m30.adapters.prices import PriceSource
from m30.config import ET
from m30.db.store import CardStore
from m30.llm import LLM, LLMBudget, LLMRequest
from m30.models import CardLine, CardStatus, Classification, Coverage, LineStatus, NewsCandidate, StockCard, TickerNews
from m30.pipeline.classify import Classified, FilingItem, SkippedBatch, batch_count, classify
from m30.pipeline.collect import (
    SourceCalls,
    SourceFailure,
    filing_window,
    valid_bars,
    valid_events,
    valid_filings,
    valid_releases,
)
from m30.pipeline.compute import bars_usable, change_pct
from m30.pipeline.lines import (
    EVENT_SCOPE,
    EVENT_WINDOW,
    PRICE_SCOPE,
    delayed_line,
    event_line,
    leverage_tag,
    news_template_line,
    price_fact_line,
)
from m30.pipeline.newsline import NewsDraft, write_news_drafts

LOOKBACK = timedelta(weeks=53)  # 52주 이력 + 52주 전 날이 휴장일이어도 거래일이 들어가는 1주


@dataclass(frozen=True)
class RunSummary:
    trading_day: date
    access_denied: tuple[Source, ...]  # 401·403이 난 출처. 요약 맨 위에 표시
    cards_saved: int
    change_delayed: tuple[str, ...]  # 등락률을 계산 못 해 delayed로 저장한 티커 (오름차순)
    failures: tuple[SourceFailure, ...]  # 재시도 뒤에도 실패한 출처·대상
    filings_collected: int  # 이번 거래일 공시 수(중복 제거 후)
    filings_unclassified: int  # 이번 거래일 공시 중 미분류
    classify_batches: int  # 분류 묶음 수
    skipped_batches: tuple[SkippedBatch, ...]  # 건너뛴 분류 묶음
    llm_calls: int  # 보낸 LLM 요청 수(재시도 포함)
    llm_call_limit: int  # 실행당 LLM 호출 상한
    news: dict[str, TickerNews]  # 커버 범위 티커 → 첫 번째 줄 상태·후보 (#6의 입력)
    drafts: dict[str, NewsDraft]  # 소식 있는 종목 → 첫 번째 줄 초안. 검수(#7) 전이라 카드·DB·CLI에 문장을 내보내지 않는다


class MorningPipeline:
    def __init__(
        self,
        *,
        prices: PriceSource,
        events: EventSource,
        filings: FilingSource,
        indicators: IndicatorSource,
        llm: LLM,
        store: CardStore,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # 출처는 기본값 없는 필수 키워드: 빠뜨리면 조용히 도는 대신 바로 실패한다
        self._prices = prices
        self._events = events
        self._filings = filings
        self._indicators = indicators
        self._llm = llm
        self._store = store
        self._sleep = sleep

    def run(self, trading_day: date) -> RunSummary:
        if isinstance(trading_day, datetime):
            # datetime은 date의 하위 클래스라 그대로 두면 시각이 거래일로 쓰인다
            raise TypeError("trading_day must be a date, not a datetime")
        checked_at = datetime.now(ET)  # 이 실행의 모든 줄이 같은 확인 시각을 쓴다
        calls = SourceCalls(self._sleep)
        coverage = self._store.list_coverage()
        items, failed_ciks = self._collect_filings(coverage, trading_day, calls)
        self._collect_indicators(trading_day, calls)
        budget = LLMBudget(self._llm, len(coverage) * 4 + batch_count(items))  # 생성 대상 = 커버 범위 전체(#8 전)

        def send(subject: str, request: LLMRequest) -> str:
            """LLM 호출 창구 하나: 분류(묶음 번호)·첫 번째 줄(접수번호)이 같은 상한·재시도·차단을 쓴다."""
            return calls.call(Source.LLM, subject, lambda: budget.complete(request), lambda text: isinstance(text, str))

        outcomes, skipped = classify(items, trading_day, lambda n, request: send(str(n), request))
        self._store.replace_classifications(trading_day, _classification_rows(items, outcomes))
        news = {cov.ticker: _ticker_news(cov, failed_ciks, items, outcomes) for cov in coverage}
        drafts = write_news_drafts(news, {i.filing.accession: i for i in items}, trading_day, send)
        saved = 0
        delayed = []
        for cov in coverage:
            try:
                bars = calls.call(
                    Source.PRICES,
                    cov.ticker,
                    lambda: self._prices.daily_bars(cov.ticker, trading_day - LOOKBACK, trading_day - timedelta(days=1)),
                    valid_bars,
                )
            except SourceError:
                bars = []  # 등락률·세 번째 줄 지연
            usable = bars_usable(bars, trading_day)  # 지난 카드 값은 읽지 않는다. 그날 받은 봉으로만
            pct = change_pct(bars) if usable else None
            price_fact = price_fact_line(bars, checked_at) if usable else delayed_line(PRICE_SCOPE, checked_at)
            news_line = news_template_line(news[cov.ticker], checked_at)  # LLM 초안은 검수(#7) 전에 카드에 쓰지 않는다
            self._store.upsert_card(
                StockCard(
                    ticker=cov.ticker,
                    trading_day=trading_day,
                    status=CardStatus.FALLBACK if news_line is None else CardStatus.NORMAL,  # 축소판 = 소식 있음, 검수 대기
                    change_pct=pct,
                    change_status=LineStatus.DELAYED if pct is None else LineStatus.CHECKED_FOUND,
                    news_line=news_line,
                    event_line=self._event_line(cov.ticker, trading_day, checked_at, calls),
                    price_fact_line=price_fact,
                    leverage_tag=leverage_tag(cov.leverage),
                )
            )
            saved += 1
            if pct is None:
                delayed.append(cov.ticker)
        return RunSummary(
            trading_day=trading_day,
            access_denied=calls.access_denied,
            cards_saved=saved,
            change_delayed=tuple(delayed),
            failures=calls.failures,
            filings_collected=len(items),
            filings_unclassified=sum(not isinstance(o, Classified) for o in outcomes.values()),
            classify_batches=batch_count(items),
            skipped_batches=skipped,
            llm_calls=budget.calls,
            llm_call_limit=budget.limit,
            news=news,
            drafts=drafts,
        )

    def _collect_filings(
        self, coverage: list[Coverage], trading_day: date, calls: SourceCalls
    ) -> tuple[list[FilingItem], set[str]]:
        """(이번 거래일 카드의 새 공시를 (접수 시각, 접수번호) 순으로, 수집에 실패한 CIK)."""
        since, until = filing_window(trading_day)
        names = {cov.ticker: cov.name for cov in coverage}
        tickers_by_cik: dict[str, list[str]] = {}
        for cov in coverage:
            if cov.cik is not None:
                tickers_by_cik.setdefault(cov.cik, []).append(cov.ticker)
        filings, tickers, failed = {}, {}, set()
        for cik in sorted(tickers_by_cik):  # 같은 접수번호가 여러 CIK에서 오면 CIK 정렬 첫 번째 원본을 남긴다
            try:
                received = calls.call(
                    Source.SEC_FILINGS,
                    cik,
                    lambda: self._filings.filings(cik, since, until),
                    lambda filings: valid_filings(filings, cik),
                )
            except SourceError:
                failed.add(cik)
                continue
            for f in received:
                if since <= f.accepted_at < until:  # 어댑터가 범위를 어겨도 옛 공시가 새 소식이 되지 않게
                    filings.setdefault(f.accession, f)
                    tickers.setdefault(f.accession, set()).update(tickers_by_cik[cik])
        new = self._store.save_filings(trading_day, filings.values())
        items = []
        for accession in new:
            linked = tuple(sorted(tickers[accession]))
            items.append(FilingItem(filings[accession], linked, names[linked[0]]))
        return sorted(items, key=lambda i: (i.filing.accepted_at, i.filing.accession)), failed

    def _collect_indicators(self, trading_day: date, calls: SourceCalls) -> None:
        try:
            releases = calls.call(
                Source.INDICATORS, None, lambda: self._indicators.releases(trading_day, trading_day), valid_releases
            )
        except SourceError:
            return
        self._store.save_indicator_releases(
            trading_day, [r for r in releases if r.released_at.astimezone(ET).date() == trading_day]
        )

    def _event_line(self, ticker: str, trading_day: date, checked_at: datetime, calls: SourceCalls) -> CardLine:
        try:
            events = calls.call(
                Source.EVENTS,
                ticker,
                lambda: self._events.upcoming_events(ticker, trading_day, trading_day + EVENT_WINDOW),
                valid_events,
            )
        except SourceError:  # 다른 예외는 버그라 그대로 올린다
            return delayed_line(EVENT_SCOPE, checked_at)
        return event_line(events, trading_day, checked_at)


def _classification_rows(items: list[FilingItem], outcomes: dict) -> list[Classification]:
    """공시 × 연결 티커마다 한 행. 같은 CIK의 티커는 같은 결과(LLM이 고른 티커는 검증에만 쓴다)."""
    rows = []
    for item in items:
        outcome = outcomes[item.filing.accession]
        for ticker in item.tickers:
            if isinstance(outcome, Classified):
                rows.append(Classification(item.filing.accession, ticker, outcome.kind, outcome.importance, outcome.opinion))
            else:
                rows.append(Classification(item.filing.accession, ticker, unclassified=outcome))
    return rows


def _ticker_news(cov: Coverage, failed_ciks: set[str], items: list[FilingItem], outcomes: dict) -> TickerNews:
    """첫 번째 줄 상태와 후보(스펙 D11 표, 위에서부터)."""
    if cov.cik is None:
        return TickerNews(LineStatus.UNSUPPORTED)
    if cov.cik in failed_ciks:
        return TickerNews(LineStatus.DELAYED)  # 수집 실패를 "없음"으로 두지 않는다
    mine = [i for i in items if cov.ticker in i.tickers]
    if not mine:
        return TickerNews(LineStatus.CHECKED_NONE)
    # 의견글은 후보에도 +N more 개수에도 들어가지 않는다
    classified = [(i, o) for i in mine if isinstance(o := outcomes[i.filing.accession], Classified) and not o.opinion]
    ranked = sorted(classified, key=lambda p: (-p[1].importance, -p[0].filing.accepted_at.timestamp(), p[0].filing.accession))
    candidates = tuple(
        NewsCandidate(i.filing.accession, o.kind, o.importance, i.filing.form is FilingForm.EIGHT_K_A) for i, o in ranked
    )
    if not candidates and any(not isinstance(outcomes[i.filing.accession], Classified) for i in mine):
        return TickerNews(LineStatus.DELAYED)  # 공시는 있는데 분류를 못 했다. "없음"으로 쓰지 않는다
    return TickerNews(LineStatus.CHECKED_FOUND, candidates)
