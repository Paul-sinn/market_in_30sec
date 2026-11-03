import "server-only";

/** 가격 표시 플래그(GLOSSARY PriceDisplay, #56). trim·소문자로 "on"일 때만 true. 없음·빈 값·그 밖은 false(닫힌 쪽).
 * 요청 때마다 읽는다(모듈 상수로 고정하지 않는다: 테스트 stubEnv, 런타임 env). 읽는 곳은 여기 하나 */
export function priceDisplayOn(): boolean {
  return process.env.PRICE_DISPLAY?.trim().toLowerCase() === "on";
}
