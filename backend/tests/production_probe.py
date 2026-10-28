"""test_production이 하위 프로세스로만 돌리는 파일. test_ 접두사가 없어 기본 수집에서 빠진다.
운영 CLI(m30.pipeline.__main__.main)를 그대로 돌리고, 바깥 전송 층 셋(EdgarClient.get·AnthropicLLM = run_production이 주입받는
그 둘, 스펙 #26 D4 + Tiingo opener)만 네트워크 없는 대역으로 바꾼다. Tiingo는 TiingoPriceSource를 그대로 두고 opener만 바꾼다:
토큰이 실제 요청 헤더까지 가는 경로를 지난다. 사용법: python tests/production_probe.py <상황> --production 2026-10-16
끝나면 stderr 마지막 줄에 불러온 가짜 모듈 목록(fake_modules=[…])을 찍는다. 그래서 가짜 어댑터를 불러오는 테스트 모듈
(test_edgar 등)을 import하지 않는다."""

import io
import json
import os
import sys
import urllib.error
import urllib.response
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from m30.adapters import AccessDeniedError, SourceError, tiingo
from m30.adapters.edgar import SUBMISSION_TEXT_URL, SUBMISSIONS_URL, TICKERS_URL
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


def main(situation, args):
    import m30.pipeline.__main__ as cli
    from m30.models import HoldItem, HoldStage

    responses = quiet_day(**{
        "quiet": {},
        "denied": {SUBMISSIONS_URL.format(cik=COMPANY_CIKS["AAPL"]): AccessDeniedError("sec http 403")},
        "no_tickers": {TICKERS_URL: SourceError("sec tickers shape")},
        # 라이브러리가 키를 예외 메시지에 넣는 경우(http.client의 잘못된 헤더 값처럼)
        "crash": {TICKERS_URL: ValueError(f"Invalid header value {os.environ['ANTHROPIC_API_KEY']!r}")},
        "db_error": {},
        "tiingo_quiet": {},
        "tiingo_denied": {},
    }[situation])

    def get(url):
        outcome = responses[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    cli.EdgarClient = lambda settings: SimpleNamespace(get=get)
    cli.AnthropicLLM = lambda settings: NoCallLLM()
    tiingo._OPENER = TiingoOpener(situation)
    if situation == "db_error":
        # 검사 제약(replacement_iff_review)에 걸리는 보류함 행: 서버 오류 DETAIL에 행 내용(검수 전 문장)이 들어간다
        def run_production(store, day, *, get, llm, prices):
            store.replace_hold_items(
                "AAPL", day, [HoldItem("AAPL", day, "0000320193-26-000001", HoldStage.DRAFT, DRAFT_CANARY, ("r",), None)]
            )

        cli.run_production = run_production
    try:
        return cli.main(args)
    finally:
        print(f"fake_modules={sorted(m for m in sys.modules if m.startswith('m30') and 'fake' in m)}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
