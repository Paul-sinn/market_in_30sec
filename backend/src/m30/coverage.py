"""커버 범위(HANDOFF 3-1, #58) = SPY 최신 N-PORT 보유 보통주 회사의 티커 + ETF 설정 목록(etfs.toml). 추가만.
갱신은 pipeline.production.refresh_coverage가 매 아침 실행 앞에서 한다. 여기는 순수 함수만."""

import re
import tomllib
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from m30.adapters.holdings import Holding, HoldingsReport
from m30.models import Coverage
from m30.pipeline.lines import company_short_name

SP500_FUND = "SPY"  # 커버 범위 주식의 출처 ETF. etfs.toml에 반드시 있어야 한다
ETF_LIST = files("m30").joinpath("etfs.toml")
# 2026Q4 기본 종목(#8 D7, GLOSSARY DefaultTicker). SPY·QQQ 포함(테스트로 고정). 재선정(HANDOFF 3-2)은 #58 밖
DEFAULT_TICKERS: tuple[str, ...] = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "KO", "PFE",
                                    "SPY", "QQQ", "TQQQ", "SCHD")

TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")  # DB coverage.ticker check와 같다. fullmatch로 쓴다
ETF_KEYS = frozenset({"ticker", "name", "holdings", "leverage"})

_CLASS_TAIL = re.compile(r"\s+Class [A-Z]$", re.I)  # 'Alphabet Inc Class C', 'CLASS C'
_SLASH_TAIL = re.compile(r"/\w+$")  # 'Coca-Cola Co/The'


def coverage_name(nport_name: str) -> str:
    """N-PORT 발행 회사 이름 → 카드 이름. 끝 ' Class X'(대소문자 무시) → 끝 '/글자' → company_short_name. 비면 원래 이름(strip)."""
    name = nport_name.strip()
    return company_short_name(_SLASH_TAIL.sub("", _CLASS_TAIL.sub("", name)).strip()) or name


def load_etfs(source: Traversable | Path = ETF_LIST) -> tuple[Coverage, ...]:
    """etfs.toml → Coverage(ticker, name, leverage, cik=None, holdings_ticker=holdings), 파일 순서.
    규칙(#58 D5)을 어기면 ValueError("etf list: <순번> <티커|-> <무엇>"). TOML 문법 오류도 ValueError(tomllib.TOMLDecodeError)."""
    top = tomllib.loads(source.read_text(encoding="utf-8"))
    if top.keys() != {"etf"} or not isinstance(top["etf"], list) or not all(isinstance(r, dict) for r in top["etf"]):
        raise ValueError("etf list: top-level keys")
    etfs: list[Coverage] = []
    for n, row in enumerate(top["etf"], 1):
        ticker = row.get("ticker")
        where = f"etf list: {n} {ticker if isinstance(ticker, str) and TICKER.fullmatch(ticker) else '-'}"
        if not row.keys() <= ETF_KEYS:
            raise ValueError(f"{where} unknown key")
        if not (isinstance(ticker, str) and TICKER.fullmatch(ticker)):
            raise ValueError(f"{where} ticker")
        if any(e.ticker == ticker for e in etfs):
            raise ValueError(f"{where} duplicate ticker")
        if not (isinstance(name := row.get("name"), str) and name.strip() and name.isprintable()):
            raise ValueError(f"{where} name")
        if not (isinstance(holdings := row.get("holdings"), str) and TICKER.fullmatch(holdings)):
            raise ValueError(f"{where} holdings")
        etfs.append(Coverage(ticker, name, _leverage(row.get("leverage"), where), None, holdings))
    tickers = {e.ticker for e in etfs}
    if missing := next((e for e in etfs if e.holdings_ticker not in tickers), None):
        raise ValueError(f"etf list: {etfs.index(missing) + 1} {missing.ticker} holdings not in list")
    if SP500_FUND not in tickers:
        raise ValueError(f"etf list: {SP500_FUND} missing")
    return tuple(etfs)


def _leverage(value: object, where: str) -> Decimal | None:
    """없으면 None. 문자열 → Decimal, 유한, > 1 또는 < 0, 소수 둘째 자리 이하, 절댓값 100 미만(DB numeric(4,2) + check)."""
    if value is None:
        return None
    try:
        leverage = Decimal(value) if isinstance(value, str) else None  # 숫자는 받지 않는다(TOML float 3.10 → 3.1 같은 바뀜)
    except InvalidOperation:
        leverage = None
    if not (leverage is not None and leverage.is_finite() and (leverage > 1 or leverage < 0) and abs(leverage) < 100
            and leverage.as_tuple().exponent >= -2):
        raise ValueError(f"{where} leverage")
    return leverage


def sp500_stocks(report: HoldingsReport, ciks: Mapping[str, str]) -> tuple[list[Coverage], int]:
    """(주식 행 티커순, 못 찾은 회사 수). report = SPY 보고, ciks = ticker_ciks 결과(dict 순서 = SEC 목록 순서, 주 티커가 먼저).
    보통주(EC) 롱만 회사(cik, 없으면 이름)로 묶는다(top_holdings와 같다). 회사마다 k = 그 회사 EC 롱 행 수(주식 종류 수),
    티커 = ciks에서 그 CIK를 가리키고 TICKER에 맞는 것 앞 k개(SEC 목록의 권리·기타 티커 CELG-RI·GOOGN은 뒤에 있다),
    이름 = 비중 가장 큰 행(같으면 이름 순 앞)의 coverage_name. cik 없음·티커 0개 = 못 찾음. leverage·holdings_ticker는 None."""
    companies: dict[tuple[str, str], list[Holding]] = {}
    for h in report.holdings:
        if h.asset_category == "EC" and h.pct > 0:
            companies.setdefault(("cik", h.cik) if h.cik is not None else ("name", h.name), []).append(h)
    tickers_by_cik: dict[str, list[str]] = {}
    for ticker, cik in ciks.items():
        if TICKER.fullmatch(ticker):  # 외부 데이터: 하나라도 DB 형식에 안 맞으면 insert 전체가 실패한다
            tickers_by_cik.setdefault(cik, []).append(ticker)
    rows: list[Coverage] = []
    unmatched = 0
    for (kind, value), holdings in companies.items():
        tickers = tickers_by_cik.get(value, [])[:len(holdings)] if kind == "cik" else []
        if not tickers:
            unmatched += 1
            continue
        name = coverage_name(min(holdings, key=lambda h: (-h.pct, h.name)).name)
        rows += [Coverage(ticker, name, cik=value) for ticker in tickers]
    return sorted(rows, key=lambda c: c.ticker), unmatched
