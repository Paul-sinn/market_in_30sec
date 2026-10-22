"""SEC EDGAR 실제 공시 어댑터. 표준 라이브러리만. 다시 시도는 하지 않는다(SourceCalls가 한다).

User-Agent(사용자 연락처) 노출 방지는 anthropic.py와 같다: 값은 EdgarSettings(repr 숨김) 안에만 있고, 헤더는 요청을 만드는
도우미 _request 안에서만 만든다. get 프레임의 지역 변수에 User-Agent·헤더를 두지 않는다(pytest --showlocals가 찍는다).
모든 실패는 상태만 담은 메시지로 from None. SEC 호스트에만 보내고 리다이렉트는 따라가지 않는다."""

import gzip
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable
from datetime import date, datetime
from html.parser import HTMLParser

from m30.adapters import SourceError, TransientSourceError, error_for_status
from m30.adapters.filings import ACCESSION, Filing, FilingForm
from m30.config import ET, EdgarSettings

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"  # cik: 10자리
SUBMISSION_TEXT_URL = "https://www.sec.gov/Archives/edgar/data/{cik_number}/{accession_digits}/{accession}.txt"
SEC_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})  # netloc 그대로 비교: 포트·사용자 정보가 붙으면 다르다
MIN_INTERVAL = 0.125  # 요청 시작 간격(초) = 초당 최대 8회. SEC 상한 10회 미만
FORMS = frozenset(FilingForm)  # 정확히 "8-K"·"8-K/A". 8-K12B 등은 다른 서식
RECENT_COLUMNS = ("accessionNumber", "form", "acceptanceDateTime", "items", "reportDate")  # submissions filings.recent의 쓰는 열
TEXT_EXTENSIONS = frozenset({".htm", ".html", ".txt"})  # 읽는 문서. PDF·그림(jpg·gif)·XBRL(xml·xsd)은 읽지도 저장하지도 않는다
HEADER = re.compile(r"<SEC-HEADER>.*?</SEC-HEADER>", re.DOTALL)  # 접수 시각·항목 원본. 몇 KB라 남긴다(사람 대조)
DOCUMENT = re.compile(r"<DOCUMENT>.*?</DOCUMENT>", re.DOTALL)
TYPE = re.compile(r"<TYPE>([^\n]*)")
FILENAME = re.compile(r"<FILENAME>([^\n]*)")
TEXT = re.compile(r"<TEXT>(.*)</TEXT>", re.DOTALL)
# U5 = A: 8-K 본문의 서식 표지(주소·체크 박스·상장 증권 목록 $0.00001 par value)를 뗀다. 분류·첫 번째 줄은 앞 4,000자만 본다
COVER_END = re.compile(r"\b(?:Item\s+[1-9]\.[0-9]{2}|Explanatory\s+Note)\b", re.IGNORECASE)
HIDDEN_TAGS = frozenset({"title", "script", "style", "ix:header"})  # 안의 글자를 버린다. ix:header = iXBRL 숨은 값(CIK·false…)
BLOCK_TAGS = frozenset(
    "address article aside blockquote br caption dd div dl dt figcaption figure footer h1 h2 h3 h4 h5 h6 header hr li ol p pre"
    " section table tbody td tfoot th thead tr ul".split()
)  # 열고 닫을 때 공백. 그 밖(span·b·a·font·ix:nonfraction)은 붙인다: $<ix:nonFraction>94.9</…> billion → $94.9 billion

Get = Callable[[str], bytes]


class Throttle:
    # shortcut: 스레드 안전하지 않다(파이프라인은 한 스레드에서 순서대로 부른다). 동시에 부르게 되면 잠금을 더한다
    def __init__(
        self, interval: float, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        """앞 요청을 시작하고 interval이 안 지났으면 남은 시간만큼 잔다. 그다음 이번 시작 시각을 적는다."""
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            self._sleep(self._last + self._interval - now)
            now = self._clock()
        self._last = now


SEC_THROTTLE = Throttle(MIN_INTERVAL)  # 프로세스에 하나. 클라이언트를 여럿 만들어도, 다시 시도해도 같은 간격을 센다


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트가 호스트 확인을 건너뛰지 못하게: 30x는 HTTPError로 남아 SourceError가 된다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)  # 테스트가 이 자리를 패치한다


class EdgarClient:
    def __init__(self, settings: EdgarSettings, *, timeout: float = 30.0, throttle: Throttle = SEC_THROTTLE) -> None:
        self._settings = settings
        self._timeout = timeout
        self._throttle = throttle

    def get(self, url: str) -> bytes:
        """응답 본문(Content-Encoding: gzip이면 푼 것). https·SEC_HOSTS·기본 포트가 아니면 요청 전에 ValueError."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.netloc not in SEC_HOSTS:
            raise ValueError("SEC requests must go to https://www.sec.gov or https://data.sec.gov")
        self._throttle.wait()
        try:
            with _OPENER.open(self._request(url), timeout=self._timeout) as response:
                encoding = (response.headers.get("Content-Encoding") or "identity").strip().lower()
                body = response.read()
            if encoding == "gzip":
                body = gzip.decompress(body)
        except urllib.error.HTTPError as e:  # URLError의 하위 클래스라 먼저 받는다
            raise error_for_status("sec", e.code) from None
        except TimeoutError:
            raise TransientSourceError("sec timeout") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, EOFError, zlib.error):  # 접속 실패·끊김·깨진 gzip
            raise TransientSourceError("sec connection failed") from None
        if encoding not in ("gzip", "identity"):
            raise SourceError("sec response encoding")
        return body

    def _request(self, url: str) -> urllib.request.Request:
        """헤더(User-Agent)는 이 프레임 안에서만 만든다. Request의 repr에는 헤더가 없다."""
        return urllib.request.Request(url, headers={"User-Agent": self._settings.user_agent, "Accept-Encoding": "gzip"})


def ticker_ciks(get: Get) -> dict[str, str]:
    """SEC 공식 티커 목록 → {티커(대문자): 10자리 CIK}. 한 CIK에 티커 여럿 가능(GOOGL·GOOG).
    서로 다른 CIK에 같은 티커 → 그 티커는 뺀다(그 티커만 닫고 나머지는 쓴다). cik_str가 1 이상 10**10 미만 정수가 아니면 그 항목을 버린다.
    모양 오류 → SourceError("sec tickers shape"). get의 SourceError는 그대로 올린다."""
    data = get(TICKERS_URL)
    try:
        rows = [(row["ticker"].upper(), row["cik_str"]) for row in json.loads(data).values()]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise SourceError("sec tickers shape") from None
    ciks: dict[str, str] = {}
    clashes = set()
    for ticker, number in rows:
        if type(number) is not int or not 1 <= number < 10**10:
            continue
        if ciks.setdefault(ticker, f"{number:010d}") != f"{number:010d}":
            clashes.add(ticker)
    return {ticker: cik for ticker, cik in ciks.items() if ticker not in clashes}


class EdgarFilingSource:
    """FilingSource 구현. CIK마다 submissions 1회 + 기간 안 8-K·8-K/A마다 전체 제출 파일 1회.
    받기 오류(SourceError)는 잡지 않는다: 다시 시도·차단·기록은 SourceCalls가 CIK 단위로 한다."""

    def __init__(self, get: Get) -> None:
        self._get = get

    def filings(self, cik: str, since: datetime, until: datetime) -> list[Filing]:
        """순서 = submissions 순서(최신 먼저). submissions 모양 오류 → SourceError("sec submissions shape")."""
        rows = _recent(self._get(SUBMISSIONS_URL.format(cik=cik)), cik, since, until)
        filings = []
        for accession, form, accepted_at, items, report_date in rows:
            url = SUBMISSION_TEXT_URL.format(
                cik_number=int(cik), accession_digits=accession.replace("-", ""), accession=accession
            )
            # Postgres text는 NUL을 받지 못한다. errors="replace"는 짝 없는 서로게이트를 만들지 않는다(valid_filings가 CIK를 지연시키지 않게)
            text = self._get(url).decode("utf-8", "replace").replace("\x00", "\ufffd")
            documents = _documents(text, form)
            sections = [section for _, _, section in documents]
            header = HEADER.search(text)
            if sections and header:  # 쓸 문서가 없으면 헤더도 빼 빈 원본: valid_filings가 그 CIK를 invalid_data로 지연(닫힌 쪽)
                sections.insert(0, header.group(0))
            raw = "\n".join(sections)
            texts = [(kind, _document_text(section, extension)) for kind, extension, section in documents]
            body = next((_without_cover(text) for kind, text in texts if kind == form), "")
            exhibit99 = "\n\n".join(text for kind, text in texts if kind != form and text)
            filings.append(Filing(accession, cik, form, accepted_at, items, body or None, exhibit99 or None, raw, report_date))
        return filings


def _recent(
    data: bytes, cik: str, since: datetime, until: datetime
) -> list[tuple[str, FilingForm, datetime, tuple[str, ...], date | None]]:
    """submissions JSON → 기간 안 8-K·8-K/A 행. 그 행만 접수 시각을 읽는다."""
    try:
        top = json.loads(data)
        if int(top["cik"]) != int(cik):
            raise ValueError("other company")
        recent = top["filings"]["recent"]
        columns = [recent[name] for name in RECENT_COLUMNS]
        if not all(type(column) is list for column in columns):
            raise ValueError("columns")
        rows = []
        for accession, form, accepted, items, report in zip(*columns, strict=True):  # 열 길이가 다르면 ValueError
            if form not in FORMS:
                continue
            accepted_at = _accepted_at(accepted)
            if not since <= accepted_at < until:
                continue
            if ACCESSION.fullmatch(accession) is None:  # 주소에 들어간다. 경로에 이상한 글자가 끼지 않게
                raise ValueError("accession")
            items = tuple(i.strip() for i in items.split(",") if i.strip())  # EDGAR 표기 그대로("2.02"). 형식은 valid_filings가 본다
            rows.append((accession, FilingForm(form), accepted_at, items, date.fromisoformat(report) if report else None))
    except (AttributeError, KeyError, TypeError, ValueError):
        raise SourceError("sec submissions shape") from None
    return rows


def _accepted_at(value: str) -> datetime:
    """A1: acceptanceDateTime의 숫자는 동부 벽시계 시각이고 끝의 Z는 UTC 표시가 아니다. 명시적 오프셋이 있으면 따른다.
    동부로 읽어야 틀려도 소식을 잃지 않는다: UTC로 잘못 읽으면 06~08시 ET 장전 공시가 02~04시가 되어 이미 지난 카드 기간에 들어간다."""
    at = datetime.fromisoformat(value.removesuffix("Z"))
    return at.replace(tzinfo=ET) if at.tzinfo is None else at.astimezone(ET)


def _documents(text: str, form: FilingForm) -> list[tuple[str, str, str]]:
    """전체 제출 파일(SGML) → 쓰는 문서의 (TYPE, 확장자, <DOCUMENT> 구간 원문), 파일 안 순서(SEQUENCE 순 = 보통 99.1, 99.2).
    쓰는 문서 = TYPE이 서식 이름(본문)이거나 EX-99·EX-99.*이고 파일이 HTML·텍스트인 것. 원격 DB 무료 한도(500MB) 때문에
    나머지 문서(그림·XBRL·ZIP·PDF·다른 첨부)는 저장하지 않는다(SEC-HEADER는 filings가 따로 앞에 붙인다).
    TYPE·FILENAME·TEXT가 없는 블록은 건너뛴다."""
    documents = []
    for match in DOCUMENT.finditer(text):
        section = match.group(0)
        kind, filename = TYPE.search(section), FILENAME.search(section)
        if kind is None or filename is None or TEXT.search(section) is None:
            continue
        kind, extension = kind.group(1).strip().upper(), os.path.splitext(filename.group(1).strip().lower())[1]
        if (kind == form or kind == "EX-99" or kind.startswith("EX-99.")) and extension in TEXT_EXTENSIONS:
            documents.append((kind, extension, section))
    return documents


def _document_text(section: str, extension: str) -> str:
    """<TEXT> 안의 글자, 공백 한 칸. .txt는 그대로, HTML은 태그를 뗀다."""
    text = TEXT.search(section).group(1)
    return " ".join(text.split()) if extension == ".txt" else _html_text(text)


def _without_cover(text: str) -> str:
    """처음 나오는 Item N.NN 또는 Explanatory Note부터. 둘 다 없으면 전체. 정정 공시는 항목 앞의 Explanatory Note가 핵심이다."""
    found = COVER_END.search(text)
    return text[found.start():] if found else text


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0  # 숨김 태그 깊이(겹쳐도 센다)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in HIDDEN_TAGS:
            self._hidden += 1
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in HIDDEN_TAGS:
            self._hidden = max(0, self._hidden - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def _html_text(html: str) -> str:
    """HTML → 글자, 공백 한 칸. 파서 예외는 잡지 않는다(버그로 올린다)."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())
