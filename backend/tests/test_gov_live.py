"""live: 실제 정부 기관 호출(요청 14회, 간격 1초). 기본 실행에서 빠진다(pyproject addopts "-m 'not live'").
녹화(tests/gov_responses/)를 받을 때 본 모양이 지금도 같은지 본다. 단언은 불리언 + 기관 라벨만(실패 메시지에 원문·연락처가 찍히지 않게).
BLS는 연락처 없는 요청을 막는다(403): BLS를 부르는 테스트는 SEC_USER_AGENT가 있을 때만. 값은 명령 줄에서만 넣는다:
  SEC_USER_AGENT="…" uv run pytest -q -m live tests/test_gov_live.py"""

import os
from datetime import datetime, time, timedelta

import pytest

from m30.adapters.edgar import Get
from m30.adapters.gov import BEA_ICS_URL, BEA_MAJOR, BLS_MAJOR, FOMC_NAME, GovClient, GovIndicatorSource, ics_events
from m30.adapters.gov_news import AGENCY_NAMES, BEA_RSS_URL, CENSUS_MAJOR, CENSUS_RSS_URL, FED_RSS_URL, GovNewsSource, _rss
from m30.config import ET, SEC_UA_VAR, EdgarSettings, load_edgar_settings
from m30.pipeline.collect import valid_market_news, valid_releases

pytestmark = pytest.mark.live
NAMES = {name for name, _ in BLS_MAJOR.values()} | {name for _, name in BEA_MAJOR} | {FOMC_NAME}


class Counted:
    def __init__(self, get: Get) -> None:
        self._get, self.requests = get, 0

    def __call__(self, url: str) -> bytes:
        self.requests += 1
        return self._get(url)


@pytest.mark.skipif(not os.environ.get(SEC_UA_VAR), reason=f"{SEC_UA_VAR} is not set (BLS blocks requests without a contact)")
def test_실제_기관에서_45일_지표_일정과_30일_공식_발표를_녹화와_같은_모양으로_읽는다():
    get = Counted(GovClient(load_edgar_settings()).get)
    today = datetime.now(ET).date()
    releases = GovIndicatorSource(get).releases(today, today + timedelta(days=45))  # 오늘이 BLS·BEA 범위 밖이면 SourceError
    until = datetime.now(ET)
    items = GovNewsSource(get).items(until - timedelta(days=30), until)

    # 단언 전에 참/거짓으로 만든다: pytest가 실패 설명에 원문을 찍지 않게
    releases_ok = valid_releases(releases) and len(releases) > 0
    names_ok = {r.name for r in releases} <= NAMES
    times_ok = {r.released_at.astimezone(ET).time() for r in releases} <= {time(8, 30), time(10, 0), time(14, 0)}
    items_ok = valid_market_news(items) and len(items) > 0
    sources_ok = {i.source for i in items} <= set(AGENCY_NAMES.values())
    assert releases_ok, "indicators: no valid releases in 45 days"
    assert names_ok, "indicators: name outside the closed list"
    assert times_ok, "indicators: release time other than 8:30, 10:00, 14:00 ET"
    assert items_ok, "market_news: no valid items in 30 days"
    assert sources_ok, "market_news: source outside AGENCY_NAMES"
    assert get.requests == 10, "requests per run"  # 일정 2 + 피드 8


def test_연락처가_필요_없는_기관은_고정_이름으로_받고_녹화와_같은_모양이다():
    client = GovClient(EdgarSettings(user_agent="unused"))  # 연락처는 BLS 요청에만 쓴다. 이 테스트는 BLS를 부르지 않는다
    today = datetime.now(ET).date()

    days = [at.date() for _, at, _ in ics_events(client.get(BEA_ICS_URL), "bea")]
    assert days and min(days) <= today <= max(days), "bea: calendar does not cover today"
    for url, label in ((BEA_RSS_URL, "bea"), (CENSUS_RSS_URL, "census"), (FED_RSS_URL, "fed")):
        parsed = _rss(client.get(url), label)
        valid = len(parsed) > 0 and valid_market_news([item for item, _ in parsed])
        assert valid, f"{label}: feed shape"
        if label == "census":
            guids_ok = CENSUS_MAJOR <= {guid for _, guid in parsed}  # 지표마다 최신 1건: 네 지표 guid가 늘 있다
            assert guids_ok, "census: major indicator guid missing"
