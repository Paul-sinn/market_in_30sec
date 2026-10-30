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
from m30.adapters.market_news import MarketNewsItem, MarketNewsSource
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
    MarketGlance,
    NewsCandidate,
    StockCard,
    TickerNews,
)
from m30.pipeline.classify import Classified, FilingItem, SkippedBatch, batch_count, classify
from m30.pipeline.collect import (
    FailureReason,
    SourceCalls,
    SourceFailure,
    error_name,
    filing_window,
    valid_bars,
    valid_events,
    valid_filings,
    valid_holdings,
    valid_market_news,
    valid_releases,
)
from m30.pipeline.compute import bars_usable, change_pct, top_holdings
from m30.pipeline.lines import (
    CLOSE_FUNDS,
    EVENT_SCOPE,
    EVENT_WINDOW,
    HOLDINGS_SCOPE,
    INDICATOR_SCOPE,
    NEWS_SCOPE,
    PRICE_SCOPE,
    close_line,
    delayed_line,
    event_line,
    holdings_scope,
    indicator_line,
    leverage_tag,
    news_template_line,
    price_fact_line,
)
from m30.pipeline.glance import GLANCE_CALLS, market_news_line
from m30.pipeline.newsline import NewsDraft, write_news_drafts
from m30.pipeline.notice import morning_notice
from m30.pipeline.review import NewsReview, review_drafts
from m30.trading_day import is_trading_day, previous_trading_day

CHECKED = (LineStatus.CHECKED_FOUND, LineStatus.CHECKED_NONE)
LOOKBACK = timedelta(weeks=53)  # 52주 이력 + 52주 전 날이 휴장일이어도 거래일이 들어가는 1주
# N-PORT는 분기 말 보고를 60일 뒤 공개한다(#10 D4). 다음 공개 예정은 기준일 약 152일 뒤
HOLDINGS_REFRESH_AFTER = timedelta(days=140)  # 저장분 기준일 + 이 기간 전에는 출처를 부르지 않는다
HOLDINGS_MAX_AGE = timedelta(days=270)  # 쓸 보고의 기준일 + 이 기간을 넘으면 지연(한 분기를 놓친 여유)


@dataclass(frozen=True, order=True)
class TickerError:
    ticker: str
    error: str  # error_name(e). 메시지는 남기지 않는다


@dataclass(frozen=True)
class RunSummary:
    trading_day: date
    access_denied: tuple[Source, ...]  # 401·403이 난 출처. 요약 맨 위에 표시
    rate_limited: tuple[Source, ...]  # 429를 낸 출처(다시 시도로 성공했어도). access_denied 바로 아래 표시
    cards_saved: int
    resumed: tuple[str, ...]  # 죽은 앞 실행이 저장해서 이번에 건너뛴 카드의 티커 (오름차순)
    change_delayed: tuple[str, ...]  # 등락률을 계산 못 해 delayed로 저장한 티커 (오름차순)
    failures: tuple[SourceFailure, ...]  # 재시도 뒤에도 실패한 출처·대상
    ticker_errors: tuple[TickerError, ...]  # 카드 만들기·저장의 예외(대상 순서). 그 카드는 전 줄 지연(#17 D5 층 2)
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
    llm_tokens: dict[str, int]  # TOKEN_FIELDS → 이번 실행 합계(LLMBudget.tokens)
    notices: int  # 저장한 아침 알림 문구 수(잠기지 않은 내 종목이 있는 유저 수)
    # "change"|"news"|"event"|"price" → LineStatus 값 4개 → 이번에 저장한 카드 수(0 포함). 첫 번째 줄이 None인 카드는 news에서 빠진다
    line_counts: dict[str, dict[str, int]]
    glance: MarketGlance | None  # 이번에 저장한 시장 한눈에(#11). None = 죽은 앞 실행이 저장해서 건너뜀
    glance_review: str  # 소식 줄 검수: "-"(LLM 안 부름) | "pass" | "pass+retry" | "hold:<단계>" | "hold:<단계>+retry"


class MorningPipeline:
    def __init__(
        self,
        *,
        prices: PriceSource,
        events: EventSource,
        filings: FilingSource,
        indicators: IndicatorSource,
        holdings: HoldingsSource,
        market_news: MarketNewsSource,
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
        self._market_news = market_news
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
        stored_glance = self._store.get_market_glance(trading_day)
        # 시장 한눈에도 카드와 같은 이어 하기 규칙: 끝나지 않은 앞 실행이 저장했으면 소식 수집·LLM·저장을 하지 않는다
        glance_resumed = resume_since is not None and stored_glance is not None and stored_glance.updated_at >= resume_since
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
        indicator = self._collect_indicators(trading_day, checked_at, calls)
        news_status, news_items = (None, ()) if glance_resumed else self._collect_market_news(trading_day, calls)
        # 시장 한눈에 소식 줄은 LLM을 부를 때만 생성 대상 하나 몫(#11 D6): 소식 없음·미지원이면 상한은 그대로
        budget = LLMBudget(self._llm, len(targets) * 4 + batch_count(items) + (GLANCE_CALLS if news_items else 0))

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

        def build(cov: Coverage) -> tuple[StockCard, list[HoldItem] | None]:
            """종목 하나의 카드와 보류함 행(None = 보류함 행을 건드리지 않는다)."""
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
            card = StockCard(
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
            )
            return card, holds

        cards, ticker_errors = [], []
        for cov in targets:
            error = None
            try:
                card, holds = build(cov)
                self._store.save_card(card, holds)  # 카드와 한 트랜잭션: 중간에 죽어도 카드만 남고 보류함 행이 빠지는 일이 없다
            except AssertionError:  # 테스트 대역의 "불리면 안 됨" 신호. 운영 코드는 assert로 흐름을 정하지 않는다
                raise
            except Exception as e:  # 종목 예외(#17 D5 층 2): 그 종목만 전 줄 지연. BaseException(프로세스 종료)은 그대로
                error = error_name(e)
            if error is not None:  # except 밖: 새 예외가 나도 __context__에 원래 예외가 붙지 않는다
                ticker_errors.append(TickerError(cov.ticker, error))
                card = _error_card(cov, trading_day, checked_at)
                self._store.save_card(card, None)  # 이것마저 실패하면 DB 문제: 그대로 올라가 실행이 죽고 이어 하기가 받는다
            cards.append(card)
        # 아침 알림(#12): 이어 하기로 건너뛴 카드까지 그날 카드 전부로. 보류함 재발행은 이 단계를 거치지 않는다(다시 만들지 않음)
        saved = {c.ticker: c for c in self._store.list_cards(trading_day)}
        importance = self._store.news_importance(trading_day)
        notices = {
            uid: morning_notice([saved[t] for t in tickers if t in saved], importance, plan, trading_day)
            for uid, plan, tickers in self._store.list_notice_users()
        }
        self._store.replace_notices(trading_day, notices)
        # 시장 한눈에(#11): 카드·알림 뒤. 여기서 예상 못 한 예외가 나도 카드·알림은 저장돼 있고 다음 실행이 이어 한다
        glance, glance_review = None, "-"
        if not glance_resumed:
            fund_pcts = [saved[t].change_pct if t in saved else None for _, t in CLOSE_FUNDS]  # 같은 날 SPY·QQQ 카드와 같은 숫자
            old = stored_glance and stored_glance.market_news_line
            if news_status is LineStatus.DELAYED and old and old.status in CHECKED:
                # 소식 기간은 고정이고 수집 실패는 새 정보가 아니다: 앞 실행이 확인한 줄(확인 시각 포함)을 그대로 둔다(첫 번째 줄 D6과 같다)
                news_line, hold_draft, hold_rules = old, None, ()
            else:
                news_line, hold_draft, hold_rules, glance_review = market_news_line(
                    news_status, news_items, trading_day, checked_at, send
                )
            close = close_line(*fund_pcts, previous_trading_day(trading_day), checked_at)
            glance = MarketGlance(trading_day, close, indicator, news_line, hold_draft, hold_rules)
            self._store.upsert_market_glance(glance)
        summary = RunSummary(
            trading_day=trading_day,
            access_denied=calls.access_denied,
            rate_limited=calls.rate_limited,
            cards_saved=len(cards),
            resumed=resumed,
            change_delayed=tuple(c.ticker for c in cards if c.change_pct is None),
            failures=calls.failures,
            ticker_errors=tuple(ticker_errors),
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
            llm_tokens=dict(budget.tokens),
            notices=len(notices),
            line_counts=_line_counts(cards),
            glance=glance,
            glance_review=glance_review,
        )
        self._store.finish_run(run_id, run_failed(summary), run_record(summary))
        return summary

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

    def _collect_indicators(self, trading_day: date, checked_at: datetime, calls: SourceCalls) -> CardLine:
        """거래일 발표를 저장하고 시장 한눈에 지표 일정 줄을 돌려준다. 실패는 그 줄만 지연(요약 failed:에 남는다)."""
        try:
            releases = calls.call(
                Source.INDICATORS, None, lambda: self._indicators.releases(trading_day, trading_day), valid_releases
            )
        except SourceError:
            return delayed_line(INDICATOR_SCOPE, checked_at)
        if releases is not None:
            releases = [r for r in releases if r.released_at.astimezone(ET).date() == trading_day]
            self._store.save_indicator_releases(trading_day, releases)
        return indicator_line(releases, checked_at)

    def _collect_market_news(self, trading_day: date, calls: SourceCalls) -> tuple[LineStatus, tuple[MarketNewsItem, ...]]:
        """(UNSUPPORTED, ()) / (DELAYED, ()) / (CHECKED_NONE, ()) / (CHECKED_FOUND, 기간 안 항목). 기간은 공시와 같다.
        어댑터가 범위를 어겨도 다시 거르고, 기간 안 항목만 저장한다. 실패는 요약 failed:에 남는다."""
        since, until = filing_window(trading_day)
        try:
            items = calls.call(Source.MARKET_NEWS, None, lambda: self._market_news.items(since, until), valid_market_news)
        except SourceError:
            return LineStatus.DELAYED, ()
        if items is None:
            return LineStatus.UNSUPPORTED, ()
        kept = tuple(i for i in items if since <= i.published_at < until)
        self._store.save_market_news(trading_day, kept)
        return (LineStatus.CHECKED_FOUND if kept else LineStatus.CHECKED_NONE), kept

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


def run_failed(summary: RunSummary) -> bool:
    """워크플로를 실패로 끝낼 실행: 재시도 뒤에도 실패한 호출(401·403 포함)·종목 예외가 있거나 카드 0장(이어 하기로 건너뛴 카드도 0장).
    미연결 출처는 실패를 남기지 않는다. 429 뒤 성공·건너뛴 분류 묶음·보류함은 실패가 아니다."""
    return bool(summary.failures or summary.ticker_errors) or summary.cards_saved + len(summary.resumed) == 0


def run_record(summary: RunSummary) -> dict:
    """pipeline_run.summary(#17 D1). 코드·건수·티커만: 카드 문장·가격·예외 메시지를 넣지 않는다. 키를 바꾸면 조회도 바꾼다."""
    reviews = summary.reviews.values()
    return {
        "counts": {
            "cards_saved": summary.cards_saved,
            "resumed": len(summary.resumed),
            "change_delayed": len(summary.change_delayed),
            "funds": len(summary.funds),
            "filings": summary.filings_collected,
            "unclassified": summary.filings_unclassified,
            "classify_batches": summary.classify_batches,
            "skipped_batches": len(summary.skipped_batches),
            "drafts": len(summary.drafts),
            "draft_problems": sum(d.problem is not None for d in summary.drafts.values()),
            "review_pass_first": sum(r.stage is None and not r.retried for r in reviews),
            "review_pass_retry": sum(r.stage is None and r.retried for r in reviews),
            "review_replaced": sum(r.stage is not None for r in reviews),
        },
        "lines": summary.line_counts,
        "failures": [
            {"stage": f.source, "subject": f.subject, "reason": f.reason, "error": f.error} for f in summary.failures
        ] + [
            {"stage": "card", "subject": t.ticker, "reason": FailureReason.UNEXPECTED, "error": t.error} for t in summary.ticker_errors
        ],
        "access_denied": list(summary.access_denied),
        "rate_limited": list(summary.rate_limited),
        "llm": {"calls": summary.llm_calls, "limit": summary.llm_call_limit, **summary.llm_tokens},
        "glance": "resumed" if (g := summary.glance) is None else {
            "close": g.close_line.status, "indicator": g.indicator_line.status, "market_news": g.market_news_line.status,
            "review": summary.glance_review,
        },
    }


def _error_card(cov: Coverage, trading_day: date, checked_at: datetime) -> StockCard:
    """종목 예외(층 2) 대체 카드: 등락률과 세 줄 모두 지연. 첫 번째 줄 범위는 ETF(편입 종목을 읽음)면 편입 고정 문구."""
    return StockCard(
        ticker=cov.ticker,
        trading_day=trading_day,
        status=CardStatus.NORMAL,
        change_pct=None,
        change_status=LineStatus.DELAYED,
        news_line=delayed_line(NEWS_SCOPE if cov.holdings_ticker is None else HOLDINGS_SCOPE, checked_at),
        event_line=delayed_line(EVENT_SCOPE, checked_at),
        price_fact_line=delayed_line(PRICE_SCOPE, checked_at),
        leverage_tag=leverage_tag(cov.leverage),
        news_line_accession=None,
        previous_trading_day=previous_trading_day(trading_day),
    )


def _line_counts(cards: list[StockCard]) -> dict[str, dict[str, int]]:
    """줄 이름 → 상태 값 4개 → 카드 수(0 포함). 첫 번째 줄이 None인 카드(축소판)는 news에서 빠진다."""
    counts = {name: dict.fromkeys(map(str, LineStatus), 0) for name in ("change", "news", "event", "price")}
    for card in cards:
        counts["change"][card.change_status] += 1
        for name, line in (("news", card.news_line), ("event", card.event_line), ("price", card.price_fact_line)):
            if line is not None:
                counts[name][line.status] += 1
    return counts


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
