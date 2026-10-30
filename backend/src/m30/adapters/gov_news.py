"""정부 기관 공식 발표 피드(#50): BLS Atom 5개 → BEA RSS → Census RSS → 연준 통화정책 RSS. 재무부는 RSS가 없어 뺀다.
XML은 표준 라이브러리(expat 2.6+: 외부 엔티티를 받지 않고 billion laughs를 막는다). 다시 시도는 SourceCalls."""

import dataclasses
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from m30.adapters import SourceError
from m30.adapters.edgar import Get, _html_text
from m30.adapters.gov import BLS_MAJOR, bea_name
from m30.adapters.market_news import MarketNewsItem

AGENCY_NAMES = {"bls": "Bureau of Labor Statistics", "bea": "Bureau of Economic Analysis",
                "census": "Census Bureau", "fed": "Federal Reserve"}  # MarketNewsItem.source = 소식 줄 맨 앞(copy-reviewer 대상)
BLS_FEED_URL = "https://www.bls.gov/feed/{slug}.rss"  # 이름은 .rss지만 Atom
BEA_RSS_URL = "https://apps.bea.gov/rss/rss.xml"
CENSUS_RSS_URL = "https://www.census.gov/economic-indicators/indicator.xml"
CENSUS_MAJOR = frozenset({"retail_sales", "housing_starts", "home_sales", "durable_goods"})  # guid(지표 고정값)
FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
ATOM = "{http://www.w3.org/2005/Atom}"


class GovNewsSource:
    """MarketNewsSource 구현. 받기 오류(SourceError)는 잡지 않는다: 다시 시도·차단·기록은 SourceCalls가 출처 전체 단위로 한다."""

    def __init__(self, get: Get) -> None:
        self._get = get

    def items(self, since: datetime, until: datetime) -> list[MarketNewsItem]:
        """피드 8개. 하나라도 실패·모양 오류면 SourceError(줄 전체 지연). published_at ∈ [since, until), 주요 발표만, (source, key) 중복 제거.
        BLS 피드는 이미 주요 발표, BEA는 BEA_MAJOR 제목, Census는 CENSUS_MAJOR guid, 연준은 통화정책 피드 전체."""
        found = []
        for slug in dict.fromkeys(slug for _, slug in BLS_MAJOR.values()):
            found += _atom(self._get(BLS_FEED_URL.format(slug=slug)), "bls")
        found += [item for item, _ in _rss(self._get(BEA_RSS_URL), "bea") if bea_name(item.title) is not None]
        # Census guid는 지표 고정값이라 발표마다 같다: 발표 시각을 붙여 키로 쓴다
        found += [dataclasses.replace(item, key=f"{guid}@{item.published_at.isoformat()}")
                  for item, guid in _rss(self._get(CENSUS_RSS_URL), "census") if guid in CENSUS_MAJOR]
        found += [item for item, _ in _rss(self._get(FED_RSS_URL), "fed")]
        unique: dict[tuple[str, str], MarketNewsItem] = {}
        for item in found:
            if since <= item.published_at < until:
                unique.setdefault((item.source, item.key), item)
        return list(unique.values())


def _atom(data: bytes, label: str) -> list[MarketNewsItem]:
    """Atom entry마다 항목(key = id, published = ISO). content type이 html이면 태그를 뗀다(xhtml은 글자만 모은다)."""
    try:
        root = ET.fromstring(data)
        if root.tag != f"{ATOM}feed":
            raise ValueError("root")
        items = []
        for entry in root.iterfind(f"{ATOM}entry"):
            content = entry.find(f"{ATOM}content")
            text = "" if content is None else "".join(content.itertext())
            if content is not None and content.get("type") == "html":
                text = _html_text(text)
            items.append(MarketNewsItem(
                _required(entry, f"{ATOM}id"), AGENCY_NAMES[label], _aware(datetime.fromisoformat(_required(entry, f"{ATOM}published"))),
                _required(entry, f"{ATOM}title"), text, ET.tostring(entry, encoding="unicode"),
            ))
    except (ET.ParseError, ValueError):
        raise SourceError(f"{label} feed shape") from None
    return items


def _rss(data: bytes, label: str) -> list[tuple[MarketNewsItem, str]]:
    """RSS 2.0 item마다 (항목, guid). key = guid, published = pubDate(RFC 822), 본문 = description 태그를 뗀 글자."""
    try:
        root = ET.fromstring(data)
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError("root")
        items = []
        for element in root.iterfind("channel/item"):
            guid = _required(element, "guid")
            items.append((MarketNewsItem(
                guid, AGENCY_NAMES[label], _aware(parsedate_to_datetime(_required(element, "pubDate"))),
                _required(element, "title"), _html_text(element.findtext("description") or ""),
                ET.tostring(element, encoding="unicode"),
            ), guid))
    except (ET.ParseError, ValueError):
        raise SourceError(f"{label} feed shape") from None
    return items


def _required(element: ET.Element, tag: str) -> str:
    value = (element.findtext(tag) or "").strip()
    if not value:
        raise ValueError(tag)
    return value


def _aware(at: datetime) -> datetime:
    if at.tzinfo is None:  # 모르는 시간대 이름(parsedate_to_datetime) 또는 오프셋 없는 ISO
        raise ValueError("naive")
    return at
