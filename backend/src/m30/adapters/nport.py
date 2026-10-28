"""SEC N-PORT(NPORT-P) 편입 종목 어댑터(#10 B). 표준 라이브러리만. 다시 시도는 하지 않는다(SourceCalls가 한다).
모든 요청은 EdgarClient.get(User-Agent·초당 8회·https·SEC 호스트·리다이렉트 금지)으로 보낸다. 실패 메시지는 상태만, from None."""

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cached_property

from m30.adapters import SourceError
from m30.adapters.edgar import DOCUMENT, SUBMISSION_TEXT_URL, SUBMISSIONS_URL, TICKERS_URL, TYPE, Get, ticker_ciks
from m30.adapters.filings import ACCESSION
from m30.adapters.holdings import Holding, HoldingsReport

MF_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"  # 펀드 심볼 → (CIK, 시리즈)
NPORT_FORM = "NPORT-P"  # 정확히 이것만. NPORT-P/A(정정)는 보지 않는다
# shortcut: 멀티 시리즈 신탁(Schwab)은 갱신일마다 다른 시리즈 보고까지 받는다(최대 이만큼). ETF가 수십 개로 늘면 .hdr.sgml(헤더)만 먼저 읽는다
SERIES_SCAN_MAX = 60
XML = re.compile(r"<XML>\s*(.*?)\s*</XML>", re.DOTALL)
DOCTYPE = re.compile(r"<!DOCTYPE", re.IGNORECASE)  # 엔티티 확장(billion laughs)을 막으려고 DTD가 있는 문서는 읽지 않는다
LEGAL_TAIL = frozenset({"the", "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "new", "de"})
_THE = re.compile(r"/the\b")
_CLASS = re.compile(r"\bclass [a-z]\b")
_TOKEN = re.compile(r"[a-z0-9]+")


def fund_series(get: Get) -> dict[str, tuple[str, str]]:
    """SEC 펀드 티커 목록 → {심볼(대문자): (CIK 10자리, seriesId)}. 같은 심볼에 값이 다르면 그 심볼은 뺀다.
    cik가 1 이상 10**10 미만 정수가 아니거나 심볼·시리즈가 문자열이 아닌 행은 버린다. 모양 오류 → SourceError("sec fund tickers shape")."""
    data = get(MF_TICKERS_URL)
    try:
        top = json.loads(data)
        cik, series, symbol = (top["fields"].index(name) for name in ("cik", "seriesId", "symbol"))
        rows = [(row[symbol], row[cik], row[series]) for row in top["data"]]
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise SourceError("sec fund tickers shape") from None
    found: dict[str, tuple[str, str]] = {}
    clashes = set()
    for name, number, series_id in rows:
        if not isinstance(name, str) or not isinstance(series_id, str) or type(number) is not int or not 1 <= number < 10**10:
            continue
        if found.setdefault(name.upper(), value := (f"{number:010d}", series_id)) != value:
            clashes.add(name.upper())
    return {name: value for name, value in found.items() if name not in clashes}


def issuer_key(name: str) -> str:
    """발행 회사 이름 → 비교 키. casefold → '/the'·'class x' 제거 → 영숫자 토큰 → 끝의 법인 꼬리 토큰 제거.
    'Coca-Cola Co/The' = 'COCA COLA CO' = 'coca cola', 'Alphabet Inc Class C' = 'Alphabet Inc.' = 'alphabet'."""
    tokens = _TOKEN.findall(_CLASS.sub(" ", _THE.sub(" ", name.casefold())))
    while tokens and tokens[-1] in LEGAL_TAIL:
        tokens.pop()
    return " ".join(tokens)


def issuer_ciks(get: Get) -> dict[str, str]:
    """SEC 회사 티커 목록 → {issuer_key(title): CIK 10자리}. 키가 같은데 CIK가 다르면 그 키는 뺀다(완전 일치만 믿는다).
    빈 키·잘못된 cik_str 행은 버린다. 모양 오류 → SourceError("sec tickers shape")."""
    data = get(TICKERS_URL)
    try:
        rows = [(row["title"], row["cik_str"]) for row in json.loads(data).values()]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise SourceError("sec tickers shape") from None
    found: dict[str, str] = {}
    clashes = set()
    for title, number in rows:
        if not isinstance(title, str) or type(number) is not int or not 1 <= number < 10**10 or not (key := issuer_key(title)):
            continue
        if found.setdefault(key, f"{number:010d}") != f"{number:010d}":
            clashes.add(key)
    return {key: cik for key, cik in found.items() if key not in clashes}


class EdgarHoldingsSource:
    """HoldingsSource 구현. ETF → (CIK, 시리즈) → 신탁 submissions의 NPORT-P를 최신부터(최대 SERIES_SCAN_MAX건) 받아
    시리즈가 같은 첫 보고. 두 목록(펀드·회사 티커)은 인스턴스마다 처음 필요할 때 한 번씩 받는다."""

    def __init__(self, get: Get) -> None:
        self._get = get
        self._lists: dict[str, bytes] = {}

    def _list(self, url: str) -> bytes:
        if url not in self._lists:
            self._lists[url] = self._get(url)
        return self._lists[url]

    @cached_property
    def _series(self) -> dict[str, tuple[str, str]]:
        return fund_series(self._list)

    @cached_property
    def _tickers(self) -> dict[str, str]:
        return ticker_ciks(self._list)

    @cached_property
    def _issuers(self) -> dict[str, str]:
        return issuer_ciks(self._list)

    def latest_report(self, fund: str) -> HoldingsReport | None:
        """None = SEC가 이 ETF를 모름, NPORT-P가 없음, 최근 SERIES_SCAN_MAX건 안에 그 시리즈 보고가 없음."""
        if fund in self._series:
            cik, series = self._series[fund]
        elif (cik := self._tickers.get(fund)) is not None:
            series = None  # 단일 시리즈 신탁(UIT): 가장 최근 NPORT-P
        else:
            return None
        for accession in _nport_accessions(self._get(SUBMISSIONS_URL.format(cik=cik)), cik)[:SERIES_SCAN_MAX]:
            url = SUBMISSION_TEXT_URL.format(cik_number=int(cik), accession_digits=accession.replace("-", ""), accession=accession)
            # Postgres text는 NUL을 받지 못한다. errors="replace"는 짝 없는 서로게이트를 만들지 않는다
            xml = _nport_xml(self._get(url).decode("utf-8", "replace").replace("\x00", "�"))
            report_series, period_end, rows = _parse(xml)
            if series is None or report_series == series:
                holdings = tuple(Holding(name, self._issuers.get(issuer_key(name)), pct, cat) for name, pct, cat in rows)
                return HoldingsReport(fund, accession, period_end, holdings, xml)
        return None


def _nport_accessions(data: bytes, cik: str) -> list[str]:
    """submissions JSON → form이 정확히 NPORT-P인 접수번호, recent 순서(최신 먼저)."""
    try:
        top = json.loads(data)
        if int(top["cik"]) != int(cik):
            raise ValueError("other company")
        recent = top["filings"]["recent"]
        rows = [a for a, form in zip(recent["accessionNumber"], recent["form"], strict=True) if form == NPORT_FORM]
        if not all(isinstance(a, str) and ACCESSION.fullmatch(a) for a in rows):  # 주소에 들어간다
            raise ValueError("accession")
    except (AttributeError, KeyError, TypeError, ValueError):
        raise SourceError("sec submissions shape") from None
    return rows


def _nport_xml(text: str) -> str:
    """전체 제출 파일 → TYPE NPORT-P 문서의 <XML> 안. 없으면 SourceError("nport shape")."""
    for match in DOCUMENT.finditer(text):
        kind, xml = TYPE.search(match.group(0)), XML.search(match.group(0))
        if kind is not None and kind.group(1).strip().upper() == NPORT_FORM and xml is not None:
            return xml.group(1)
    raise SourceError("nport shape")


def _local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]  # 네임스페이스와 무관하게 로컬 이름


def _child(element: ET.Element, name: str) -> str | None:
    found = next((c for c in element if _local(c) == name), None)
    return None if found is None or found.text is None else found.text.strip()


def _parse(xml: str) -> tuple[str | None, date, list[tuple[str, Decimal, str | None]]]:
    """(genInfo seriesId, repPdDate, invstOrSec마다 (name, pctVal, assetCat)). 모양 오류 → SourceError("nport shape")."""
    if DOCTYPE.search(xml):
        raise SourceError("nport shape")
    try:
        root = ET.fromstring(xml)
        gen = next(e for e in root.iter() if _local(e) == "genInfo")
        period_end = date.fromisoformat(_child(gen, "repPdDate") or "")
        rows = [
            (_child(e, "name") or "", Decimal(_child(e, "pctVal") or ""), _child(e, "assetCat"))
            for e in root.iter() if _local(e) == "invstOrSec"
        ]
    except (ET.ParseError, StopIteration, ValueError, InvalidOperation):
        raise SourceError("nport shape") from None
    return _child(gen, "seriesId"), period_end, rows
