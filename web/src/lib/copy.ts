/**
 * 웹 고정 문구표. DB에 문구가 없는 화면 상태만 여기에 둔다(줄 문구는 DB의 *_text 그대로).
 * GLOSSARY·HANDOFF 3-3에 없는 문구를 새로 넣으면 copy-reviewer 검수를 받는다.
 */

// HANDOFF 3-3 데이터 상태 문구 (backend m30/pipeline/lines.py와 같은 값)
export const UPDATE_DELAYED = "Update delayed"; // 등락률 지연, 아직 없는 줄(축소판의 첫 번째 줄)
export const NOT_COVERED = "Not covered yet"; // 등락률 미지원(세 번째 줄 미지원은 DB 문구 그대로)

// 카드 헤더(#63, GLOSSARY CardHeader, copy-reviewer 검수 대상). 지연·미지원은 위 UPDATE_DELAYED·NOT_COVERED를 쓴다
export const NEW_FILINGS = (n: number) => `${n} new filing${n === 1 ? "" : "s"}`; // 첫 번째 줄 확인함·있음, n = 1등 + +N more
export const QUIET_DAY = "Quiet day"; // 조용한 날 = 첫 번째 줄 확인함·없음
// 알아두기(#66, GLOSSARY QuietFact, copy-reviewer 검수 대상). 사실 문장은 DB quiet_fact.text 그대로, 꼬리표는 backend card.toml source_tags와 같은 값
export const QUIET_FACT = (fact: string) => `Did you know: ${fact} (Annual report)`;

// 무료 범위의 세 번째 줄(연관 소식) 자리(#9·#67, HANDOFF 3-3). 서버는 건수만 보내고 글자는 이 문구뿐이다.
// count 없음 = 0건·지연 둘 다(무료에게 지연 여부도 Plus 정보). 단수형은 copy-reviewer 검수 대상
export const RELATED_IN_PLUS = (count?: number) => (count ? `${count} related update${count === 1 ? "" : "s"} in Plus` : "Related updates in Plus");

// HANDOFF 3-3
export const NOT_INVESTMENT_ADVICE = "Not investment advice";
export const CHECKED_PREFIX = "Checked"; // 카드 하단 "Checked 7:30 AM ET · SEC filings"

// 새 문구 (copy-reviewer 검수 대상. APP_NAME·NO_CARDS는 #24 1차 검수 통과)
export const APP_NAME = "market_in_30sec"; // 작업 이름. 앱 이름은 HANDOFF Q8 미정
export const NO_CARDS = "No cards yet"; // DB에 카드가 하나도 없음
export const PREV_CLOSE = "prev close"; // 등락률 옆 기준 라벨(#27 사용자 시안). 이제는 종가 날짜가 없는 카드(#16 전)에만
export const DAY_CLOSE = (day: string) => `${day} close`; // 종가 날짜 라벨 "Thu 10/15 close"(#16, copy-reviewer 검수 대상)
export const LOAD_FAILED = "Cards could not be loaded"; // DB 읽기 실패(app/cards/error.tsx). 에러 내용은 그리지 않는다
export const TRY_AGAIN = "Try again"; // 위 화면의 다시 시도 버튼
export const OPEN_CARDS = "Open the latest cards"; // 랜딩 → /cards 버튼(#27, 시안의 앱 다운로드 버튼 자리). 휴장일엔 직전 거래일 카드라 "today's"를 쓰지 않는다
export const AUTH_REQUIRED = "Authentication required"; // 배포 보호 401 본문(브라우저 로그인 창을 취소하면 보인다, #25)
export const TOO_MANY_REQUESTS = "Too many requests. Try again in a minute."; // /cards 요청 제한 429 본문(#62, copy-reviewer 검수 대상)

// 로그인(#37, copy-reviewer 검수 대상)
export const SIGN_IN = "Sign in to pick your stocks"; // 로그인 전 /cards 버튼(스펙 #36 스토리 17)
export const SIGN_OUT = "Sign out"; // 로그인됨 /cards 버튼
export const SIGN_IN_FAILED = "Sign-in could not be completed"; // 설정 없음·Google 꺼짐·취소·교환 실패·프로필 실패를 한 문구로(LOAD_FAILED와 같은 형식)

// 시장 한눈에(#11, copy-reviewer 검수 대상). 줄 문구는 DB market_glance의 *_text 그대로
export const MARKET_AT_A_GLANCE = "Market at a glance"; // 대시보드 거래일 제목 아래 블록 제목

// 내 종목(#38). 화면 제목·라벨은 스펙 #36, 업셀·카드 없음은 HANDOFF 3-2 그대로. 나머지는 새 문구(copy-reviewer 검수 대상)
export const MY_STOCKS = "My stocks";
export const BROWSE = "Browse";
export const SUMMARY_TOMORROW = "Summary arrives tomorrow morning"; // 오늘 카드가 없는 내 종목 자리(HANDOFF 3-2)
export const PICK_STOCKS = "Pick your stocks"; // 고르기 목록 펼침(내 종목 0개면 열린 채로)
export const ADD = "Add"; // 화면 읽기 프로그램에는 뒤에 티커가 붙는다("Add AAPL")
export const REMOVE = "Remove"; // 같음("Remove AAPL")
export const SWAPS_LEFT = (n: number) => `Swaps left today: ${n}`; // 무료만. 프로필 타임존 자정 기준
/** POST /my-stocks 결과 코드(/cards?my_stock=…) → 문구. 여기 없는 코드는 문구를 그리지 않는다 */
export const MY_STOCK_NOTICE = {
  free_swap_limit: "Free plan can swap stocks 3 times a day. Swaps reset tomorrow.", // HANDOFF 3-2. 리셋 = 프로필 타임존 자정(user_local_date)
  free_my_stock_limit: "Free plan can pick 3 stocks. Remove one to add another.",
  failed: "My stocks could not be updated", // 그 밖의 실패(LOAD_FAILED·SIGN_IN_FAILED와 같은 형식)
} as const;

// 고르기 검색(#58, copy-reviewer 검수 대상)
export const SEARCH_STOCKS = "Search by ticker or company"; // 검색칸 라벨(보이는 라벨)
export const SEARCH = "Search"; // 검색 버튼
export const NO_MATCHES = "No matching stocks"; // 검색어가 있는데 결과 0개(이미 내 종목인 것만 맞을 때도)
export const MORE_MATCHES = "Type more to narrow the list"; // 결과가 SEARCH_MAX(20)에서 잘림

// 지난 카드(#68, copy-reviewer 검수 대상). 뒤로 링크는 MY_STOCKS, 카드 없는 날은 SUMMARY_TOMORROW·NO_CARDS를 그대로 쓴다
export const PAST_CARDS = "Past cards"; // 내 종목 카드 아래 링크(화면 읽기 프로그램에는 티커까지)·지난 카드 화면 라벨
export const PAST_CARDS_IN_PLUS = "Past 90 days in Plus"; // 무료: 오늘 카드 아래 잠금 안내(누르는 곳 없음, 결제 연결 없음). "… in Plus" 잠금 문구 형식

// 잠긴 자리·Notify me(#69, copy-reviewer 검수 대상). UI 라벨이라 2인칭 허용. 원인·기사 기반 이유("Why it moved")·결제·구매를 약속하지 않는다(약관 "Plus is not for sale")
export const LOCKED_SLOT = {
  earnings_summary: "Earnings summary in Plus", // 카드의 잠긴 자리(실적 있는 날). "… in Plus" 잠금 문구 형식
  big_holders: "Insider and big holder filings in Plus", // 그 밖의 날. "moves"는 가격 움직임으로 읽혀 filings
} as const;
export const ABOUT_PLUS = "About Plus"; // /plus 설명 화면 제목(잠긴 자리·세 번째 줄 잠금 모두 이 화면)
export const PLUS_PLANNED =
  "Plus is not available yet. Planned: any number of covered stocks, earnings summaries, insider and big holder filings, related company filings, and past cards from the last 90 days. All from SEC filings."; // 설명(모든 자리 같음). 목록은 HANDOFF Plus 정의(판매 전 계획)
export const NOTIFY_ME_NOTE = "Tap Notify me and we'll email your sign-in address once when Plus launches."; // 개인정보처리방침 문장과 같게(U1 when)
export const NOTIFY_ME = "Notify me"; // 대기 등록 버튼(GLOSSARY Waitlist)
export const ON_THE_LIST = "You're on the list"; // 이미 등록함
export const SIGN_IN_TO_NOTIFY = "Sign in to use Notify me"; // 로그인 전 버튼(POST /auth/sign-in)
export const NOTIFY_FAILED = "Notify me could not be saved"; // 등록 저장 실패(LOAD_FAILED와 같은 형식)

// 초보 친화 화면(#93, copy-reviewer 검수 대상)
/** 카드 줄 위 작은 라벨(첫 번째·두 번째·세 번째 줄). 랜딩 "The card" 설명의 말과 같다. 줄 문구(DB)는 그대로, 라벨만 웹 고정 문구 */
export const LINE_LABELS = ["What happened", "What's next", "Related"] as const;
/** 카드 대시보드 거래일 제목 아래 한 줄 설명(SEC 공시가 뭔지) */
export const DASHBOARD_INTRO =
  "Companies file reports with the SEC, a U.S. government agency, when certain big events happen. Each trading day, we read those filings and sum up each stock and ETF we cover in a few short lines.";
/** 랜딩 샘플 카드 아래(지어낸 예시가 아니라 그날 실제 카드). day = formatTradingDay 값("Fri, Nov 6, 2026") */
export const REAL_CARDS_FROM = (day: string) => `Real cards from ${day}.`;
