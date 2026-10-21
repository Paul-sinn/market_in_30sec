/**
 * 웹 고정 문구표. DB에 문구가 없는 화면 상태만 여기에 둔다(줄 문구는 DB의 *_text 그대로).
 * GLOSSARY·HANDOFF 3-3에 없는 문구를 새로 넣으면 copy-reviewer 검수를 받는다.
 */

// HANDOFF 3-3 데이터 상태 문구 (backend m30/pipeline/lines.py와 같은 값)
export const UPDATE_DELAYED = "Update delayed"; // 등락률 지연, 아직 없는 줄(축소판의 첫 번째 줄)
export const NOT_COVERED = "Not covered yet"; // 등락률 미지원

// HANDOFF 3-3
export const NOT_INVESTMENT_ADVICE = "Not investment advice";
export const CHECKED_PREFIX = "Checked"; // 카드 하단 "Checked 7:30 AM ET · SEC filings"

// 새 문구 (copy-reviewer 검수 대상. APP_NAME·NO_CARDS는 #24 1차 검수 통과)
export const APP_NAME = "market_in_30sec"; // 작업 이름. 앱 이름은 HANDOFF Q8 미정
export const NO_CARDS = "No cards yet"; // DB에 카드가 하나도 없음
export const LAST_CLOSE = "Last close"; // 등락률 아래 기준 라벨(직전 거래일 종가 기준). 날짜는 쓰지 않는다(휴장일 달력 #16 전)
export const LOAD_FAILED = "Cards could not be loaded"; // DB 읽기 실패(app/error.tsx). 에러 내용은 그리지 않는다
export const TRY_AGAIN = "Try again"; // 위 화면의 다시 시도 버튼
