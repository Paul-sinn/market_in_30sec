"""정부 기관 공식 ICS·RSS(#50). 표준 라이브러리만, 스크래핑 없음. 다시 시도는 SourceCalls. 출처 조사: docs/vendors/gov-sources.md

연락처(SEC_USER_AGENT) 노출 방지는 edgar.py와 같다: 값은 EdgarSettings(repr 숨김) 안에만 있고, 헤더는 _request 안에서만 만든다.
연락처는 BLS에만 보낸다(연락처 없는 로봇을 막는 곳). 모든 실패는 기관 라벨·상태만 담은 메시지로 from None.
허용 호스트에만 보내고 리다이렉트는 따라가지 않는다. 압축을 요청하지 않는다(받은 Content-Encoding이 identity가 아니면 실패)."""

import http.client
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import UTC, date, datetime, time

from m30.adapters import SourceError, TransientSourceError, error_for_status
from m30.adapters.edgar import Get, Throttle, _NoRedirect
from m30.adapters.indicators import IndicatorRelease
from m30.config import ET, EdgarSettings

LABELS = {"www.bls.gov": "bls", "www.bea.gov": "bea", "apps.bea.gov": "bea", "www.census.gov": "census",
          "www.federalreserve.gov": "fed"}  # 허용 호스트(netloc 그대로 비교: 포트·사용자 정보가 붙으면 다르다) → 오류 메시지 라벨
GOV_HOSTS = frozenset(LABELS)
CONTACT_HOSTS = frozenset({"www.bls.gov"})  # 연락처 UA를 요구하는 곳만(BLS 로봇 정책). 다른 기관엔 보내지 않는다
USER_AGENT = "m30/0.1 (market_in_30sec morning pipeline)"
GOV_THROTTLE = Throttle(1.0)  # 요청 시작 간격 1초(BLS: 초당 여러 번 금지). 프로세스에 하나, SEC와 따로

_OPENER = urllib.request.build_opener(_NoRedirect)  # 테스트가 이 자리를 패치한다


class GovClient:
    def __init__(self, contact: EdgarSettings, *, timeout: float = 30.0, throttle: Throttle = GOV_THROTTLE) -> None:
        self._contact = contact
        self._timeout = timeout
        self._throttle = throttle

    def get(self, url: str) -> bytes:
        """응답 본문. https·GOV_HOSTS·기본 포트가 아니면 요청 전에 ValueError.
        실패: 상태 → error_for_status(라벨), 타임아웃·접속 실패 → TransientSourceError, 압축 응답 → SourceError. 모두 from None."""
        host = urllib.parse.urlsplit(url).netloc
        if not url.startswith("https://") or host not in GOV_HOSTS:
            raise ValueError("government requests must go to https on an allowed agency host")
        label = LABELS[host]
        self._throttle.wait()
        try:
            with _OPENER.open(self._request(url), timeout=self._timeout) as response:
                encoding = (response.headers.get("Content-Encoding") or "identity").strip().lower()
                body = response.read()
        except urllib.error.HTTPError as e:  # URLError의 하위 클래스라 먼저 받는다
            raise error_for_status(label, e.code) from None
        except TimeoutError:
            raise TransientSourceError(f"{label} timeout") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):  # 접속 실패·응답 도중 끊김
            raise TransientSourceError(f"{label} connection failed") from None
        if encoding != "identity":
            raise SourceError(f"{label} response encoding")
        return body

    def _request(self, url: str) -> urllib.request.Request:
        """헤더(User-Agent)는 이 프레임 안에서만 만든다. Request의 repr에는 헤더가 없다."""
        contact = urllib.parse.urlsplit(url).netloc in CONTACT_HOSTS
        return urllib.request.Request(url, headers={"User-Agent": self._contact.user_agent if contact else USER_AGENT})


BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_ICS_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"

# 화면에 나가는 이름(copy-reviewer 검수 대상). 외부 제목은 화면에 그대로 나가지 않는다: 닫힌 목록 → 코드 상수
BLS_MAJOR: Mapping[str, tuple[str, str]] = {  # ICS SUMMARY(정확히 같음) → (화면 이름, Atom 피드 slug). Real Earnings는 CPI와 같은 시각이라 뺀다
    "Employment Situation": ("Jobs report", "empsit"),
    "Consumer Price Index": ("CPI", "cpi"),
    "Producer Price Index": ("Producer prices", "ppi"),
    "Job Openings and Labor Turnover Survey": ("Job openings", "jolts"),
    "Employment Cost Index": ("Labor costs", "eci"),
}
BEA_MAJOR: tuple[tuple[str, str], ...] = (  # (제목 앞부분, 화면 이름). ICS·RSS 공용, 처음 맞는 것. "… by State"·"GDP by County"는 안 맞는다
    ("GDP (", "GDP"),
    ("Gross Domestic Product, ", "GDP"),
    ("Personal Income and Outlays, ", "Income and spending"),
    ("U.S. International Trade in Goods and Services, ", "Trade balance"),
)
FOMC_NAME = "Fed decision"
FOMC_TIME = time(14, 0)  # 성명 발표 2:00 PM ET
FOMC_YEARS = range(2026, 2028)
# 회의 둘째 날(성명일). 출처 federalreserve.gov/monetarypolicy/fomccalendars.htm, Last Update 2026-10-28
# shortcut: 임시 회의·일정 변경은 반영 안 됨. 연준이 다음 해를 실으면 손으로 더하고 FOMC_YEARS를 늘린다(trading_day.py와 같은 방식)
FOMC_DAYS = frozenset(date(year, month, day) for year, month, day in (
    (2026, 1, 28), (2026, 3, 18), (2026, 4, 29), (2026, 6, 17), (2026, 7, 29), (2026, 9, 16), (2026, 10, 28), (2026, 12, 9),
    (2027, 1, 27), (2027, 3, 17), (2027, 4, 28), (2027, 6, 9), (2027, 7, 28), (2027, 9, 15), (2027, 10, 27), (2027, 12, 8),
))
FOMC_RAW = "FOMC statement {day} 2:00 PM ET (code table from federalreserve.gov fomccalendars.htm, last update 2026-10-28)"

ET_TZIDS = frozenset({"US-Eastern", "America/New_York"})  # 벽시계로 받는 TZID. 나머지는 모양 오류
_VEVENT = re.compile(r"^BEGIN:VEVENT\r?$.*?^END:VEVENT(?=\r?$)", re.MULTILINE | re.DOTALL)
_FOLD = re.compile(r"\r?\n[ \t]")  # 줄 접기: 줄바꿈 + 공백·탭 하나
_ESCAPE = re.compile(r"\\([,;\\nN])")
_DATE_TIME = re.compile(r"([0-9]{8}T[0-9]{6})(Z?)")


def bea_name(title: str) -> str | None:
    return next((name for prefix, name in BEA_MAJOR if title.startswith(prefix)), None)


def _bls_name(summary: str) -> str | None:
    return BLS_MAJOR[summary][0] if summary in BLS_MAJOR else None


def ics_events(data: bytes, label: str) -> list[tuple[str, datetime, str]]:
    """VEVENT마다 (SUMMARY 이스케이프 푼 값, DTSTART ET aware, VEVENT 원문). DTSTART는 …Z(UTC) 또는 TZID ∈ ET_TZIDS의 벽시계만.
    SUMMARY·DTSTART가 없거나 이 모양이 아니면 SourceError(f"{label} ics shape")."""
    try:
        events = []
        for match in _VEVENT.finditer(data.decode("utf-8")):
            props = {}
            for line in _FOLD.sub("", match.group(0)).splitlines():
                head, _, value = line.partition(":")
                name, *params = head.split(";")
                props.setdefault(name.upper(), (dict(p.partition("=")[::2] for p in params), value))
            _, summary = props["SUMMARY"]
            events.append((_ESCAPE.sub(lambda m: "\n" if m[1] in "nN" else m[1], summary), _start(*props["DTSTART"]),
                           match.group(0)))
    except (KeyError, ValueError):  # UnicodeDecodeError는 ValueError
        raise SourceError(f"{label} ics shape") from None
    return events


def _start(params: dict[str, str], value: str) -> datetime:
    found = _DATE_TIME.fullmatch(value)
    if found is None or params.get("VALUE", "DATE-TIME") != "DATE-TIME" or set(params) - {"VALUE", "TZID"}:
        raise ValueError("dtstart")
    wall = datetime.strptime(found[1], "%Y%m%dT%H%M%S")
    if found[2] and "TZID" not in params:
        return wall.replace(tzinfo=UTC).astimezone(ET)
    if not found[2] and params.get("TZID") in ET_TZIDS:
        return wall.replace(tzinfo=ET)
    raise ValueError("dtstart zone")


class GovIndicatorSource:
    """IndicatorSource 구현. BLS ICS → BEA ICS → FOMC 표. Census 일정은 HTML뿐이라 없다(스크래핑 금지)."""

    def __init__(self, get: Get) -> None:
        self._get = get

    def releases(self, start: date, end: date) -> list[IndicatorRelease]:
        """세 곳이 [start, end]를 덮지 않거나 하나라도 실패하면 SourceError(줄 전체 지연: 반쪽 목록을 보여 주지 않는다).
        주요 발표만, ET 날짜 ∈ [start, end], (name, released_at) 중복 제거. [] = 세 곳 확인, 주요 발표 없음. None은 돌려주지 않는다."""
        if start.year not in FOMC_YEARS or end.year not in FOMC_YEARS:
            raise SourceError("fomc table range")
        found = []
        for url, label, name_of in ((BLS_ICS_URL, "bls", _bls_name), (BEA_ICS_URL, "bea", bea_name)):
            events = ics_events(self._get(url), label)
            days = [at.date() for _, at, _ in events]
            if not days or not min(days) <= start or not end <= max(days):  # 아직 안 실은 기간을 "없음"으로 쓰지 않는다
                raise SourceError(f"{label} calendar range")
            found += [IndicatorRelease(name, at, raw) for summary, at, raw in events
                      if start <= at.date() <= end and (name := name_of(summary)) is not None]
        found += [IndicatorRelease(FOMC_NAME, datetime.combine(day, FOMC_TIME, ET), FOMC_RAW.format(day=day.isoformat()))
                  for day in sorted(FOMC_DAYS) if start <= day <= end]
        unique: dict[tuple[str, datetime], IndicatorRelease] = {}
        for release in found:
            unique.setdefault((release.name, release.released_at), release)
        return list(unique.values())
