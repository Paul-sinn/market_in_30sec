# Tiingo 구독 전 확인 (#18)

확인일: 2026-10-26 (실행 22:59~23:00 ET, 장 마감 후 약 7시간) · 확인: backend-dev(Claude) · 토큰: Paul의 무료(Starter) 플랜 토큰

- #18 두 번째 완료 기준: Marketstack이 배당 조정가를 못 맞춰서(`docs/vendors/marketstack.md`) 같은 항목을 Tiingo로 확인했다
- HANDOFF 4장 예외(2026-10-18 사용자 결정): 무료 API는 **구독 전 성능 검사에만** 쓴다. 받은 시세 값은 검사 프로세스 메모리에만 두고 버렸다. 원격·로컬 DB, 파일, 화면 출력 어디에도 남기지 않았다
- 이 문서에는 건수·참거짓·비율·지연·날짜만 있다. 가격 값은 없다
- 표시: ✅ 충족 · ❌ 불충족 · ⚠️ 일부만 확인 · ⏳ 미정

---

## 0. 요약

| #18 완료 기준 항목 | 결과 | 근거 절 |
| --- | --- | --- |
| 분할 조정가 | ✅ `close`는 원래 거래 가격, `adjClose`는 분할 조정값. 분할 2건 모두 `adjClose` 연속 | 2-1 |
| 배당 조정가 | ✅ 배당 주는 13종목의 배당락일 52개 모두 `adjClose`에 반영. 5% 기준으로 51/52 맞음, 남은 1건(META)은 배당락일 당일 종가 기준 식으로 맞음 | 2-1 |
| 약관의 내부 상업 이용 | ✅ Commercial($50/월) "Internal Use Only" = 내부 상업 이용. 앱 표시는 Redistribution(스타트업 $250/월, 영업 확인) | 6 |
| HTTPS | ✅ 무료 플랜에서 HTTPS 요청 33회 모두 200. 토큰은 `Authorization` 헤더로 보냄 | 2-2 |
| TQQQ·SCHD 포함 | ✅ 둘 다 251/251봉 | 2-3 |
| 1년 이력 | ✅ 16종목 모두 251/251 거래일, 빠진 날 0 | 2-4 |
| 장 마감 후 업데이트 시각 | ⚠️ 문서: 대부분 17:30 EST, 거래소 수정은 20:00 EST까지. 실측은 상한만: 마감 약 7시간 뒤 당일 봉 있음 | 2-5 |

- 결론: **기술 항목은 모두 맞는다.** Marketstack에서 걸린 배당 조정가가 Tiingo에서는 맞고, 이상 봉도 0개(4절)
- 약관(6절): 실험은 Commercial($50/월), 앱 공개는 Redistribution(스타트업 $250/월, 영업 서면 확인 필요)
- 무료 플랜으로 본 결과다. 유료(Power) 데이터가 다른지는 확인 안 함(5절)

---

## 1. 방법

- 문서는 토큰 없이 먼저 읽었다. Tiingo 문서 페이지는 자바스크립트 앱이라 HTML에 본문이 없어서, 문서 모듈 JS 번들(`src_app_api_documentation_documentation_module_ts-es2015.*.js`)과 가격표가 든 메인 번들에서 글을 뽑아 읽었다
- 엔드포인트
  - 메타: `GET https://api.tiingo.com/tiingo/daily/<ticker>` (응답: `ticker` `name` `exchangeCode` `description` `startDate` `endDate`)
  - EOD: `GET https://api.tiingo.com/tiingo/daily/<ticker>/prices?startDate=2025-10-27&endDate=2026-10-26`. 1년치(251봉)가 한 응답에 온다. 페이지 넘김 없음
- 부른 종목: 실험 15종목 전부(AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, XOM, KO, PFE, SPY, QQQ, TQQQ, SCHD) + NFLX(실험 종목 아님. 창 안에 10:1 분할이 있어 분할 확인 대조군)
- 요청 수: 토큰을 넣은 HTTPS 요청 33회, 모두 200
  - 종목마다 메타 1회 + EOD 1회 = 32회
  - 예비 1회: META 배당 조정이 5% 기준을 1건 넘어서, META EOD를 한 번 더 받아 조정 식을 확인(2-1)
  - 무료 한도 안: 시간당 50·하루 1,000·월 고유 종목 500(가격표). 지시 상한 40회 안
- 무료 플랜 한도(가격표 "Starter $0/month"): 월 고유 종목 500, 시간당 요청 50, 하루 요청 1,000, 월 대역폭 1 GB, 가격 이력 "30+ Years", 라이선스 "Internal Use Only". 문서: 분·초 단위 제한은 없고, 시간 한도는 매시간, 하루 한도는 자정 EST에 초기화
- 거래일 기준: 평일에서 NYSE 휴장일 10일(2025-11-27, 2025-12-25, 2026-01-01, 2026-01-19, 2026-02-16, 2026-04-03, 2026-05-25, 2026-06-19, 2026-07-03, 2026-09-07)을 뺀 251일. Marketstack 확인과 같은 달력
- 토큰: macOS 키체인 → 검사 프로세스 하나의 환경 변수로만. 요청 헤더 `Authorization: Token …`으로 보냈고 URL에는 넣지 않았다. 헤더·토큰·URL은 출력하지 않았다. 실패는 예외 클래스나 HTTP 상태만 찍는다. 리다이렉트는 따라가지 않았다(헤더가 다른 곳이나 http로 가지 않게). User-Agent는 직접 넣었다
- 스크립트는 레포에 넣지 않았다(검사 전용 임시 파일). 네트워크 없이 합성 봉으로 분석 자체 검사, 가짜 토큰(canary)으로 실패 경로 출력에 토큰이 없는지 확인한 뒤 실제 호출

---

## 2. 결과

### 2-1. 분할·배당 조정가

봉에 오는 필드(문서와 같음, 16종목 모든 봉이 같은 구성): `date` `open` `high` `low` `close` `volume` `adjOpen` `adjHigh` `adjLow` `adjClose` `adjVolume` `divCash` `splitFactor`

- `close`·`open`·`high`·`low`·`volume`은 원래 값, `adj…`는 분할·배당 조정값이다(문서: CRSP 방식, 분할과 배당 모두 조정)
- `divCash`는 배당락일 봉에 들어온다(문서: "date will be the exDate")

**분할** (`splitFactor` ≠ 1인 날)

| 종목 | 분할일 | 배수 | `close`가 배수만큼 뜀 | `adjClose` 연속 | 조정 비율 단계 = 1/배수 |
| --- | --- | --- | --- | --- | --- |
| NFLX | 2025-11-17 | 10 | 예 | 예 | 예 |
| TQQQ | 2025-11-20 | 2 | 예 | 예 | 예 |

- Marketstack과 달리 `close`가 분할 전 실제 거래 가격이다. 원래 종가와 조정 종가를 둘 다 받을 수 있다
- 나머지 14종목은 창 안에 분할 없음

**배당** (판정: r = `adjClose` ÷ `close`. 배당락일 t에서 1 − r(t−1) ÷ r(t)가 배당 ÷ `close`(t−1)과 5% 안이면 "맞음". Marketstack 확인과 같은 식·같은 기준)

| 종목 | 창 안 배당락일(`divCash` > 0) | 배당락일 조정 맞음 | 맞춤 비율(관측 ÷ 기대) 범위 |
| --- | --- | --- | --- |
| AAPL | 4 | 4/4 | 0.995 ~ 1.016 |
| MSFT | 4 | 4/4 | 1.001 ~ 1.016 |
| NVDA | 4 | 4/4 | 0.979 ~ 1.023 |
| GOOGL | 4 | 4/4 | 0.974 ~ 1.023 |
| META | 4 | 3/4 | 0.898 ~ 0.994 |
| JPM | 4 | 4/4 | 0.986 ~ 0.998 |
| XOM | 4 | 4/4 | 0.961 ~ 1.030 |
| KO | 4 | 4/4 | 0.997 ~ 1.014 |
| PFE | 4 | 4/4 | 1.000 ~ 1.014 |
| SPY | 4 | 4/4 | 0.990 ~ 1.015 |
| QQQ | 4 | 4/4 | 0.972 ~ 1.003 |
| TQQQ | 4 | 4/4 | 0.981 ~ 1.026 |
| SCHD | 4 | 4/4 | 0.986 ~ 1.006 |
| AMZN, TSLA, NFLX | 0 | 해당 없음 | — |

- 합계: 배당락일 52개 중 51개 맞음. 52개 모두 조정 비율이 배당락일 당일에 바뀐다(배당·분할 없는 날의 단계가 0이라 하루 앞뒤로 밀린 경우 없음)
- META 1건(2026-09-21, 맞춤 비율 0.898): 예비 요청으로 보니 META 4건 모두 "배당 ÷ 배당락일 당일 `close`"와 맞춤 비율 0.999. Tiingo는 기준 종가로 전날 종가가 아니라 배당락일 당일 종가를 쓰는 것으로 보인다(META로만 확인). 다른 종목의 0.96~1.03 흩어짐도 이 차이(그날 등락)로 설명된다. 두 식의 차이는 배당 수익률 × 그날 등락률 정도라 이번 창에서는 1bp 미만
- AMZN·TSLA(배당·분할 없음)는 1년 내내 `adjClose` = `close`. 맞는 동작
- 배당·분할 없는 날에 r이 0.01% 넘게 바뀐 경우: 16종목 모두 0번 (Marketstack TQQQ는 2번)
- 16종목 모두 마지막 봉에서 r = 1 (조정은 과거 쪽에만 걸린다)

### 2-2. HTTPS

- ✅ 무료 플랜 토큰으로 `https://api.tiingo.com` 요청 33회 모두 200
- 토큰은 `Authorization: Token …` 헤더로 보냈다(문서의 "2. Pass the token in your request headers" 방식). 요청 URL에 토큰이 없어서, URL이 로그에 찍혀도 토큰은 안 샌다. 문서 예시는 `?token=`(URL) 방식도 보여 주지만 어댑터는 헤더 방식을 쓰면 된다
- User-Agent는 직접 넣었다. 기본 User-Agent(`Python-urllib/…`)가 막히는지는 확인 안 함(요청 예산을 차단 탐침에 안 씀)

### 2-3. TQQQ·SCHD 포함

| 종목 | 거래소(메타 `exchangeCode`) | 종류·통화(종목 목록) | 봉 수 / 거래일 |
| --- | --- | --- | --- |
| AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, NFLX | NASDAQ | Stock · USD | 251 / 251 |
| JPM, XOM, KO, PFE | NYSE | Stock · USD | 251 / 251 |
| QQQ, TQQQ | NASDAQ | ETF · USD | 251 / 251 |
| SPY, SCHD | NYSE | ETF · USD | 251 / 251 |

- 메타 엔드포인트에는 통화 필드가 없다(문서와 같음). 통화·종류는 토큰 없이 받는 종목 목록(`supported_tickers.zip`)에서 봤다
- 종목 목록(2026-10-26 받음, 109,139행, 최신 `endDate` 2026-10-26)에 16종목 모두 한 행씩 있다. 같은 티커가 두 번 나오는 경우 없음(Marketstack 목록은 META·PFE가 두 번)
- SPY·SCHD는 실제로 NYSE Arca 상장인데 Tiingo는 `NYSE`로 적는다. 거래소 구분이 필요하면 이 점을 감안
- 메타 `endDate`가 16종목 모두 받은 마지막 봉 날짜(2026-10-26)와 같다

### 2-4. 1년 이력

- ✅ 무료 토큰으로 2025-10-27 ~ 2026-10-26 요청, 16종목 모두 251/251 거래일
- 빠진 날 0, 달력 밖 날(휴장일·주말) 0, 같은 날짜 중복 0
- 첫 봉 2025-10-27. 가격표 기준 무료도 "30+ Years". 메타 `startDate`로 보면 이력 시작은 1962(KO) ~ 2012(META). 1년보다 긴 구간은 받지 않았다

### 2-5. 장 마감 후 업데이트 시각

- 문서(2.1.1): "Most US Equity prices are available at 5:30 PM EST, however exchanges may send corrections until 8 PM EST. As we obtain corrections, we update prices throughout the evening."
- ⚠️ 실측은 상한만: 2026-10-26(월) 22:59 ET 실행 때 16종목 모두 2026-10-26 봉이 있었다. 처음 들어오는 시각은 안 쟀다(마감 뒤 여러 번 불러야 함)
- 우리 일정과 맞춰 보면
  - 아침 파이프라인(`.github/workflows/morning.yml`, 05:17 EDT / 04:17 EST)은 수정 마감(20:00 EST) 뒤 9시간 이상이라 전날 봉이 확정된 뒤 받는다
  - HANDOFF 하루 일정의 "16:30 장 마감 작업: 종가 → 등락률"은 문서상 도착 시각(17:30 EST)보다 이르다. 이 작업을 Tiingo EOD로 하면 그날 봉이 아직 없거나 수정 전일 수 있다

---

## 3. 응답 시간·요청 수

| 종목 | 메타 (ms) | EOD 1년치 (ms) | EOD 응답 크기 (KB, 1 KB = 1,000바이트) |
| --- | --- | --- | --- |
| AAPL | 801 | 234 | 64 |
| MSFT | 280 | 214 | 64 |
| NVDA | 288 | 243 | 65 |
| AMZN | 308 | 226 | 58 |
| GOOGL | 275 | 236 | 65 |
| META | 269 | 244 | 65 |
| TSLA | 271 | 223 | 58 |
| JPM | 265 | 234 | 65 |
| XOM | 194 | 249 | 64 |
| KO | 254 | 221 | 63 |
| PFE | 192 | 316 | 62 |
| SPY | 182 | 300 | 65 |
| QQQ | 212 | 342 | 65 |
| TQQQ | 188 | 308 | 63 |
| SCHD | 196 | 273 | 63 |
| NFLX | 210 | 294 | 57 |
| META (예비) | — | 259 | 65 |

- EOD 16회: 최소 214 · 중앙값 243.5 · 최대 342 ms (응답 본문 읽기까지 포함, 1년치 251봉)
- 메타 16회: 최소 182 · 중앙값 259.5 · 최대 801 ms (801은 첫 요청. 요청마다 새 연결이라 첫 연결 준비가 들어간 것으로 보임)
- 요청 수: 토큰을 넣은 요청 33회(성공 33). 받은 양 약 1.1 MB(EOD 17회 약 1.07 MB + 메타). 무료 월 1 GB 대비 작다
- 응답 헤더에 남은 한도를 알려 주는 값(이름에 limit·remain·quota·usage가 든 숫자 헤더)이 없다. 어댑터가 남은 한도를 헤더로 알 수 없으니 요청 수를 직접 세야 한다

---

## 4. 데이터 이상 (16종목 4,016봉)

| 항목 | 건수 |
| --- | --- |
| 가격 빈값·0 이하 (원래 OHLC) | 0 |
| 조정가 빈값·0 이하 (조정 OHLC) | 0 |
| OHLC 불일치 (원래 값) | 0 |
| OHLC 불일치 (조정값) | 0 |
| 거래량 빈값·음수 (`volume`·`adjVolume`) | 0 |
| 거래량 0 | 0 |
| 필드가 null인 봉 (13개 필드 전부) | 0 |
| 문서에 없는 필드·문서에 있는데 빠진 필드 | 0 |

- 빈값 = None·NaN·무한대. OHLC 불일치 = 종가 > 고가, 종가 < 저가, 고가 < 저가, 시가 > 고가, 시가 < 저가 중 하나. 기준은 Marketstack 확인과 같다

**공급원·표기 섞임**

- Tiingo 봉에는 거래소·통화 필드가 없다. 그래서 Marketstack처럼 봉마다 공급원을 직접 볼 수는 없다
- 종목 단위: 메타 `exchangeCode`가 16종목 모두 NASDAQ 또는 NYSE, 종목 목록상 통화는 모두 USD(2-3)
- 시계열 안 섞임을 간접으로 본 지표, 모두 0:
  - 한 종목 안에서 봉의 필드 구성이 다른 경우: 0 (16종목 모두 한 가지)
  - `adjClose`가 하루에 25% 넘게 바뀐 날(자릿수·통화가 다른 봉이 끼면 나타남): 0
  - 배당·분할 없이 조정 비율이 바뀐 날: 0
- 섞였다는 신호는 없다. 다만 봉에 공급원 표기가 없으니 "섞이지 않았다"를 직접 증명한 것은 아니다

---

## 5. 확인 안 한 것

- 유료(Power·Commercial) 플랜 데이터가 무료와 같은지. 같은 엔드포인트일 것으로 보지만 확인 안 함
- 장 마감 뒤 당일 봉이 처음 들어오는 시각(문서 17:30 EST, 실측 상한 약 7시간만)
- 지난 봉이 나중에 고쳐지는지(문서는 20:00 EST까지 수정. 같은 날짜를 다른 날 다시 받아 비교하지 않음)
- 배당 조정 기준 종가(배당락일 당일 종가)는 META로만 확인. 다른 12종목은 5% 기준 판정만
- 오류 응답 형식(401·404·429). 이번에 실패한 요청이 없어서 실제 형식을 못 봤다
- 기본 User-Agent 차단 여부
- 여러 종목을 한 요청에 받는 방법(EOD 엔드포인트는 경로에 종목 하나)
- 1년보다 긴 이력
- 2026-06 이후 임시 휴장일. 이번 창에서는 빠진 날·남는 날이 0이라 영향 없음

---

## 6. 약관 (상업 이용·표시 권한)

법률 검토 아님. 2026-10-26에 오케스트레이터(Claude)가 가격표·EOD 상품 페이지에서 읽은 것.

| 플랜 | 가격 | 대상 | 라이선스 |
| --- | --- | --- | --- |
| Free | $0/월 | 개인 | "Internal Use Only" |
| Power | $30/월 | 개인 | "Internal Use Only" |
| Commercial | $50/월 ($499/년) | 사업자 | "Internal Use Only" (내부 상업 이용) |
| EOD + IEX Redistribution | "$250/month for startups", "$500/month for enterprise" | 사업자 | 재배포(앱·웹 표시). "Contact sales to get started" |

- 내부 이용 정의(가격표): 본인 용도로만 쓰고 "may not display or share the data with another person or organization"
- 문서 1.1.6: 웹사이트·앱에서 데이터를 재배포하려면 sales@tiingo.com에 연락
- 판단: Paul만 보는 실험 대시보드 = Commercial($50) ✅. 앱 사용자 표시 = Redistribution 계약 필요. Marketstack과 달리 내부용·재배포가 가격표에서 분명히 나뉜다
- 확인 필요: Redistribution 가격은 EOD 상품 페이지의 표가 깨져 있어 어느 열 값인지 확실하지 않다. 출시 전 영업팀 서면 확인. 등락률·52주 고점 대비 같은 파생값 표시가 포함되는지도 같이 묻는다(HANDOFF 4장)

---

## 7. Marketstack과 비교

같은 날(2026-10-26), 같은 창(1년), 같은 판정 기준. 둘 다 무료 플랜. Marketstack은 8종목, Tiingo는 16종목을 봤다.

| 항목 | Marketstack | Tiingo |
| --- | --- | --- |
| 분할 조정 | ✅ `close`부터 분할 조정(원래 종가 없음), `adj_close` 연속 | ✅ `close`는 원래 가격, `adjClose` 연속 |
| 배당 조정 | ❌ 배당 종목 7개 중 TQQQ만 반영(3/4), 나머지 6개 0/4 | ✅ 배당 종목 13개, 배당락일 52개 모두 반영(5% 기준 51/52) |
| 1년 이력 | ✅ 251/251 (8종목) | ✅ 251/251 (16종목) |
| 당일 봉 (밤 실행) | 있음 (22:44 ET) | 있음 (22:59 ET) |
| 문서상 업데이트 시각 | 안내 없음 | 17:30 EST, 수정은 20:00 EST까지 |
| 원래 OHLC 빈값·0 이하 | 18 / 2,008봉 | 0 / 4,016봉 |
| OHLC 불일치 (원래 값) | 20 | 0 |
| 조정가 빈값 | 77 | 0 |
| 공급원·통화 섞임 | 있음: 한 종목 안에 ARS·MXN·`exchange_code` 없는 봉(767봉) | 신호 없음(봉에 공급원 필드는 없음) |
| 같은 티커 중복(종목 목록) | META·PFE | 없음 |
| EOD 1년치 응답 시간 (최소·중앙값·최대) | 482 · 642 · 793 ms | 214 · 243.5 · 342 ms |
| 키 전달 | URL 쿼리(`access_key`) | `Authorization` 헤더 |
| HTTPS | ✅ (기본 User-Agent는 Cloudflare가 막음) | ✅ (기본 User-Agent 미확인) |
| 남은 한도 응답 헤더 | 있음(`x-quota-remaining`) | 없음 |
| 무료 한도 | 월 100회 | 시간당 50·하루 1,000·월 고유 500종목·월 1 GB |
| 검토 대상 유료 플랜(HANDOFF) | Basic $9.99/월 | Power Internal Commercial $50/월 |

---

## 근거 링크 (2026-10-26 확인)

- EOD 문서: https://www.tiingo.com/documentation/end-of-day (2.1.1 업데이트 시각·CRSP 조정, 2.1.2 EOD 엔드포인트·필드, 2.1.3 메타 엔드포인트)
- 일반 문서: https://www.tiingo.com/documentation/general/overview (1.1.3 Usage Limits, 1.1.6 Permitted Use of Our Data)
- 연결 문서(토큰을 헤더로 보내는 방법): https://www.tiingo.com/documentation/general/connecting
- 가격표: https://www.tiingo.com/about/pricing
- 위 페이지는 자바스크립트 앱이라 실제 글은 번들에서 읽었다: https://apimedia.tiingo.com/dist/src_app_api_documentation_documentation_module_ts-es2015.f92c915a94800abc2f1b.js (문서), https://apimedia.tiingo.com/dist/main-es2015.eeb8b338ef82186074f9.js (가격표)
- 종목 목록: https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip
- CRSP 조정 방식(문서가 가리키는 곳): http://www.crsp.com/products/documentation/crsp-calculations
