"""아침 파이프라인. 바깥 인터페이스는 run 하나."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from m30.adapters import Source, SourceError
from m30.adapters.events import EventSource
from m30.adapters.filings import FilingForm, FilingSource
from m30.adapters.holdings import HoldingsSource
from m30.adapters.indicators import IndicatorSource
from m30.adapters.prices import PriceSource
from m30.config import ET
from m30.db.store import CardStore
from m30.llm import LLM, LLMBudget, LLMRequest
from m30.models import (
    CardLine,
    CardStatus,
    Classification,
    Coverage,
    FundHoldings,
    HoldItem,
    LineStatus,
    NewsCandidate,
    StockCard,
    TickerNews,
)
from m30.pipeline.classify import Classified, FilingItem, SkippedBatch, batch_count, classify
from m30.pipeline.collect import (
    SourceCalls,
    SourceFailure,
    filing_window,
    valid_bars,
    valid_events,
    valid_filings,
    valid_holdings,
    valid_releases,
)
from m30.pipeline.compute import bars_usable, change_pct, top_holdings
from m30.pipeline.lines import (
    EVENT_SCOPE,
    EVENT_WINDOW,
    HOLDINGS_SCOPE,
    NEWS_SCOPE,
    PRICE_SCOPE,
    delayed_line,
    event_line,
    holdings_scope,
    leverage_tag,
    news_template_line,
    price_fact_line,
)
from m30.pipeline.newsline import NewsDraft, write_news_drafts
from m30.pipeline.review import NewsReview, review_drafts
from m30.trading_day import is_trading_day, previous_trading_day

CHECKED = (LineStatus.CHECKED_FOUND, LineStatus.CHECKED_NONE)
LOOKBACK = timedelta(weeks=53)  # 52주 이력 + 52주 전 날이 휴장일이어도 거래일이 들어가는 1주
# N-PORT는 분기 말 보고를 60일 뒤 공개한다(#10 D4). 다음 공개 예정은 기준일 약 152일 뒤
HOLDINGS_REFRESH_AFTER = timedelta(days=140)  # 저장분 기준일 + 이 기간 전에는 출처를 부르지 않는다
HOLDINGS_MAX_AGE = timedelta(days=270)  # 쓸 보고의 기준일 + 이 기간을 넘으면 지연(한 분기를 놓친 여유)


@dataclass(frozen=True)
class RunSummary:
    trading_day: date
    access_denied: tuple[Source, ...]  # 401·403이 난 출처. 요약 맨 위에 표시
    rate_limited: tuple[Source, ...]  # 429를 낸 출처(다시 시도로 성공했어도). access_denied 바로 아래 표시
    cards_saved: int
    resumed: tuple[str, ...]  # 죽은 앞 실행이 저장해서 이번에 건너뛴 카드의 티커 (오름차순)
    change_delayed: tuple[str, ...]  # 등락률을 계산 못 해 delayed로 저장한 티커 (오름차순)
    failures: tuple[SourceFailure, ...]  # 재시도 뒤에도 실패한 출처·대상
    filings_collected: int  # 이번 거래일 공시 수(중복 제거 후)
    filings_unclassified: int  # 이번 거래일 공시 중 미분류
    classify_batches: int  # 분류 묶음 수
    skipped_batches: tuple[SkippedBatch, ...]  # 건너뛴 분류 묶음
    llm_calls: int  # 보낸 LLM 요청 수(재시도 포함)
    llm_call_limit: int  # 실행당 LLM 호출 상한
    news: dict[str, TickerNews]  # 생성 대상 티커 → 첫 번째 줄 상태·후보 (#6의 입력)
    drafts: dict[str, NewsDraft]  # 소식 있는 종목 → 첫 번째 줄 초안(검수 전). 카드에는 reviews의 줄만 간다
    reviews: dict[str, NewsReview]  # 소식 있는 종목 → 검수 결과(통과한 줄 또는 대체 줄)
    funds: dict[str, FundHoldings]  # ETF 생성 대상(holdings_ticker 있음) → 상위 편입 종목


class MorningPipeline:
    def __init__(
        self,
        *,
        prices: PriceSource,
        events: EventSource,
        filings: FilingSource,
        indicators: IndicatorSource,
        holdings: HoldingsSource,
        llm: LLM,
        store: CardStore,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # 출처는 기본값 없는 필수 키워드: 빠뜨리면 조용히 도는 대신 바로 실패한다
        self._prices = prices
        self._events = events
        self._filings = filings
        self._indicators = indicators
        self._holdings = holdings
        self._llm = llm
        self._store = store
        self._sleep = sleep

    def run(self, trading_day: date) -> RunSummary:
        if isinstance(trading_day, datetime):
            # datetime은 date의 하위 클래스라 그대로 두면 시각이 거래일로 쓰인다
            raise TypeError("trading_day must be a date, not a datetime")
        if not is_trading_day(trading_day):  # 표 밖의 해면 CalendarError(ValueError). 둘 다 DB 전
            raise ValueError(f"{trading_day} is not a trading day")
        with self._store.run_lock(trading_day):  # 출처 호출·LLM·DB 쓰기는 전부 잠금 뒤
            return self._run(trading_day)

    def _run(self, trading_day: date) -> RunSummary:
        run_id, resume_since = self._store.start_run(trading_day)
        stored = {c.ticker: c for c in self._store.list_cards(trading_day)}  # 이번 실행 전 카드(티커 순)
        # 이어 하기: 끝나지 않은 앞 실행이 저장한 정상 카드는 건너뛴다(축소판은 다시 만든다). 앞 실행이 끝까지 갔으면 전부 다시 만든다
        resumed = tuple(
            t for t, c in stored.items()
            if resume_since is not None and c.status is CardStatus.NORMAL and c.updated_at >= resume_since
        )
        checked_at = datetime.now(ET)  # 이 실행의 모든 줄이 같은 확인 시각을 쓴다
        calls = SourceCalls(self._sleep)
        # 활성 종목 ∪ 기본 종목. 건너뛴 종목은 공시 수집·분류·초안·검수·저장을 전부 하지 않는다
        targets = [c for c in self._store.list_generation_targets(trading_day) if c.ticker not in resumed]
        coverage = {c.ticker: c for c in self._store.list_coverage()}
        funds = self._fund_holdings(targets, coverage, trading_day, calls)
        # 첫 번째 줄이 보는 (티커, CIK) 묶음(D5): 종목 = 자기 자신, ETF = 상위 편입 종목. 편입 종목을 못 읽은 ETF는 묶음이 없다
        groups = {}
        for cov in targets:
            if cov.ticker not in funds:
                groups[cov.ticker] = (frozenset({cov.ticker}), frozenset({cov.cik} - {None}))
            elif funds[cov.ticker].status is LineStatus.CHECKED_FOUND:
                tickers = frozenset(funds[cov.ticker].tickers)
                groups[cov.ticker] = (tickers, frozenset(coverage[t].cik for t in tickers))
        # 공시 수집·분류 대상 = 묶음의 티커 전부(생성 대상이 아닌 편입 종목 포함, 카드는 만들지 않는다). 편입 경로가 있는 ETF 자신의 CIK는 받지 않는다
        collected = [coverage[t] for t in sorted(set().union(*(tickers for tickers, _ in groups.values())))]
        items, failed_ciks = self._collect_filings(collected, trading_day, calls)
        # 카드 루프 전: 카드가 하나라도 저장됐으면 정정 공시 행은 이미 있다(이어 하기가 그 CIK를 다시 받지 않아도)
        self._store.flag_amended_cards(trading_day, [i.filing for i in items if i.filing.form is FilingForm.EIGHT_K_A])
        self._collect_indicators(trading_day, calls)
        budget = LLMBudget(self._llm, len(targets) * 4 + batch_count(items))

        def send(subject: str, request: LLMRequest) -> str:
            """LLM 호출 창구 하나: 분류(묶음 번호)·첫 번째 줄·판정(접수번호)이 같은 상한·재시도·차단을 쓴다."""
            return calls.call(Source.LLM, subject, lambda: budget.complete(request), lambda text: isinstance(text, str))

        outcomes, skipped = classify(items, trading_day, lambda n, request: send(str(n), request))
        # 이번에 공시를 받은 종목의 분류만 바꾼다(건너뛴 종목·수집 실패 CIK의 지난 분류 행은 그대로)
        handled = [c.ticker for c in collected if c.cik not in failed_ciks]
        self._store.replace_classifications(trading_day, handled, _classification_rows(items, outcomes))
        # 초안·검수는 생성 대상만(ETF는 조합한 값). 편입 종목 쪽 1등이 아닌 공시는 LLM을 부르지 않는다
        news = {
            cov.ticker: _ticker_news(*groups[cov.ticker], failed_ciks, items, outcomes) if cov.ticker in groups
            else TickerNews(funds[cov.ticker].status)
            for cov in targets
        }
        by_accession = {i.filing.accession: i for i in items}
        drafts = write_news_drafts(news, by_accession, trading_day, send)
        reviews = review_drafts(drafts, news, by_accession, {c.ticker: c.name for c in collected}, trading_day, send)
        kept = self._store.republished_news(trading_day)  # 사람이 재발행한 첫 번째 줄은 재실행이 덮지 않는다
        saved = 0
        delayed = []
        for cov in targets:
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
            # 첫 번째 줄의 출처는 넷뿐: 사람이 재발행한 줄, 앞 실행이 확인한 줄(CIK 실패), 검수 결과(통과한 줄·대체 줄), 데이터 상태 문구
            # holds: 이 카드의 보류함 행. None = 이번에 첫 번째 줄을 만들지 않았다 → 보류함 행을 건드리지 않는다
            old = stored.get(cov.ticker)
            scope = _news_scope(funds.get(cov.ticker))
            ciks = groups[cov.ticker][1] if cov.ticker in groups else frozenset()
            if cov.ticker in kept:
                text, accession = kept[cov.ticker]
                news_line, holds = CardLine(text, LineStatus.CHECKED_FOUND, checked_at, scope), None
            elif ciks & failed_ciks and old and old.news_line and old.news_line.status in CHECKED:
                # 공시 기간은 고정이고 수집 실패는 새 정보가 아니다: 앞 실행이 확인한 줄(확인 시각 포함)을 그대로 둔다(D6).
                # ETF는 편입 종목 CIK 중 하나라도 실패하면(#10 D5)
                news_line, accession, holds = old.news_line, old.news_line_accession, None
            elif cov.ticker in reviews:
                review = reviews[cov.ticker]
                accession = review.accession
                news_line = CardLine(review.line, LineStatus.CHECKED_FOUND, checked_at, scope)
                # U1 = A: 대체 줄이 카드에 들어간 종목마다 보류함 행 하나
                holds = [] if review.stage is None else [
                    HoldItem(cov.ticker, trading_day, review.accession, review.stage, review.draft_text, review.rules, review.line)
                ]
            else:
                accession, news_line, holds = None, news_template_line(news[cov.ticker], checked_at, scope), []
            self._store.save_card(
                StockCard(
                    ticker=cov.ticker,
                    trading_day=trading_day,
                    status=CardStatus.FALLBACK if news_line is None else CardStatus.NORMAL,  # 축소판은 7:45 마감(미구현)용
                    change_pct=pct,
                    change_status=LineStatus.DELAYED if pct is None else LineStatus.CHECKED_FOUND,
                    news_line=news_line,
                    event_line=self._event_line(cov.ticker, trading_day, checked_at, calls),
                    price_fact_line=price_fact,
                    leverage_tag=leverage_tag(cov.leverage),
                    news_line_accession=accession,
                    previous_trading_day=previous_trading_day(trading_day),
                ),
                holds,  # 카드와 한 트랜잭션: 중간에 죽어도 카드만 남고 보류함 행이 빠지는 일이 없다
            )
            saved += 1
            if pct is None:
                delayed.append(cov.ticker)
        self._store.finish_run(run_id)
        return RunSummary(
            trading_day=trading_day,
            access_denied=calls.access_denied,
            rate_limited=calls.rate_limited,
            cards_saved=saved,
            resumed=resumed,
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
            reviews=reviews,
            funds=funds,
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

    def _fund_holdings(
        self, targets: list[Coverage], coverage: dict[str, Coverage], trading_day: date, calls: SourceCalls
    ) -> dict[str, FundHoldings]:
        """ETF 생성 대상(holdings_ticker 있음) → 상위 편입 종목. 같은 fund를 가리키는 ETF가 여럿이어도(QQQ·TQQQ) fund마다 한 번."""
        by_fund: dict[str, FundHoldings] = {}
        for cov in targets:
            fund = cov.holdings_ticker
            if fund is not None and fund not in by_fund:
                by_fund[fund] = self._read_fund(fund, coverage, trading_day, calls)
        return {cov.ticker: by_fund[cov.holdings_ticker] for cov in targets if cov.holdings_ticker is not None}

    def _read_fund(self, fund: str, coverage: dict[str, Coverage], trading_day: date, calls: SourceCalls) -> FundHoldings:
        """스펙 #10 D4 표, 위에서부터."""
        if fund not in coverage:  # 없는 티커를 가리킴(FK 없음): 출처를 부르지 않는다
            return FundHoldings(LineStatus.UNSUPPORTED)
        report = self._store.latest_holdings(fund)
        if report is None or trading_day >= report.period_end + HOLDINGS_REFRESH_AFTER:
            try:
                fresh = calls.call(
                    Source.HOLDINGS, fund, lambda: self._holdings.latest_report(fund), lambda r: valid_holdings(r, fund)
                )
            except SourceError:
                pass  # 저장분을 쓴다(없으면 지연). 실패는 요약 failed:에 남았다
            else:
                if fresh is None:
                    return FundHoldings(LineStatus.UNSUPPORTED)
                self._store.save_holdings(fresh)
                report = self._store.latest_holdings(fund)  # 저장분과 비교해 period_end가 늦은 쪽
        if report is None or trading_day > report.period_end + HOLDINGS_MAX_AGE:
            return FundHoldings(LineStatus.DELAYED)
        return top_holdings(report, coverage.values())

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


def _news_scope(fund: FundHoldings | None) -> str:
    """첫 번째 줄 출처 범위. 종목(None) = SEC filings, ETF = 확인한 편입 회사 수, 편입 보고를 못 읽은 ETF = 고정 문구(#10 D6)."""
    if fund is None:
        return NEWS_SCOPE
    return holdings_scope(fund.companies) if fund.status is LineStatus.CHECKED_FOUND else HOLDINGS_SCOPE


def _ticker_news(
    tickers: frozenset[str], ciks: frozenset[str], failed_ciks: set[str], items: list[FilingItem], outcomes: dict
) -> TickerNews:
    """첫 번째 줄 상태와 후보(스펙 D11 표, 위에서부터). 종목은 ({티커}, {CIK}), ETF는 (편입 티커들, 그 CIK들)(#10 D5).
    CIK 하나라도 수집 실패면 지연: 일부를 확인 못 했으면 "가장 중요한 것"이라고 말할 수 없다."""
    if not ciks:
        return TickerNews(LineStatus.UNSUPPORTED)
    if ciks & failed_ciks:
        return TickerNews(LineStatus.DELAYED)  # 수집 실패를 "없음"으로 두지 않는다
    mine = [i for i in items if tickers.intersection(i.tickers)]
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
