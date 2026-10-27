# Marketstack 구독 전 확인 (#18)

확인일: 2026-10-26 (실행 22:44~22:46 ET, 장 마감 후 약 6시간 45분) · 확인: backend-dev(Claude) · 키: Paul의 무료(Free) 플랜 키

- HANDOFF 4장 예외(2026-10-18 사용자 결정): 무료 API는 **구독 전 성능 검사에만** 쓴다. 받은 시세 값은 검사 프로세스 메모리에만 두고 버렸다. 원격·로컬 DB, 파일, 화면 출력 어디에도 남기지 않았다
- 이 문서에는 건수·참거짓·비율·지연·날짜만 있다. 가격 값은 없다
- 표시: ✅ 충족 · ❌ 불충족 · ⚠️ 일부만 확인 · ⏳ 미정

---

## 0. 요약

| #18 첫 번째 완료 기준 | 결과 | 근거 절 |
| --- | --- | --- |
| 분할 조정가 | ✅ `close`부터 분할 조정값. 분할 2건 모두 `adj_close` 연속 | 2-1 |
| 배당 조정가 | ❌ 배당 정보는 오지만 `adj_close`에 반영 안 됨: 배당 주는 7종목 중 6종목이 1년 내내 `adj_close` = `close` | 2-1 |
| 약관의 내부 상업 이용 | ✅ Basic부터 "Commercial Use", 내부 업무 사용 허용. 앱 사용자 표시는 ⏳ 서면 확인 대기 | 6 |
| HTTPS | ✅ 무료 플랜에서도 HTTPS 요청 성공 | 2-2 |
| TQQQ·SCHD 포함 | ✅ 둘 다 251/251봉 | 2-3 |
| 1년 이력 | ✅ 부른 8종목 모두 251/251 거래일, 빠진 날 0 | 2-4 |
| 장 마감 후 업데이트 시각 | ⚠️ 상한만 확인: 마감 약 6시간 45분 뒤 당일 봉 있음. 처음 들어오는 시각은 안 잼 | 2-5 |

- 결론: **배당 조정가가 안 맞는다.** #18 두 번째 완료 기준("하나라도 안 맞으면 Tiingo로 바꾸고 같은 항목을 확인") 대상
- 데이터 이상도 있음(4절): 한 종목 시계열 안에 공급원·통화 표기가 다른 봉이 섞이고, 빈 종가·OHLC 불일치 봉이 1년 2,008봉 중 38봉(약 1.9%). #18 추가 기준대로면 그만큼 그 종목·그날 카드가 지연된다
- 무료 플랜으로 본 결과다. 유료(Basic) 데이터가 다른지는 확인 안 함(5절)

---

## 1. 방법

- 엔드포인트: `GET https://api.marketstack.com/v2/eod` (v2), 파라미터 `symbols=<한 종목>`, `date_from=2025-10-27`, `date_to=2026-10-26`, `sort=ASC`, `limit=1000`. 1년치(251봉)가 한 페이지에 들어와 페이지 넘김 없음
- 한 종목씩 부른 이유: v1 문서에 "Each symbol consumes one API request"(여러 종목을 한 요청에 넣으면 종목 수만큼 차감). v2에서도 그런지 몰라서, 어느 방식이든 1회로 끝나는 한 종목 요청만 썼다
- 부른 종목: TQQQ, SCHD, SPY, QQQ, KO, XOM, JPM(실험 15종목 중 7) + NFLX(실험 종목 아님. 창 안에 10:1 분할이 있어 분할 확인 대조군). KO는 공급원 분해용으로 한 번 더
- 안 부른 종목: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, PFE. 요청 예산(10회) 밖. 키 없이 받는 종목 목록 CSV로 존재만 확인(2-3)
- 요청 수: 키를 넣은 HTTPS 요청 10회
  - 1회는 Cloudflare가 막음(403, `error code: 1010`). 할당량에 안 잡힘(다음 요청의 `x-quota-remaining`이 100)
  - 할당량 차감 9회. 응답 헤더 `x-quota-remaining` 100 → 92(9번째 요청 직전 값). 무료 월 100회 중 9회 사용, 91회 남음(추정)
- 거래일 기준: 평일에서 NYSE 휴장일 10일(2025-11-27, 2025-12-25, 2026-01-01, 2026-01-19, 2026-02-16, 2026-04-03, 2026-05-25, 2026-06-19, 2026-07-03, 2026-09-07)을 뺀 251일. `backend/src/m30/trading_day.py`에는 휴장일 달력이 아직 없어(#16) 검사 스크립트에 직접 넣었다
- 키: macOS 키체인 → 검사 프로세스 하나의 환경 변수로만. 요청 URL(쿼리에 `access_key`가 들어감)·키는 출력하지 않았다. 실패는 예외 클래스·HTTP 상태·오류 코드만 찍었다. 리다이렉트는 따라가지 않았다(http로 내려가지 않게)
- 스크립트는 레포에 넣지 않았다(검사 전용 임시 파일)

---

## 2. 결과

### 2-1. 분할·배당 조정가

봉에 오는 필드: `open` `high` `low` `close` `volume` `adj_open` `adj_high` `adj_low` `adj_close` `adj_volume` `split_factor` `dividend` `name` `symbol` `exchange` `exchange_code` `asset_type` `price_currency` `date`

**분할** (API의 `split_factor` ≠ 1인 날)

| 종목 | 분할일 | 배수 | `close`가 배수만큼 뜀 | `adj_close` 연속 |
| --- | --- | --- | --- | --- |
| NFLX | 2025-11-17 | 10 | 아니오 | 예 |
| TQQQ | 2025-11-20 | 2 | 아니오 | 예 |

- `close`부터 이미 분할 조정된 값이다. 분할 전 실제 거래 가격(원래 종가)은 이 엔드포인트로 받을 수 없다
- 나머지 6종목은 창 안에 분할 없음

**배당** (판정: r = `adj_close` ÷ `close`. 배당락일 t에서 r(t−1) ÷ r(t)이 1 − 배당 ÷ `close`(t−1)과 5% 안이면 "맞음". v2 문서가 말하는 CRSP 방식 식)

| 종목 | 창 안 배당락일(`dividend` > 0) | `adj_close` ≠ `close`인 봉 있음 | 배당락일 조정 맞음 |
| --- | --- | --- | --- |
| TQQQ | 4 | 예 | 3/4 |
| SCHD | 4 | 아니오 (모든 봉 같음) | 0/4 |
| SPY | 4 | 아니오 | 0/4 |
| QQQ | 4 | 아니오 | 0/4 |
| KO | 4 | 아니오 | 0/4 |
| XOM | 4 | 아니오 | 0/4 |
| JPM | 4 | 아니오 | 0/4 |
| NFLX | 0 | 아니오 | 해당 없음 |

- 배당 금액(`dividend`)과 배당락일은 온다. 하지만 `adj_close`에 반영된 건 TQQQ 하나뿐
- v2 문서는 "분할·배당을 CRSP 방식으로 조정"이라고 적었지만 실제 응답과 다르다
- 배당·분할 없는 날에 r이 0.01% 넘게 바뀐 경우: TQQQ 2번(최대 0.19%), 나머지 0번
- 8종목 모두 마지막 봉에서 r = 1 (조정은 과거 쪽에만 걸리는 방식과 맞음)

### 2-2. HTTPS

- ✅ 무료 플랜 키로 `https://api.marketstack.com/v2/eod` 요청 9회 모두 200. 가격표도 Free·Basic 모두 "HTTPS Encryption"
- 주의: Python 기본 User-Agent(`Python-urllib/…`)는 Cloudflare가 403(`error code: 1010`)으로 막는다. 키 없는 요청으로 비교: 기본 User-Agent는 403, User-Agent를 넣으면 401(`missing_access_key`, 정상 응답). 어댑터는 User-Agent를 직접 넣어야 한다

### 2-3. TQQQ·SCHD 포함

| 종목 | 거래소(MIC) | 종류 | 봉 수 / 거래일 |
| --- | --- | --- | --- |
| TQQQ | XNAS | ETF | 251 / 251 |
| SCHD | ARCX | ETF | 251 / 251 |
| SPY | ARCX | ETF | 251 / 251 |
| QQQ | XNAS | ETF | 251 / 251 |
| KO, XOM, JPM | XNYS | Stock | 251 / 251 |
| NFLX | XNAS | Stock | 251 / 251 |

- 키 없이 받는 종목 목록(`supported_tickers_2.csv`)에 실험 15종목 모두 있다. 단 이 파일의 `endDate`가 전부 2025-03-12라 오래된 스냅숏이다("daily updated" 표기와 다름)
- 목록에서 같은 티커가 두 번 나오는 경우: META(거래소 빈칸인 ETF 행), PFE(ASX 행). 어댑터는 `exchange`(MIC)를 지정하는 게 안전하다

### 2-4. 1년 이력

- ✅ 무료 키로 2025-10-27 ~ 2026-10-26 요청, 부른 8종목 모두 251/251 거래일
- 빠진 날 0, 달력 밖 날(휴장일·주말) 0, 같은 날짜 중복 0, 페이지 잘림 없음(`pagination.total` 251)
- 첫 봉 2025-10-27. 가격표 기준 무료는 "1 Year History", Basic은 "10 Years History"(Basic은 미확인)

### 2-5. 장 마감 후 업데이트 시각

- ⚠️ 2026-10-26(월) 22:44~22:46 ET 실행 때 8종목 모두 2026-10-26 봉이 있었다. 장 마감 16:00 ET 뒤 늦어도 약 6시간 45분 안에 들어온다는 상한만 확인
- 처음 들어오는 시각은 안 쟀다(마감 뒤 여러 번 불러야 해서 요청 예산 밖). 문서에도 업데이트 시각 안내 없음

---

## 3. 응답 시간·요청 수

| 요청 | 상태 | 응답 시간(ms) |
| --- | --- | --- |
| TQQQ (1차, 기본 User-Agent) | 403 Cloudflare 1010 | 628 |
| TQQQ | 200 | 793 |
| SCHD | 200 | 752 |
| SPY | 200 | 616 |
| QQQ | 200 | 626 |
| KO | 200 | 642 |
| XOM | 200 | 538 |
| JPM | 200 | 659 |
| NFLX | 200 | 482 |
| KO (공급원 분해) | 200 | 700 |

- 성공 9회: 최소 482 · 중앙값 642 · 최대 793 ms (응답 본문 읽기까지 포함, 1년치 251봉)
- 응답 헤더: 초당 5회 제한(`x-ratelimit-limit-second: 5`), 월 할당 `x-quota-limit: 100`, 한 종목 요청은 `x-increment-usage: 1`
- 요청 수: 키를 넣은 요청 10회, 할당량 차감 9회

---

## 4. 데이터 이상 (8종목 2,008봉)

| 종목 | 가격 빈값·0 이하 (OHLC) | 조정가 빈값·0 이하 | OHLC 불일치 (원래 값) | OHLC 불일치 (조정값) | 거래량 빈값·음수 |
| --- | --- | --- | --- | --- | --- |
| TQQQ | 0 | 0 | 0 | 0 | 0 |
| SCHD | 4 | 13 | 2 | 0 | 0 |
| SPY | 5 | 15 | 2 | 2 | 0 |
| QQQ | 0 | 10 | 0 | 2 | 0 |
| KO | 3 | 13 | 7 | 2 | 0 |
| XOM | 3 | 13 | 5 | 0 | 0 |
| JPM | 3 | 13 | 4 | 2 | 0 |
| NFLX | 0 | 0 | 0 | 0 | 0 |
| 합계 | 18 | 77 | 20 | 8 | 0 |

- 빈값 = None·NaN·무한대. OHLC 불일치 = 종가 > 고가, 종가 < 저가, 고가 < 저가, 시가 > 고가, 시가 < 저가 중 하나. 빈값 봉은 불일치 칸에서 빼서 두 칸은 겹치지 않는다
- 필드별 빈값(2,008봉 중): `close` 15, `adj_close` 15, `adj_open`·`adj_high`·`adj_low` 60, `adj_volume` 80, `exchange_code`·`asset_type` 767
- 원래 값 기준으로 쓸 수 없는 봉 38개(빈값 18 + 불일치 20) = 약 1.9%

**공급원·표기 섞임**

- 한 종목 시계열 안에 표기가 다른 봉이 섞인다. KO: 거래소 XNYS인데 `price_currency`가 ARS인 봉. XOM·JPM: MXN 봉. NFLX: `exchange_code` 없는 USD 봉
- `exchange_code` 없는 봉 767개: KO 34, XOM·JPM·NFLX 합계 733(종목별로는 안 나눔), TQQQ·SCHD·SPY·QQQ 0. XOM·JPM·NFLX는 봉 대부분이 이쪽 묶음이다
- KO 분해(공급원 분해 요청): 251봉 =
  - (NYSE, Stock, USD, 이름 "Coca-Cola Company") 217봉
  - (`exchange_code` 없음, ARS, 이름 "COCA-COLA CO") 30봉. 2026-01-05 ~ 2026-09-25 사이에 흩어져 있음
  - (`exchange_code` 없음, USD, 이름 "COCA-COLA CO") 4봉. 2026-10-15 ~ 2026-10-21
  - 날짜 순으로 묶음이 18번 바뀐다
- KO 이상 봉 위치:
  - 빈 종가 3건 모두 ARS 묶음: 2026-06-09, 2026-06-10, 2026-06-15. 2026-06-15는 배당락일이라 배당일 봉에 종가가 없다
  - OHLC 불일치 7건: NYSE 묶음 6건(예: 2025-11-03, 2026-02-06, 2026-03-11), USD 다른 묶음 1건(2026-10-19)
  - ARS 묶음의 가격 크기는 USD 봉과 같은 범위(중앙값의 0.5~2배 밖 0건). 통화 표기만 틀린 것으로 보이지만 확인은 아님
- 추정(확인 아님): v2 문서의 종목 목록 파일 이름이 `v2_eod_tickers_finnworlds_tiingo.xlsx`이고 가격표 FAQ는 "미국 거래소 데이터는 Tiingo에서 라이선스"라고 한다. v2 EOD가 공급원 둘 이상을 날짜별로 섞는 것으로 보인다

---

## 5. 확인 안 한 것

- 나머지 8종목(AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, PFE)의 API 응답. 요청 예산 밖
- 유료(Basic) 플랜 데이터가 무료와 같은지(배당 조정, 이상 봉)
- Basic 10년 이력
- 장 마감 뒤 당일 봉이 처음 들어오는 시각(상한 약 6시간 45분만 확인)
- 여러 종목을 한 요청에 넣을 때 할당량 차감(v1 문서: 종목마다 1회. v2는 미확인)
- 지난 봉이 나중에 고쳐지는지(같은 날짜를 다른 날 다시 받아 비교하지 않음)
- ARS·MXN 표기 봉이 실제로 다른 시장 가격인지, 표기만 틀린지
- `/v2/splits`·`/v2/dividends`·`/v2/eod/latest` 엔드포인트. 요청 예산 밖이라 봉의 `split_factor`·`dividend`로 대신함
- 키가 맞을 때의 오류 응답 형식. 키 없는 요청의 실제 응답은 `{"error": {"code": "missing_access_key", "message": …}}`(문자 코드, `message`)로, v2 스웨거 문서의 형식(숫자 `code`, `type`, `info`)과 다르다
- 2026-06 이후 임시 휴장일. 이번 창에서는 빠진 날·남는 날이 0이라 영향 없음

---

## 6. 약관 (상업 이용·표시 권한)

법률 검토 아님. 2026-10-26에 오케스트레이터(Claude)가 읽은 것.

- 가격표: Free "Non-Commercial Use", Basic($9.99/월)부터 "Commercial Use". 앱 사용자에게 보여 주는 것(재배포·표시)은 가격표에 없다
- Marketstack 약관 링크(`marketstack.com/terms`)는 APILayer 공통 법률 페이지로 이어진다. Marketstack 전용 약관은 찾지 못했다
- APILayer Master SaaS Subscription Agreement(Ver. 082523):
  - 2(a): 서비스를 "access and use"하는 제한적·비독점·양도 불가 라이선스. 제3자 사용은 "Customer's own internal business operations"를 위한 외주처만
  - 5(a): 계약서에 정한 경우 말고는 복제 금지. 파생물 권리도 APILayer·라이선서 소유
  - 앱 사용자에게 데이터를 보여 주는 것을 허락하는 조항은 없다(금지 조항도 없다)
- 판단: 내부 상업 이용(Paul만 보는 실험 대시보드)은 ✅. 앱 사용자 표시는 서면 확인 전까지 ⏳
- 2026-10-26 Paul이 Marketstack 지원팀에 표시 권한·조정가·업데이트 시각을 묻는 메일을 보냄. 답장 오면 여기에 기록

---

## 근거 링크 (2026-10-26 확인)

- 가격표·FAQ: https://marketstack.com/pricing
- APILayer 법률 문서 목록: https://www.ideracorp.com/legal/APILayer (Master SaaS Subscription Agreement PDF)
- v2 API 스펙(스웨거): https://api.swaggerhub.com/apis/apilayer-863/MarketstackAPIv2/2.0.0/swagger.json
- v2 문서: https://docs.apilayer.com/marketstack/docs/marketstack-api-v2-v-2-0-0
- v1 문서("Each symbol consumes one API request. Maximum: 100 symbols"): https://docs.apilayer.com/marketstack/docs/api-endpoints-v1
- 종목 목록 CSV: https://marketstack.com/download/supported_tickers_2.csv
- v2 EOD 종목·공급원 목록(파일 이름만 봄, 받지 않음): https://marketstack.com/download/v2_eod_tickers_finnworlds_tiingo.xlsx
