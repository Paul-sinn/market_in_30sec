/**
 * 웹 고정 문구표. DB에 문구가 없는 화면 상태만 여기에 둔다(줄 문구는 DB의 *_text 그대로).
 * GLOSSARY·HANDOFF 3-3에 없는 문구를 새로 넣으면 copy-reviewer 검수를 받는다.
 */

// HANDOFF 3-3 데이터 상태 문구 (backend m30/pipeline/lines.py와 같은 값)
export const UPDATE_DELAYED = "Update delayed"; // 등락률 지연, 아직 없는 줄(축소판의 첫 번째 줄)
export const NOT_COVERED = "Not covered yet"; // 등락률 미지원

// HANDOFF 3-2·GLOSSARY: 무료 범위의 세 번째 줄 자리(#9). 서버는 잠금 상태만 보내고 글자는 이 문구뿐이다
export const PRICE_FACTS_IN_PLUS = "Price facts in Plus";

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
  free_swap_limit: "Free plan can swap stocks 3 times a day. Plus has no limit.", // HANDOFF 3-2
  free_my_stock_limit: "Free plan can pick 3 stocks. Remove one to add another.",
  failed: "My stocks could not be updated", // 그 밖의 실패(LOAD_FAILED·SIGN_IN_FAILED와 같은 형식)
} as const;
