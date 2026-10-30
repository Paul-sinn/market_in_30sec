# 정부 공식 출처 (지표 일정·공식 발표, #50)

확인일 2026-10-30. 키 없음, 스크래핑 없음(기관이 공개한 ICS·RSS만). 근거·판정은 아래 표, 코드는 `backend/src/m30/adapters/gov.py`·`gov_news.py`.

## 출처 조사 (확인일 2026-10-30 KST = 2026-10-29 ET, curl, 키 없음, 연락처 대신 `research@example.org` 자리표시자)

| 기관 | 쓰는 것 | 형식 | 키 | User-Agent | 약관 | 업데이트 | 판정 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BLS | 발표 일정 `https://www.bls.gov/schedule/news_release/bls.ics` | ICS. `DTSTART;TZID=US-Eastern:20261014T083000`, 2025-01-03~2026-12-30 313건(2027 아직 없음) | 없음 | **연락처 필수.** 기본 curl UA·이메일 없는 UA → 403 "Access Denied … bot activity", 이메일 모양 UA → 200 | 공공 영역, BLS 출처 표기 요청(`/bls/linksite.htm`). 로봇: "multiple times per second" 금지, 연락처 없는 로봇 차단 가능(`/bls/pss.htm`) | 일정 바뀔 때 | ✅ 지표 일정 |
| BLS | 발표별 Atom `https://www.bls.gov/feed/{empsit,cpi,ppi,jolts,eci}.rss` (목록 `/feed/`) | Atom. entry `id`·`title`·`content`(요약 문단, 일반 텍스트)·`published`(ISO, −04:00). 피드당 12건 | 없음 | 위와 같음 | 위와 같음 | 발표 때 | ✅ 공식 발표 |
| BEA | 발표 일정 `https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics` | ICS. `DTSTART:…Z`·`DTSTART;VALUE=DATE-TIME:…Z`(UTC), 줄 접기, `\,` 이스케이프. 2025-01-07~2027-12-22 168건 | 없음 | 아무 UA나 200 | 연방 저작물(공공 영역), 인용 지침: 보증으로 읽히게 쓰지 말 것(`/help/guidelines-for-citing-bea`) | 일정 바뀔 때 | ✅ 지표 일정 |
| BEA | 보도자료 `https://apps.bea.gov/rss/rss.xml` | RSS 2.0, 49건. `guid`(URL)·`title`·`description`(CDATA HTML)·`pubDate`(`Thu, 29 Oct 2026 08:30:00 EDT`) | 없음 | 아무 UA나 200 | 위와 같음 | 발표 때(ttl 17) | ✅ 공식 발표 |
| Census | 지표 최신값 `https://www.census.gov/economic-indicators/indicator.xml` | RSS 2.0, 지표마다 최신 1건. **`guid`는 지표 고정값(`retail_sales`)이라 발표마다 같다** | 없음 | 아무 UA나 200 | 공공 영역, 출처 표기 권장(`/about/policies/citation.html`) | 발표 때 | ✅ 공식 발표 |
| Census | 발표 일정 `/economic-indicators/calendar-listview.html` | **HTML 표뿐**(ICS·JSON·RSS 링크 없음, JS도 데이터 파일을 안 부름) | — | — | — | — | ❌ 스크래핑 금지 → 지표 일정에서 뺀다 |
| 연준 | 통화정책 보도자료 `https://www.federalreserve.gov/feeds/press_monetary.xml` (목록 `/feeds/feeds.htm`) | RSS 2.0, 15건. 값이 CDATA. **FOMC 성명 항목의 description은 제목과 같다**("Federal Reserve issues FOMC statement") → 금리 결정 내용은 RSS에 없다 | 없음 | 아무 UA나 200 | 공공 영역, 복사·배포 자유, 출처 표기 요청(`/disclaimer.htm`) | 발표 때 | ✅ 공식 발표 (내용 한계 D3) |
| 연준 | FOMC 일정 `/monetarypolicy/fomccalendars.htm` | **HTML뿐**(ICS 없음) | — | — | — | 연 1회(2026-10-28 갱신) | ⚠️ 실행 중 읽지 않는다. 날짜를 코드 표로 둔다(D2, NYSE 휴장일 표와 같은 방식) |
| 재무부 | 보도자료 | `home.treasury.gov/news/press-releases/feed` 404, 보도자료 페이지에 RSS 링크 없음, 응답 10~37초 | — | — | — | — | ❌ 뺀다 |
| 재무부 | Fiscal Data `api.fiscaldata.treasury.gov/services/calendar/release`, `…/upcoming_auctions` | JSON, 키 없음 | 없음 | — | — | — | ❌ 데이터셋 공개 일정·국채 입찰이라 캐주얼 투자자의 "오늘 지표"가 아니다 |
| (참고) FRED | 발표 일정 | JSON | **필요** | — | 정부 출처 시리즈만 | — | ❌ 키 필요(HANDOFF 4장 "키 필요하면 사용자 조치로 분리") |
| (참고) 노동부 실업수당 청구 | — | — | — | — | — | — | ❌ 티켓 기관 목록 밖, 조사 안 함 |

- 실패 시 동작(관찰): BLS 차단은 HTTP 403 + HTML. 나머지는 200. 리다이렉트는 하나도 없었다(그래서 따라가지 않는다).
- Python 3.13.12의 expat 2.6.3: 표준 `xml.etree.ElementTree`는 billion laughs에 막혀 있고 외부 엔티티를 받지 않는다. 새 의존성 없음.
- 이 표는 `_workspace`(git 제외)에만 있으므로 메인이 `docs/vendors/gov-sources.md`로 옮긴다(6장).


## 운영 메모

- BLS는 연락처 User-Agent 필수(없으면 403). 운영은 `SEC_USER_AGENT` 값을 BLS 요청에만 쓴다. 기관 요청 간격 1초
- BLS 일정 ICS는 2026-12-30까지만 있다. 2026-12-31부터 지표 줄 `Update delayed` + 실행 실패 알림 → 12월 중순까지 BLS 2027 일정 게재 확인
- FOMC 날짜는 코드 표(휴장일 표처럼 손으로 관리). 연준 성명 RSS는 본문이 제목뿐이라 소식 줄은 "성명을 냈다"까지만
