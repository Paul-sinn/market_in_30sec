"""test_production이 하위 프로세스로만 돌리는 파일. test_ 접두사가 없어 기본 수집에서 빠진다.
운영 CLI(m30.pipeline.__main__.main)를 그대로 돌리고, 바깥 전송 층 넷(EdgarClient.get·GovClient.get·AnthropicLLM = run_production이
주입받는 셋, 스펙 #26 D4·#50 D4 + Tiingo opener)만 네트워크 없는 대역으로 바꾼다. 기관 응답은 기본 quiet_gov(발표 없는 피드). Tiingo는 TiingoPriceSource를 그대로 두고 opener만 바꾼다:
토큰이 실제 요청 헤더까지 가는 경로를 지난다. 사용법: python tests/production_probe.py <상황> --production 2026-10-16
끝나면 stderr 마지막 줄에 불러온 가짜 모듈 목록(fake_modules=[…])을 찍는다. 그래서 가짜 어댑터를 불러오는 테스트 모듈
(test_edgar 등)을 import하지 않는다. Discord 웹훅(#17)은 notify._OPENER만 바꾸고, 보낸 메시지를 stdout에 webhook_content=<JSON>으로 찍는다."""

import io
import json
import os
import sys
import urllib.error
import urllib.response
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import psycopg

from m30 import notify
from m30.adapters import AccessDeniedError, SourceError, TransientSourceError, tiingo
from m30.adapters.edgar import SUBMISSION_TEXT_URL, SUBMISSIONS_URL, TICKERS_URL
from m30.adapters.gov import BEA_ICS_URL, BLS_ICS_URL
from m30.adapters.gov_news import BEA_RSS_URL, BLS_FEED_URL, CENSUS_RSS_URL, FED_RSS_URL
from m30.adapters.nport import MF_TICKERS_URL

RESPONSES = Path(__file__).resolve().parent / "edgar_responses"
# 실험 회사 11개의 CIK (company_tickers.json fixture, #19 test_실험_종목_15개…와 같은 값). ETF 4개는 CIK 없음
COMPANY_CIKS = {
    "AAPL": "0000320193", "MSFT": "0000789019", "NVDA": "0001045810", "AMZN": "0001018724", "GOOGL": "0001652044",
    "META": "0001326801", "TSLA": "0001318605", "JPM": "0000019617", "XOM": "0000034088", "KO": "0000021344",
    "PFE": "0000078003",
}
ETFS = ("SPY", "QQQ", "TQQQ", "SCHD")
# 녹화 N-PORT(#10, test_nport docstring): 신탁 CIK → 그 submissions에 남긴 NPORT-P 접수번호
NPORT = {"0000884394": ("0001410368-26-089410",), "0001067839": ("0001067839-26-000030",),
         "0001454889": ("0001410368-26-108627", "0001410368-26-108609")}
DRAFT_CANARY = "DraftCanary58 Apple will surely beat estimates"  # 검수 전 AI 문장 자리. 공개 로그에 나오면 샌 것


class NoCallLLM:
    """공시가 없는 날이라 LLM을 부르면 안 된다. 부르면 실행이 크게 멈춘다."""

    def complete(self, request):
        raise AssertionError("LLM must not be called")


def empty_submissions(cik):
    data = json.loads((RESPONSES / "CIK0000320193.json").read_bytes())
    data["cik"] = str(int(cik))
    data["filings"]["recent"] = {name: [] for name in data["filings"]["recent"]}
    return json.dumps(data).encode()


def nport_responses():
    """ETF 편입 보고: 펀드 티커 목록 + 신탁 3개 submissions + NPORT-P 전체 제출 파일 4개(녹화)."""
    responses = {MF_TICKERS_URL: (RESPONSES / "company_tickers_mf.json").read_bytes()}
    for cik, accessions in NPORT.items():
        responses[SUBMISSIONS_URL.format(cik=cik)] = (RESPONSES / f"CIK{cik}.json").read_bytes()
        for a in accessions:
            url = SUBMISSION_TEXT_URL.format(cik_number=int(cik), accession_digits=a.replace("-", ""), accession=a)
            responses[url] = (RESPONSES / f"{a}.txt").read_bytes()
    return responses


def quiet_day(**changes):
    """공시가 하나도 없는 날의 SEC 응답: 티커 목록 + 회사 11개의 빈 submissions + ETF 편입 보고(녹화)."""
    return {TICKERS_URL: (RESPONSES / "company_tickers.json").read_bytes()} | {
        SUBMISSIONS_URL.format(cik=cik): empty_submissions(cik) for cik in COMPANY_CIKS.values()
    } | nport_responses() | changes


GOV = Path(__file__).resolve().parent / "gov_responses"  # 실제 녹화(#50): 2026-10-29 ET에 받은 응답 그대로
GOV_FILES = {
    BLS_ICS_URL: "bls.ics", BEA_ICS_URL: "bea.ics",
    **{BLS_FEED_URL.format(slug=slug): f"bls_{slug}.atom" for slug in ("empsit", "cpi", "ppi", "jolts", "eci")},
    BEA_RSS_URL: "bea.rss", CENSUS_RSS_URL: "census.xml", FED_RSS_URL: "fed_monetary.xml",
}


def gov_day(**changes):
    """기관 응답 녹화 그대로(주소 → 바이트). changes로 주소 하나를 다른 바이트·예외로 바꾼다."""
    return {url: (GOV / name).read_bytes() for url, name in GOV_FILES.items()} | changes


EMPTY_FEEDS = {url: b'<feed xmlns="http://www.w3.org/2005/Atom"><id>empty</id></feed>' if "/feed/" in url
               else b'<rss version="2.0"><channel><title>empty</title></channel></rss>' for url in GOV_FILES if not url.endswith(".ics")}


def quiet_gov(**changes):
    """발표가 하나도 없는 피드 + 녹화 일정(2026-10-16은 주요 발표 없음): 시장 한눈에 두 줄 확인함·없음, LLM 0회."""
    return gov_day(**EMPTY_FEEDS) | changes


class GlanceLLM:
    """시장 한눈에 소식 줄 요청만 답한다: 초안 → 항목 0의 숫자 없는 문장, 판정 → fact. 그 밖(분류·첫 번째 줄)은 실행을 크게 멈춘다."""

    def __init__(self, sentence="Federal Reserve issued its policy statement"):
        self.requests, self._sentence = [], sentence

    def complete(self, request):
        from m30.llm import LLMReply
        from m30.pipeline.glance import GLANCE_SYSTEM
        from m30.pipeline.review import FACTCHECK_SYSTEM

        self.requests.append(request)
        if request.system == GLANCE_SYSTEM:
            return LLMReply(json.dumps({"item": 0, "number": None, "sentence": self._sentence}))
        if request.system == FACTCHECK_SYSTEM:
            return LLMReply(json.dumps({"label": "fact"}))
        raise AssertionError("only market glance requests are expected")


def tiingo_day():
    """15종목 모두 같은 Tiingo 응답: 10-14 100 → 10-15 101(+1.0%)."""
    fields = ("close", "high", "low", "open", "adjClose", "adjHigh", "adjLow", "adjOpen")
    return json.dumps([
        {"date": f"{day}T00:00:00.000Z", **dict.fromkeys(fields, close), "volume": 1000, "adjVolume": 1000, "divCash": 0.0,
         "splitFactor": 1.0}
        for day, close in (("2026-10-14", 100), ("2026-10-15", 101))
    ]).encode()


class TiingoOpener:
    """tiingo._OPENER 자리. tiingo_quiet: 정상 봉. tiingo_denied: 401인데 오류의 주소·사유·본문에 받은 Authorization 값을 넣는다
    (라이브러리가 요청 값을 오류에 옮기는 최악). 그 밖의 상황: 부르면 안 된다(키가 없으면 NoPriceSource)."""

    def __init__(self, situation):
        self._situation = situation

    def open(self, request, timeout):
        sent = request.get_header("Authorization")
        if self._situation == "tiingo_quiet":
            return urllib.response.addinfourl(io.BytesIO(tiingo_day()), Message(), request.full_url, 200)
        if self._situation == "tiingo_denied":
            raise urllib.error.HTTPError(f"{request.full_url}&t={sent}", 401, f"bad {sent}", Message(), io.BytesIO(sent.encode()))
        raise AssertionError("Tiingo must not be called")


class WebhookOpener:
    """notify._OPENER 자리. 받은 주소가 환경 변수 값인지 확인만 하고(찍지 않는다) 메시지를 찍는다.
    webhook_down: 500인데 오류의 주소·사유에 받은 주소를 넣는다(라이브러리가 요청 값을 오류에 옮기는 최악)."""

    def __init__(self, situation):
        self._situation = situation

    def open(self, request, timeout):
        assert request.full_url == os.environ["DISCORD_WEBHOOK_URL"], "webhook url"
        print(f"webhook_content={json.dumps(json.loads(request.data)['content'], ensure_ascii=False)}")
        if self._situation == "webhook_down":
            raise urllib.error.HTTPError(request.full_url, 500, f"down {request.full_url}", Message(), io.BytesIO(b""))
        return urllib.response.addinfourl(io.BytesIO(b""), Message(), request.full_url, 204)


def patch(module, name, value):
    """속성 바꿔치기. 이름이 바뀌면 바꿔치기가 조용히 빈 동작이 되므로 먼저 있는지 확인한다(#26 R3)."""
    assert hasattr(module, name), f"{module.__name__}.{name}"
    setattr(module, name, value)


GOV_CANARY = "GovCanaryQx"  # 숫자 없음(LLM 문장 숫자 대조). 기관 원문(BLS 본문·연준 제목)과 LLM 문장 자리. 공개 로그·실행 기록에 나오면 샌 것
BLS_PPI = BLS_FEED_URL.format(slug="ppi")
BLS_URLS = [url for url in GOV_FILES if url.startswith("https://www.bls.gov/")]


def canary_gov():
    """녹화 응답에 캐너리: BLS PPI 본문(10/16 기간 안)과 연준 FOMC 성명 제목(10/29 기간 안)."""
    day = gov_day()
    return day | {
        BLS_PPI: day[BLS_PPI].replace(b"The Producer Price Index for final demand", f"{GOV_CANARY} prices".encode()),
        FED_RSS_URL: day[FED_RSS_URL].replace(b"issues FOMC statement", f"issues {GOV_CANARY} statement".encode()),
    }


def main(situation, args):
    import m30.pipeline.__main__ as cli
    from m30.models import HoldItem, HoldStage
    from m30.pipeline import collect

    responses = quiet_day(**{
        "quiet": {},
        "denied": {SUBMISSIONS_URL.format(cik=COMPANY_CIKS["AAPL"]): AccessDeniedError("sec http 403")},
        "no_tickers": {TICKERS_URL: SourceError("sec tickers shape")},
        # 라이브러리가 키를 예외 메시지에 넣는 경우(http.client의 잘못된 헤더 값처럼)
        "crash": {TICKERS_URL: ValueError(f"Invalid header value {os.environ['ANTHROPIC_API_KEY']!r}")},
        # 종목 하나의 예상 못 한 예외(#17 D5 층 1): 그 CIK만 지연, 실행은 끝까지
        "ticker_crash": {
            SUBMISSIONS_URL.format(cik=COMPANY_CIKS["AAPL"]): ValueError(f"bad {os.environ['ANTHROPIC_API_KEY']!r}")},
        "db_error": {},
        "db_lost": {},
        "tiingo_quiet": {},
        "tiingo_denied": {},
        "webhook_down": {},
        "gov_canary": {},
        "gov_denied": {},
        "gov_down": {},
    }[situation])

    gov_responses = {
        "gov_canary": canary_gov(),
        "gov_denied": quiet_gov(**dict.fromkeys(BLS_URLS, AccessDeniedError("bls http 403"))),  # 연락처 없는 로봇 차단
        "gov_down": quiet_gov(**{BLS_ICS_URL: TransientSourceError("bls http 503")}),
    }.get(situation) or quiet_gov()

    def recorded(table):
        def get(url):
            outcome = table[url]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return get

    patch(cli, "EdgarClient", lambda settings: SimpleNamespace(get=recorded(responses)))
    patch(cli, "GovClient", lambda settings: SimpleNamespace(get=recorded(gov_responses)))
    llm = GlanceLLM(f"Federal Reserve issued its {GOV_CANARY} statement") if situation == "gov_canary" else NoCallLLM()
    patch(cli, "AnthropicLLM", lambda settings: llm)
    patch(collect, "RETRY_DELAYS", (0.0, 0.0, 0.0))  # 503 다시 시도를 실제로 기다리지 않는다
    patch(tiingo, "_OPENER", TiingoOpener(situation))
    patch(notify, "_OPENER", WebhookOpener(situation))
    if situation == "db_error":
        # 검사 제약(replacement_iff_review)에 걸리는 보류함 행: 서버 오류 DETAIL에 행 내용(검수 전 문장)이 들어간다
        def run_production(store, day, *, get, gov_get, llm, prices):
            store.replace_hold_items(
                "AAPL", day, [HoldItem("AAPL", day, "0000320193-26-000001", HoldStage.DRAFT, DRAFT_CANARY, ("r",), None)]
            )

        patch(cli, "run_production", run_production)
    if situation == "db_lost":
        # 실행 중 DB 연결이 끊김(#26 R1): 연결 실패(DBConnectError)와 같은 부모 클래스지만 우리가 쓴 문구가 아니다
        def run_production(store, day, *, get, gov_get, llm, prices):
            raise psycopg.OperationalError(f"server closed the connection {os.environ['ANTHROPIC_API_KEY']}")

        patch(cli, "run_production", run_production)
    try:
        return cli.main(args)
    finally:
        print(f"fake_modules={sorted(m for m in sys.modules if m.startswith('m30') and 'fake' in m)}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
