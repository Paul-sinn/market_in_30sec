"""커버 범위(#58) = SPY 최신 N-PORT 보유 보통주 회사의 티커 + ETF 설정 목록(etfs.toml). 추가만.
입구 1: run_production(녹화 SEC 응답 + 기록용 get, 로컬 DB) / refresh_coverage. 순수 규칙(이름 다듬기·ETF 목록 검증)은 직접 부른다."""

import dataclasses
import json
from datetime import date
from decimal import Decimal

import pytest

from m30.adapters import Source, TransientSourceError
from m30.adapters.edgar import SUBMISSIONS_URL, TICKERS_URL
from m30.adapters.holdings import Holding
from m30.adapters.nport import EdgarHoldingsSource
from m30.coverage import DEFAULT_TICKERS, SP500_FUND, coverage_name, load_etfs
from m30.models import Coverage
from m30.pipeline import collect, production
from m30.pipeline.collect import FailureReason, SourceFailure
from m30.pipeline.production import CoverageRefresh, refresh_coverage, run_failed, run_production
from production_probe import COMPANY_CIKS, REMOTE_START, NoCallLLM, empty_submissions, nport_responses, quiet_gov
from test_edgar import RecordedGet
from test_nport import SPY_CIK, recorded, sec
from test_schema import as_service_role

FRI = date(2026, 10, 16)
# 녹화 SPY 보고(test_nport, 기준일 2026-06-30): 보통주 12행 = 회사 11개(Alphabet 두 행) + 파생 1행(CONTRA HOLOGIC, DE).
# 발행 회사 CIK는 company_tickers_holdings.json(그 11개 회사 title이 다 있다)으로 찾은 것
SPY_REPORT = EdgarHoldingsSource(sec()).latest_report("SPY")
HOLDINGS_LISTING = json.loads(recorded("company_tickers_holdings.json"))
# 손으로 정한 기댓값: (티커, 이름, CIK). 이름 = 그 회사 행 중 비중이 가장 큰 N-PORT 이름에서 법인 꼬리를 뗀 것
SP500_STOCKS = [
    ("AAPL", "Apple", "0000320193"), ("AMD", "Advanced Micro Devices", "0000002488"), ("AMZN", "Amazon.com", "0001018724"),
    ("AVGO", "Broadcom", "0001730168"), ("GOOG", "Alphabet", "0001652044"), ("GOOGL", "Alphabet", "0001652044"),
    ("LLY", "Eli Lilly", "0000059478"), ("META", "Meta Platforms", "0001326801"), ("MSFT", "Microsoft", "0000789019"),
    ("MU", "Micron Technology", "0000723125"), ("NVDA", "NVIDIA", "0001045810"), ("TSLA", "Tesla", "0001318605"),
]


def with_rows(*rows, listing=HOLDINGS_LISTING):
    """listing 앞에 (cik_str, ticker, title) 행을 끼운 티커 목록. dict 순서 = SEC 목록 순서."""
    added = [{"cik_str": cik, "ticker": ticker, "title": title} for cik, ticker, title in rows]
    return {str(n): row for n, row in enumerate([*added, *listing.values()])}


def sec_day(listing=HOLDINGS_LISTING, **changes):
    """공시가 없는 날의 SEC 응답: 티커 목록(listing) + 그 목록·#58 전 실험 회사의 빈 submissions + ETF 편입 보고(녹화)."""
    ciks = {f"{row['cik_str']:010d}" for row in listing.values()} | set(COMPANY_CIKS.values())
    return RecordedGet({TICKERS_URL: json.dumps(listing).encode()}
                       | {SUBMISSIONS_URL.format(cik=cik): empty_submissions(cik) for cik in ciks} | nport_responses() | changes)


MON = date(2026, 10, 19)  # FRI 다음 거래일


def later_report(*added, without=()):
    """기준일 2026-09-30의 새 SPY 보고 = 녹화 보고 + added 행 - 이름이 without인 행."""
    holdings = tuple(h for h in SPY_REPORT.holdings if h.name not in without) + added
    return dataclasses.replace(SPY_REPORT, accession="0001410368-26-120001", period_end=date(2026, 9, 30), holdings=holdings)


def run(store, day=FRI, get=None):
    return run_production(store, day, get=get or sec_day(), gov_get=RecordedGet(quiet_gov()), llm=NoCallLLM(), prices=None)


def stocks(store):
    return [(c.ticker, c.name, c.cik) for c in store.list_coverage() if c.holdings_ticker is None]


def save_report(store, report=SPY_REPORT):
    """ETF 행(보고는 coverage를 가리킨다) + 보고. 기준일 + 140일 전이면 파이프라인이 SPY 보고를 다시 받지 않는다."""
    store.upsert_coverage(load_etfs())
    store.save_holdings(report)


@pytest.mark.parametrize(
    "nport_name, name",
    [
        ("Coca-Cola Co/The", "Coca-Cola"),
        ("Alphabet Inc Class C", "Alphabet"),
        ("Merck & Co Inc", "Merck"),
        ("Eli Lilly & Co", "Eli Lilly"),
        ("Charles Schwab Corp/The", "Charles Schwab"),
        ("Amazon.com Inc", "Amazon.com"),
        ("Estee Lauder Cos Inc/The", "Estee Lauder"),
        ("TJX Cos Inc/The", "TJX"),
        ("Cooper Cos Inc/The", "Cooper"),
        ("Interpublic Group of Cos Inc/The", "Interpublic Group of Cos"),  # 'of' 뒤는 법인 꼬리가 아니라 이름이다
        ("News Corp Class A", "News Corp"),  # 'News'만 남으면 일반 명사(기사 소식)로 읽힌다. NWSA·NWS 둘 다
        ("News Corp Class B", "News Corp"),
        ("Fox Corp Class A", "Fox"),
        ("Alphabet Inc CLASS A", "Alphabet"),  # 대문자로 와도
    ],
)
def test_N_PORT_이름은_주식_종류·슬래시_꼬리·법인_꼬리를_떼고_카드_이름이_된다(nport_name, name):
    assert coverage_name(nport_name) == name


def test_ETF_설정_목록은_SPY·QQQ와_기본_종목_ETF를_포함하고_편입_출처가_목록_안을_가리킨다():
    etfs = {e.ticker: e for e in load_etfs()}

    # 기본 종목 ETF 4개 = #58 전 실험 커버 범위의 ETF 행과 같은 값(이름·배율·편입 출처). ETF는 CIK 없음(U3 = A).
    # #59가 목록을 늘려도 그대로다. SPY = 커버 범위 주식의 출처, 지수 대신 SPY·QQQ
    assert [etfs.get(t) for t in ("SPY", "QQQ", "TQQQ", "SCHD")] == [
        Coverage("SPY", "SPDR S&P 500 ETF", holdings_ticker="SPY"),
        Coverage("QQQ", "Invesco QQQ", holdings_ticker="QQQ"),
        Coverage("TQQQ", "ProShares UltraPro QQQ", leverage=Decimal("3"), holdings_ticker="QQQ"),
        Coverage("SCHD", "Schwab U.S. Dividend Equity ETF", holdings_ticker="SCHD"),
    ]
    assert SP500_FUND == "SPY" and {"SPY", "QQQ", "TQQQ", "SCHD"} <= set(DEFAULT_TICKERS)
    assert {e.holdings_ticker for e in etfs.values()} <= etfs.keys()


ETF_TOML = """
[[etf]]
ticker = "SPY"
name = "SPDR S&P 500 ETF"
holdings = "SPY"

[[etf]]
ticker = "QQQ"
name = "Invesco QQQ"
holdings = "QQQ"

[[etf]]
ticker = "TQQQ"
name = "ProShares UltraPro QQQ"
holdings = "QQQ"
leverage = "3"
"""


@pytest.mark.parametrize(
    "old, new, message",
    [
        ('leverage = "3"', 'leverge = "3"', "etf list: 3 TQQQ unknown key"),  # 오타는 조용히 일반 ETF가 되지 않는다
        ('ticker = "QQQ"', 'ticker = "qqq"', "etf list: 2 - ticker"),
        ('ticker = "QQQ"', 'ticker = "QQQ QQQ"', "etf list: 2 - ticker"),
        ('ticker = "TQQQ"', 'ticker = "QQQ"', "etf list: 3 QQQ duplicate ticker"),
        ('holdings = "QQQ"\nleverage', 'holdings = "NDX"\nleverage', "etf list: 3 TQQQ holdings not in list"),
        ('holdings = "QQQ"\nleverage', 'holdings = "qqq"\nleverage', "etf list: 3 TQQQ holdings"),
        ('holdings = "SPY"', "", "etf list: 1 SPY holdings"),
        ('name = "Invesco QQQ"', 'name = ""', "etf list: 2 QQQ name"),
        ('name = "Invesco QQQ"', 'name = "Invesco\\nQQQ"', "etf list: 2 QQQ name"),
        ('leverage = "3"', 'leverage = "1"', "etf list: 3 TQQQ leverage"),  # 1배는 레버리지가 아니다(DB check와 같다)
        ('leverage = "3"', 'leverage = "0.5"', "etf list: 3 TQQQ leverage"),
        ('leverage = "3"', 'leverage = "abc"', "etf list: 3 TQQQ leverage"),
        ('leverage = "3"', 'leverage = "1.234"', "etf list: 3 TQQQ leverage"),  # numeric(4,2)
        ('leverage = "3"', 'leverage = "100"', "etf list: 3 TQQQ leverage"),
        ('leverage = "3"', 'leverage = "NaN"', "etf list: 3 TQQQ leverage"),
        ('leverage = "3"', 'leverage = "inf"', "etf list: 3 TQQQ leverage"),
        ('leverage = "3"', 'leverage = "-inf"', "etf list: 3 TQQQ leverage"),
        ('leverage = "3"', "leverage = 3", "etf list: 3 TQQQ leverage"),  # 숫자는 받지 않는다(3.10 → 3.1 같은 바뀜 없이)
        ('ticker = "SPY"\nname = "SPDR S&P 500 ETF"\nholdings = "SPY"', 'ticker = "VOO"\nname = "Vanguard S&P 500 ETF"\nholdings = "VOO"',
         "etf list: SPY missing"),  # 커버 범위 주식의 출처
        ("[[etf]]\nticker = \"SPY\"", "[[etff]]\nticker = \"SPY\"", "etf list: top-level keys"),
        (ETF_TOML, "etf = [1]", "etf list: top-level keys"),  # 표가 아닌 행
    ],
)
def test_ETF_설정_목록이_규칙을_어기면_ValueError다(tmp_path, old, new, message):
    assert old in ETF_TOML
    path = tmp_path / "etfs.toml"
    path.write_text(ETF_TOML.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ValueError) as raised:
        load_etfs(path)
    assert str(raised.value) == message


def test_ETF_설정_목록이_TOML_문법에_맞지_않으면_ValueError다(tmp_path):
    path = tmp_path / "etfs.toml"
    path.write_text(ETF_TOML.replace('name = "Invesco QQQ"', 'name = "Invesco QQQ'), encoding="utf-8")

    with pytest.raises(ValueError):
        load_etfs(path)


def test_ETF_설정_목록의_배율은_부호로_방향을_나타내고_소수_둘째_자리까지_받는다(tmp_path):
    path = tmp_path / "etfs.toml"
    path.write_text(ETF_TOML + '\n[[etf]]\nticker = "SQQQ"\nname = "ProShares UltraPro Short QQQ"\nholdings = "QQQ"\nleverage = "-3"\n'
                    + '\n[[etf]]\nticker = "SSO"\nname = "ProShares Ultra S&P500"\nholdings = "SPY"\nleverage = "1.50"\n',
                    encoding="utf-8")

    assert [(e.ticker, e.leverage, e.cik) for e in load_etfs(path)] == [
        ("SPY", None, None), ("QQQ", None, None), ("TQQQ", Decimal("3"), None), ("SQQQ", Decimal("-3"), None),
        ("SSO", Decimal("1.50"), None)]


def test_커버_범위_주식은_저장된_SPY_최신_N_PORT의_보통주_회사를_SEC_티커로_바꾼_것이다(store):
    save_report(store)

    summary, refresh = run(store)

    assert stocks(store) == SP500_STOCKS  # 파생(CONTRA HOLOGIC)은 없다
    assert refresh == CoverageRefresh(None, etfs=4, stocks=12, added=12, unmatched=0, sp500_period_end=date(2026, 6, 30))
    assert {c.ticker for c in store.list_coverage() if c.holdings_ticker} == {"SPY", "QQQ", "TQQQ", "SCHD"}
    assert summary.failures == ()


ALPHABET_C = Decimal("2.590423554935")  # 녹화 SPY 보고의 Alphabet 두 행 중 비중이 작은 행(이름은 둘 다 Alphabet Inc)


@pytest.mark.parametrize(
    "holdings, alphabet",
    [(SPY_REPORT.holdings, ["GOOG", "GOOGL"]),
     (tuple(h for h in SPY_REPORT.holdings if h.pct != ALPHABET_C), ["GOOGL"])],  # 한 종류만 가지면 SEC 목록의 앞 티커만
    ids=["두_종류", "한_종류"],
)
def test_한_회사의_여러_티커는_SPY가_가진_종류_수만큼_SEC_목록_순서대로_쓰고_권리·기타_티커는_넣지_않는다(store, holdings, alphabet):
    # 녹화 목록 순서: GOOGL … GOOG → CELG-RI(BMY 권리) → GOOGN → GOOGM. 맨 앞에 DB 형식이 아닌 Alphabet 티커를 끼운다(외부 데이터)
    save_report(store, dataclasses.replace(SPY_REPORT, holdings=holdings))

    run(store, get=sec_day(with_rows((1652044, "GOOG^X", "Alphabet Inc."))))

    assert [(t, name) for t, name, cik in stocks(store) if cik == "0001652044"] == [(t, "Alphabet") for t in alphabet]
    assert not {"GOOGN", "GOOGM", "CELG-RI", "GOOG^X"} & {c.ticker for c in store.list_coverage()}


def test_더_늦은_기준일의_SPY_보고가_저장되면_다음_실행에서_새_회사가_추가된다(store):
    save_report(store)
    run(store)
    store.save_holdings(later_report(Holding("Bristol-Myers Squibb Co", "0000014272", Decimal("0.4"), "EC")))

    _, refresh = run(store, MON)

    # 녹화 목록에서 BMY CIK의 티커는 BMY → CELG-RI(권리) 순. SPY는 한 종류만 가진다
    assert stocks(store) == sorted(SP500_STOCKS + [("BMY", "Bristol-Myers Squibb", "0000014272")])
    assert refresh == CoverageRefresh(None, etfs=4, stocks=13, added=1, unmatched=0, sp500_period_end=date(2026, 9, 30))


SMALL_LISTING = json.loads(recorded("company_tickers.json"))  # 13행: AMD·Broadcom·Lilly·Micron이 없다
# 13행 목록으로 이름을 맞춘 보고(파이프라인이 이 목록으로 받았다면 저장했을 것): 그 네 회사는 cik 없음
SMALL_REPORT = EdgarHoldingsSource(sec(**{TICKERS_URL: recorded("company_tickers.json")})).latest_report("SPY")


@pytest.mark.parametrize("report", [SMALL_REPORT, SPY_REPORT], ids=["보고에_CIK_없음", "CIK의_티커가_목록에_없음"])
def test_보유_종목을_SEC_회사로_못_찾으면_넣지_않고_수만_센다(store, report):
    assert sum(h.cik is None for h in SMALL_REPORT.holdings if h.asset_category == "EC") == 4
    save_report(store, report)

    _, refresh = run(store, get=sec_day(SMALL_LISTING))

    assert [t for t, _, _ in stocks(store)] == ["AAPL", "AMZN", "GOOG", "GOOGL", "META", "MSFT", "NVDA", "TSLA"]
    assert (refresh.stocks, refresh.added, refresh.unmatched) == (8, 8, 4)


SQQQ = '\n[[etf]]\nticker = "SQQQ"\nname = "ProShares UltraPro Short QQQ"\nholdings = "QQQ"\nleverage = "-3"\n'


def test_인버스_ETF는_설정의_음수_배율로_기존_인버스_태그를_단다(store, tmp_path):
    path = tmp_path / "etfs.toml"
    path.write_text(ETF_TOML + SQQQ, encoding="utf-8")
    assert refresh_coverage(store, sec_day(), path) == CoverageRefresh(None, etfs=4, stocks=0, added=0, unmatched=0)
    store.add_default_tickers(FRI, ["SQQQ"])

    run(store)  # 원래 목록(SQQQ 없음)으로 갱신해도 SQQQ 행은 남는다(추가만)

    cards = {c.ticker: c for c in store.list_cards(FRI)}
    assert (cards["SQQQ"].leverage_tag, cards["TQQQ"].leverage_tag) == ("\u22123x inverse · resets daily", "3x · resets daily")
    assert cards["SQQQ"].news_line.source_scope == cards["QQQ"].news_line.source_scope  # 편입 종목은 같은 지수의 일반 ETF
    assert next(c for c in store.list_coverage() if c.ticker == "SQQQ") == Coverage(
        "SQQQ", "ProShares UltraPro Short QQQ", leverage=Decimal("-3"), holdings_ticker="QQQ")


def my_stock_rows(admin):
    return (admin.execute("select user_id, ticker, locked from public.my_stock order by ticker").fetchall(),
            admin.execute("select user_id, change::text, ticker, local_date from public.my_stock_history order by id").fetchall())


def test_새_SPY_보고에서_빠진_회사도_커버_범위·카드·내_종목에서_지우지_않는다(store, admin, make_user):
    save_report(store)
    run(store)  # AMD(기본 종목 아님)가 커버 범위에 들어온다
    uid = make_user()
    as_service_role(admin, "insert into public.my_stock (user_id, ticker) values (%s, 'AMD')", (uid,))
    run(store)  # 활성 종목이 되어 FRI 카드가 생긴다
    before = my_stock_rows(admin)
    [fri_card] = [c for c in store.list_cards(FRI) if c.ticker == "AMD"]
    store.save_holdings(later_report(without=("Advanced Micro Devices Inc",)))

    _, refresh = run(store, MON)

    assert stocks(store) == SP500_STOCKS  # AMD 행·이름·CIK 그대로
    assert (refresh.stocks, refresh.added, refresh.sp500_period_end) == (11, 0, date(2026, 9, 30))
    assert my_stock_rows(admin) == before
    assert [c for c in store.list_cards(FRI) if c.ticker == "AMD"] == [fri_card]
    assert "AMD" in {c.ticker for c in store.list_cards(MON)}  # 내 종목이라 카드도 계속 만든다


def test_이미_있는_주식_행은_이름·CIK를_덮지_않고_ETF_행은_설정_값으로_덮는다(store, admin):
    store.upsert_coverage(REMOTE_START)  # 원격의 #58 전 15행: 손으로 고른 이름 Amazon·Meta
    admin.execute("update public.coverage set name = 'Old SPY name', holdings_ticker = null where ticker = 'SPY'")
    admin.execute("update public.coverage set cik = '0000000001' where ticker = 'TSLA'")  # 티커 목록·보고의 CIK와 다르다
    store.save_holdings(SPY_REPORT)

    _, refresh = run(store, get=sec_day(**{SUBMISSIONS_URL.format(cik="0000000001"): empty_submissions("0000000001")}))

    rows = {c.ticker: c for c in store.list_coverage()}
    assert (rows["AMZN"].name, rows["META"].name, rows["TSLA"].cik) == ("Amazon", "Meta", "0000000001")
    assert rows["SPY"] == Coverage("SPY", "SPDR S&P 500 ETF", holdings_ticker="SPY")  # 설정 파일이 ETF 행의 기준
    assert (rows["AMD"].name, rows["JPM"].name) == ("Advanced Micro Devices", "JPMorgan Chase")  # 새 행 추가, 보고 밖 행 유지
    assert (refresh.stocks, refresh.added) == (12, 5)  # AMD·AVGO·GOOG·LLY·MU


def test_같은_입력으로_두_번_실행하면_커버_범위가_같다(store):
    save_report(store)
    run(store)
    coverage = store.list_coverage()

    _, refresh = run(store)

    assert store.list_coverage() == coverage
    assert (refresh.stocks, refresh.added) == (12, 0)


def test_커버_범위가_넓어져도_생성_대상은_활성_종목과_기본_종목뿐이다(store, admin, make_user):
    save_report(store)

    run(store)

    covered = {c.ticker for c in store.list_coverage()}
    assert len(covered) == 16
    # 유저 0명: 카드 = 기본 종목 ∩ 커버 범위(JPM·XOM·KO·PFE는 녹화 SPY 보고에 없다). 커버 범위만 넓어진 AMD·AVGO·GOOG 등은 카드 없음
    assert sorted(c.ticker for c in store.list_cards(FRI)) == sorted(set(DEFAULT_TICKERS) & covered) == [
        "AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "QQQ", "SCHD", "SPY", "TQQQ", "TSLA"]
    as_service_role(admin, "insert into public.my_stock (user_id, ticker) values (%s, 'AMD')", (make_user(),))

    run(store, MON)

    assert "AMD" in {c.ticker for c in store.list_cards(MON)} and "AVGO" not in {c.ticker for c in store.list_cards(MON)}


@pytest.mark.parametrize("text", [ETF_TOML.replace('leverage = "3"', 'leverage = "1"'), ETF_TOML + "[[etf]\n", None],
                         ids=["규칙_위반", "TOML_문법", "파일_없음"])
def test_ETF_설정_목록이_잘못되면_커버_범위를_건드리지_않고_실행은_계속된다(store, admin, tmp_path, monkeypatch, text):
    path = tmp_path / "etfs.toml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    store.upsert_coverage(REMOTE_START)
    admin.execute("update public.coverage set name = 'Old SPY name' where ticker = 'SPY'")
    store.save_holdings(SPY_REPORT)
    coverage, get = store.list_coverage(), sec_day()

    assert refresh_coverage(store, get, path) == CoverageRefresh("etf_list_invalid")
    assert get.urls == []  # SEC 티커 목록도 받지 않는다
    assert store.list_coverage() == coverage

    monkeypatch.setattr(production, "ETF_LIST", path)
    summary, refresh = run(store)

    assert refresh == CoverageRefresh("etf_list_invalid")
    assert store.list_coverage() == coverage  # Old SPY name 그대로, AMD 등도 추가하지 않음
    assert summary.cards_saved == 15 and run_failed(summary) is False  # 지난 행으로 카드를 만든다


def test_저장된_SPY_보고가_없으면_ETF_행만_갱신하고_주식_행은_그대로다(store, admin):
    store.upsert_coverage(REMOTE_START)
    admin.execute("update public.coverage set name = 'Old SPY name' where ticker = 'SPY'")

    _, refresh = run(store)  # 빈 DB 첫 실행과 같다: 편입 단계가 이 실행에서 SPY 보고를 저장한다

    assert refresh == CoverageRefresh(None, etfs=4, stocks=0, added=0, unmatched=0, sp500_period_end=None)
    assert store.list_coverage() == sorted(REMOTE_START, key=lambda c: c.ticker)  # SPY 이름은 설정 값으로 돌아왔다
    assert store.latest_holdings("SPY") is not None  # 다음 실행부터 주식 행이 생긴다


def test_SPY_N_PORT를_못_받은_날은_저장된_지난_보고로_같은_커버_범위를_유지한다(store, monkeypatch):
    monkeypatch.setattr(collect, "RETRY_DELAYS", (0.0, 0.0, 0.0))
    save_report(store)
    run(store, date(2026, 11, 16))
    coverage = store.list_coverage()

    # 기준일 2026-06-30 + 140일 = 11-17: 파이프라인이 새 SPY 보고를 찾다가 실패한다
    summary, refresh = run(store, date(2026, 11, 17), get=sec_day(**{
        SUBMISSIONS_URL.format(cik=SPY_CIK): TransientSourceError("sec http 503")}))

    assert SourceFailure(Source.HOLDINGS, "SPY", FailureReason.RETRIES_EXHAUSTED) in summary.failures
    assert store.list_coverage() == coverage
    assert (refresh.reason, refresh.stocks, refresh.sp500_period_end) == (None, 12, date(2026, 6, 30))


def test_SPY_보유_회사의_티커가_ETF_목록에_있으면_ETF_행이_이긴다(store):
    # 녹화 티커 목록에서 SPY 신탁 CIK의 티커는 SPY. 보고에 그 CIK 보통주 행이 있어도 주식 행으로 세지 않는다
    save_report(store, later_report(Holding("SPDR S&P 500 ETF Trust", "0000884394", Decimal("0.1"), "EC")))

    _, refresh = run(store)

    assert (refresh.stocks, refresh.added, refresh.unmatched) == (12, 12, 0)
    assert next(c for c in store.list_coverage() if c.ticker == "SPY") == Coverage(
        "SPY", "SPDR S&P 500 ETF", holdings_ticker="SPY")
