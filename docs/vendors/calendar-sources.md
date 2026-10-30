# 실적·배당 일정 출처 조사 (#21)

확인일: 2026-10-30 KST (2026-10-29 ET) · 확인: Claude · 근거: 공식 문서·약관·가격표만

- #21 첫 번째 완료 기준(출처 조사)과 두 번째 기준(시세 벤더 Tiingo 먼저 확인)만 다룬다. 코드·구독·키 발급은 안 했다
- 키를 넣은 API 호출 0회. 키 없이 부른 것은 Nasdaq Data Link의 표 메타데이터(스키마, 시세·일정 값 아님) 1회뿐이다. 받은 데이터는 없다
- 자바스크립트 앱이라 본문이 HTML에 없는 페이지(Tiingo, FMP)는 사이트가 내려 주는 JS 번들에서 글을 읽었다(`tiingo.md`와 같은 방법)
- 법률 검토 아님
- 표시: ✅ 충족 · ❌ 없음·불충족 · ⚠️ 일부만 확인·문서 불명확 · ⏳ 문의·서면 확인 필요

두 번째 줄이 필요한 값(HANDOFF 3-3): 실적일 + 확정/추정(`(est.)`) + 발표 시점(before open / after close), 배당락일 + 주당 금액(`Ex-dividend 12/21 · $0.70/share`), ETF 분배금.

---

## 0. 요약

| 후보 | 실적일 | 확정/추정 | 발표 시점 | 배당락일·금액 (미래) | ETF 분배금 | 내부 상업 이용 | 앱 표시 | 비용 (월) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Tiingo** | ❌ 없음 | — | — | ✅ 선언된 미래 배당 | ✅ | ✅ Commercial에 포함 (⚠️ 문서 충돌, 1절) | ⏳ Redistribution | 추가 $0 (Commercial $50) |
| Marketstack | ❌ 없음 | — | — | ⚠️ "history"만 언급 | ⚠️ | ✅ Basic | ⏳ | $9.99 (시세 탈락) |
| FMP | ✅ | ✅ `includeReportTimes` | ✅ `includeReportTimes` | ✅ 금액·날짜 | ⚠️ 미확인 | 개인 플랜 ❌. Build ✅ (⚠️ 캘린더 포함 불명확) | ⏳ Enterprise 계약 | Build $139 (연결제 $99) |
| Alpha Vantage | ✅ 3·6·12개월 | ⚠️ 문서에 열 없음 | ⚠️ 문서에 열 없음 | ✅ "future (declared)" | ⚠️ 미확인 | ⏳ 약관상 서면 합의 필요 | ⏳ | Premium $49.99부터 |
| EODHD | ✅ | ❌ 필드 없음 | ✅ `before_after_market` | ⚠️ 미래는 날짜만, 금액은 이력 API | ✅ | ⏳ 가격표 플랜은 개인 전용, 상업은 견적 | ⏳ 견적 | 견적 (개인 $59.99~$99.99) |
| Nasdaq Data Link (Zacks) | ✅ | ✅ `source_flag` | ✅ `time_of_day_code` | ❌ 없음 | ❌ | ⏳ | ⏳ | 비공개 (premium) |

- 결론: **Tiingo 하나로는 안 된다.** 배당·ETF 분배금은 Tiingo가 시세 플랜 안에서 주지만 실적 일정이 없다. 실적은 다른 출처가 필요하다
- 실적 후보 중 확정/추정과 발표 시점을 둘 다 공식 문서로 주는 곳: FMP, Zacks(Nasdaq Data Link). 공개 가격으로 내부 상업 이용이 되는 곳은 FMP Build뿐
- 추천·차선은 10절

---

## 1. Tiingo (시세 벤더, 먼저 확인)

**실적:** ❌ 실적 일정 엔드포인트가 없다. 문서 전체에서 "earnings"는 펀더멘털 FAQ("SEC 보고 후 24시간 안에 갱신") 1곳뿐. 펀더멘털 API는 지난 재무제표만 준다

**배당 (Stock, ETF, and Mutual Fund Dividends API, 문서 2.10):**
- 엔드포인트: 일괄 `GET /tiingo/corporate-actions/distributions?exDate=YYYY-MM-DD`, 종목별 `GET /tiingo/corporate-actions/<ticker>/distributions?startExDate=&endExDate=`
- 필드: `exDate` `paymentDate` `recordDate` `declarationDate` `distribution`(주당 총액) `distributionFrequency`
- "Use this endpoint to get past, present, and future dividends and distributions"(2.10.2). 상품 페이지: "covers distributions past, future, and present"
- FAQ: 하루 2~3번 갱신. "Ex-date and distribution amounts will never be null"(다른 날짜는 null 가능)
- 대상: 미국 주식·ETF·뮤추얼펀드 80,000+ (NYSE, NYSE Arca, NASDAQ 등). ETF 분배금 포함
- 날짜 형식: `"exDate":"2023-09-25T00:00:00.000Z"`, `"declarationDate":"2023-09-08T04:00:00.000Z"` (문서 예시). 날짜가 아니라 datetime 문자열로 온다(8절)
- `distributionFrequency` 코드: `w` `bm` `m` `tm` `q` `sa` `a` `ir`(비정기) `f`(마지막) `u`(미지정) `c`(취소)
- 변경 이력: 2023-09 신규, 2025-01까지 "Beta Product", 2026-03·2026-05 "upcoming distributions" 커버리지 개선

**권한·비용:**
- ✅ 배당 상품 페이지의 가격 요약이 Free·Power·Commercial(Internal Use Only)과 EOD + IEX Redistribution($250/월 스타트업)을 그대로 보여 준다. 개요(2.10.1): "included for all customers with the End-of-Day endpoint entitlement"
- ⚠️ 충돌: 같은 문서 머리말은 "currently available to Beta-enabled customers and enterprise customers ... please E-mail support@tiingo.com". 어느 쪽이 지금 맞는지 확인 필요(사용자 조치 1)
- 키 전달은 시세와 같은 `Authorization` 헤더

근거 (2026-10-30 확인):
- 문서: https://www.tiingo.com/documentation/corporate-actions/dividends (본문은 https://apimedia.tiingo.com/dist/src_app_api_documentation_documentation_module_ts-es2015.a8049f288612cb7024f8.js)
- 상품·가격 요약: https://www.tiingo.com/products/corporate-actions/stock-etf-mutual-fund-dividend-api (본문은 https://apimedia.tiingo.com/dist/src_app_api_products_products_module_ts-es2015.21212396f983248fe5d1.js)
- 가격표: https://www.tiingo.com/about/pricing

---

## 2. Marketstack

- 실적: ❌ v2 스펙 엔드포인트 48개 중 실적 일정 없음. 가격표에도 없음
- 배당: `GET /v2/dividends?symbols=`, `GET /v2/tickers/{symbol}/dividends`. 필드 `date`(배당락일) `dividend` `payment_date` `record_date` `declaration_date` `distr_freq`. 설명은 "dividend payment history", "historical dividend distributions". ⚠️ 미래 배당 언급 없음. NYSE ARCA 포함 문구는 있음
- 필드 구성이 Tiingo와 같고, 가격표 FAQ는 미국 데이터가 "licensed and sourced from Tiingo"라고 한다. Tiingo를 직접 쓰는 것보다 나을 이유가 없다
- 비용·약관: 모든 플랜에 "Splits & Dividends". Basic $9.99부터 "Commercial Use". 표시 권한은 `marketstack.md` 6절과 같이 ⏳
- 시세 확인(#18)에서 이미 탈락

근거 (2026-10-30 확인):
- v2 스펙: https://api.swaggerhub.com/apis/apilayer-863/MarketstackAPIv2/2.0.0/swagger.json
- 가격표: https://marketstack.com/pricing

---

## 3. Financial Modeling Prep (FMP)

**실적:**
- `GET /stable/earnings-calendar?from=&to=&includeReportTimes=` (한 번에 최대 90일·4,000건), 종목별 `GET /stable/earnings?symbol=&includeReportTimes=`
- 기본 필드(문서 예시): `symbol` `date` `epsActual` `epsEstimated` `revenueActual` `revenueEstimated` `lastUpdated`. 기본 응답에는 확정/추정·발표 시점이 없다
- ✅ `includeReportTimes=true`면 "period of report, confirmation status, and estimated report time"이 붙는다(FMP 공지, 2026-08-24). "Confirmation status: Whether the calendar entry is marked as confirmed or estimated", "Estimated report time: The expected reporting window relative to market hours"
- ⚠️ 붙는 필드의 이름·값은 공식 문서에 없다(문서 예시 응답이 기본 필드만). 공지도 "some calendar entries may not include a usable timing value"

**배당:** `GET /stable/dividends-calendar?from=&to=` (최대 90일), 종목별 `GET /stable/dividends?symbol=`. 필드 `date` `recordDate` `paymentDate` `declarationDate` `adjDividend` `dividend` `yield` `frequency`. 문서 예시에 `"declarationDate":""`(빈 문자열)도 있다. ETF 포함 여부는 문서에 없음 ⚠️

**권한·비용:**
- 약관 2.2.1 Personal Use: 개인·비사업 목적만. "Commercial Use"에 "data-driven decision-making" 등 상업 활동 지원 분석까지 넣는다. 개인 플랜(Starter $29, Premium $69, Ultimate $139 월결제)은 실험에도 못 쓴다 ❌
- 상업 플랜(가격표 JS 번들의 플랜 정의):
  - Build: "Commercial Internal", $139/월 (연결제 $99/월), "Internal Commercial Use". ⚠️ 포함 데이터 목록에 "Market Calendars"가 없다
  - Grow: "Commercial Internal" 계열, $999/월, 포함 목록에 "Market Calendars" 있음
  - Enterprise: "Display and Redistribution", 가격 문의
- 약관 2.2.2·가격표: 앱·웹 표시는 "Data Display and Licensing Agreement" 별도 계약 필요
- 키 전달: "Authorization can be done using either request headers or URL query parameters" → 헤더로 보낼 수 있다

근거 (2026-10-30 확인):
- 실적 캘린더 문서: https://site.financialmodelingprep.com/developer/docs/stable/earnings-calendar
- 배당 캘린더 문서: https://site.financialmodelingprep.com/developer/docs/stable/dividends-calendar
- `includeReportTimes` 공지: https://site.financialmodelingprep.com/insights/platform/fmp-earnings-calendar-update-more-detail-on-report-timing-and-period
- 가격표: https://site.financialmodelingprep.com/pricing-plans (상업 플랜 정의는 https://site.financialmodelingprep.com/_next/static/chunks/8599-475e7196916c7226.js)
- 약관: https://site.financialmodelingprep.com/terms-of-service (Last updated: August 1, 2023)

---

## 4. Alpha Vantage

- 실적: `function=EARNINGS_CALENDAR&symbol=&horizon=3month|6month|12month`, CSV만. ⚠️ 문서에 응답 열 목록이 없어 확정/추정·발표 시점 여부를 문서로 확인 못 함
- 배당: `function=DIVIDENDS&symbol=` "historical and future (declared) dividend distributions" ✅. ETF 지원은 문서에 없음 ⚠️
- 약관 2(a): 기본 라이선스는 "personal, non-commercial use". 회사로 쓰거나 남이 정보에 접근하게 하면 상업 이용이고 "please contact us at: premium@alphavantage.co". Premium($49.99/월~, 75회/분)이 상업 이용 허락인지 약관에 없다 ⏳
- 키 전달: URL 쿼리(`apikey`)만 문서화

근거 (2026-10-30 확인):
- 문서: https://www.alphavantage.co/documentation/ (Earnings Calendar, Corporate Action - Dividends)
- 가격: https://www.alphavantage.co/premium/
- 약관(PDF): https://www.alphavantage.co/terms_of_service/

---

## 5. EODHD

- 실적: `GET /api/calendar/earnings?symbols=AAPL.US&from=&to=`. 필드 `code` `report_date` `date`(회계기간 끝) `before_after_market`(`BeforeMarket`·`AfterMarket`, 모르면 null) `currency` `actual` `estimate` `difference` `percent`
  - ✅ 발표 시점. ❌ 확정/추정 구분 필드 없음
  - 문서 주의: `from`·`to` 없이 `symbols`만 주면 오늘~7일만 본다
- 배당: `/api/calendar/dividends`는 미래 날짜를 주지만 "a date and a symbol, nothing else" — 금액 없음. 금액·선언일·지급일은 `/api/div/{SYMBOL}`인데 "this API is history, not schedule" ⚠️ 미래 배당 금액을 받을 수 있는지 불명확
- 가격표(개인): Fundamentals $59.99는 캘린더 ✅·배당 ❌, ALL-IN-ONE $99.99는 둘 다 ✅. ETF 배당 "ETF Global" 포함
- 약관: 가격표 플랜은 "intended for personal use only". 개인 사용자는 "displaying" 금지. 상업은 견적(영업일 3일 안 온보딩) ⏳
- 키 전달: URL 쿼리(`api_token`)

근거 (2026-10-30 확인):
- 캘린더 문서: https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits
- 배당 문서: https://eodhd.com/financial-apis/api-splits-dividends
- 가격표: https://eodhd.com/pricing
- 약관: https://eodhd.com/financial-apis/terms-conditions , 상업 이용: https://eodhd.com/financial-apis/commercial-vs-personal-license-use

---

## 6. Nasdaq Data Link — Zacks Earnings Announcements (`ZACKS/EA`)

- 실적 전용. 7,000+ 회사의 다음 분기·다음 연도 예상 발표일(`exp_rpt_date_qr1` 등)
- ✅ `source_flag`: 1 = 회사 확정, 2 = 추정(다음 분기 날짜에만). ✅ `time_of_day_code`: 1 장 마감 후, 2 장 시작 전, 3 장중, 4 모름
- 배당·ETF 없음 ❌. 표 메타데이터는 `premium: true`, 갱신 "CONTINUOUS". 가격·라이선스 등급은 공개 페이지에 없다 ⏳
- ⚠️ 상품 페이지가 자바스크립트 앱이라 필드 설명은 검색 색인에 잡힌 상품 페이지 글로 확인했다. 열 목록은 키 없이 안 나온다

근거 (2026-10-30 확인):
- 상품 페이지: https://data.nasdaq.com/databases/ZEA
- 표 메타데이터: https://data.nasdaq.com/api/v3/datatables/ZACKS/EA/metadata.json

---

## 7. 실험 15종목 커버

| 구분 | 종목 | 필요한 일정 | 문서 기준 |
| --- | --- | --- | --- |
| 배당 주는 주식 | AAPL, MSFT, NVDA, GOOGL, META, JPM, XOM, KO, PFE | 실적 + 배당 | 모든 후보가 미국 상장 주식 지원 |
| 배당 없는 주식 | AMZN, TSLA | 실적 (배당은 빈 목록 = 확인함·없음) | 같음 |
| ETF | SPY, QQQ, TQQQ, SCHD | 분배금만 (실적 해당 없음) | Tiingo ✅, EODHD ✅, FMP·Alpha Vantage ⚠️, Zacks ❌ |

- Tiingo 종목 목록에 15종목 모두 있다(`tiingo.md` 2-3). 배당 엔드포인트가 종목마다 실제로 값을 주는지는 키 호출을 안 해서 미확인
- 다른 후보도 문서 수준만 봤다. 종목별 확인은 구독 전 성능 검사(사용자 조치 3)

---

## 8. 어댑터 구현에 영향 주는 것

- Tiingo 날짜는 datetime 문자열이다. #21 추가 기준("datetime이면 그 종목 `Update delayed`")에 걸리지 않게, 어댑터 경계에서 날짜로 바꾸는 규칙을 정해야 한다(`exDate`는 자정 UTC, `declarationDate`는 시각 포함)
- `distributionFrequency` = `c`(취소)인 행은 일정에서 빼야 한다. 모르는 코드는 추가 기준대로 지연
- 실적 출처 없이 배당만 붙이면 "가장 가까운 일정 하나"가 틀릴 수 있다(앞에 실적이 있는데 배당을 보여 줌). 실적 출처가 없는 동안 주식은 줄 전체를 `Not covered yet`으로 두는 게 안전. ETF는 실적이 해당 없으니 배당만으로 판단
- 발표 시점이 null이거나 확정 여부가 없는 출처(EODHD)는 문구 규칙 결정이 필요: 시점 생략 허용 여부, 확정 여부 모르면 모두 `(est.)`
- 키 전달: Tiingo·FMP는 헤더 가능. Alpha Vantage·EODHD는 URL 쿼리뿐이라 요청 URL을 로그에 남기지 않는 처리가 꼭 필요

---

## 9. 확인 안 한 것

- 키를 넣은 실제 응답: 필드 이름·값, 15종목 커버, 응답 시간, 오류 형식(모두 구독 전 성능 검사 대상)
- Tiingo 배당 API가 지금 Commercial 플랜에서 바로 열리는지(1절 문서 충돌)
- FMP `includeReportTimes`가 붙이는 필드 이름·값, Build 플랜에 실적 캘린더가 들어가는지
- ETF 분배금이 배당락일 며칠 전에 금액과 함께 들어오는지(선언 시점은 ETF마다 다름)
- Alpha Vantage 실적 CSV 열, Zacks 가격, EODHD 상업 견적
- 그 밖의 후보(Finnhub, Benzinga 등). Benzinga는 HANDOFF 4장대로 답장 없음 가정

---

## 10. 추천

**추천: 배당 = Tiingo Dividend API + 실적 = FMP Build**
- 배당·ETF 분배금은 이미 고른 시세 벤더 Tiingo의 플랜 안에 있다(추가 비용 0, 키·재시도·약관 하나)
- 실적에서 확정/추정과 발표 시점을 둘 다 공식으로 주고, 공개 가격으로 내부 상업 이용이 되는 곳은 FMP Build($139/월, 연결제 $99/월)뿐
- 조건: FMP가 Build에 `earnings-calendar`·`includeReportTimes`가 들어간다고 서면 확인. 안 되면 차선으로

**차선: 배당 = Tiingo + 실적 = EODHD 상업 라이선스(견적)**
- 발표 시점(`before_after_market`)은 문서로 확실하다. 확정/추정 필드가 없어 실적일은 모두 `(est.)`로 표시해야 한다(덜 말하는 쪽이라 안전)

---

## 사용자 조치 필요

1. **Tiingo 문의** (support@tiingo.com): Dividend API가 Commercial($50) 플랜에서 바로 쓰이는지, Redistribution 계약에 배당 표시가 들어가는지 서면 확인
2. **FMP 문의**: Build 플랜에 실적 캘린더(`includeReportTimes` 포함)가 들어가는지, 앱 표시용 Data Display and Licensing Agreement 조건·가격
3. **구독 전 성능 검사 허락·키** (HANDOFF 4장 예외: 결과 수치만 기록, 받은 데이터는 버림)
   - Tiingo: 기존 무료 토큰으로 배당 엔드포인트 15종목 확인
   - FMP: 무료(Basic) 키 발급 → `includeReportTimes` 필드 이름·15종목 커버만 확인
4. **구독**: 1·2 답이 맞으면 FMP Build 월결제. Tiingo는 #18 결정대로 Commercial
5. (차선으로 갈 때) **EODHD 상업 견적 요청** (sales@eodhistoricaldata.com)
