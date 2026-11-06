import { NextResponse, type NextRequest } from "next/server";

import { TAP_SLOTS, type TapSlot } from "@/lib/card-view";
import { getVerifiedUserId } from "@/server/auth";
import { countLockedSlotTap, joinWaitlist } from "@/server/waitlist";

const isTapSlot = (v: unknown): v is TapSlot => (TAP_SLOTS as readonly unknown[]).includes(v);
const code = (e: unknown) => (e instanceof Error && typeof e.cause === "string" ? e.cause : "unknown");

/** 잠긴 자리 탭·Notify me(POST만, #69: GET은 405라 프리페치·크롤러가 세지 않는다). 폼 필드 intent = tap(slot) | notify.
 *  같은 출처 Origin만 받는다(교차 사이트 POST는 아무것도 쓰지 않음). 유저는 세션으로만 안다(본문의 유저 id는 읽지 않는다).
 *  돌아갈 곳은 고정 경로뿐: 늘 /plus, 등록 저장 실패만 /plus?notify=failed. 로그는 고정 이유 + DB 코드만(자리·유저·IP 값 없음) */
export async function POST(request: NextRequest) {
  const plus = (query = "") => NextResponse.redirect(new URL(`/plus${query}`, request.url), 303);
  if (request.headers.get("origin") !== request.nextUrl.origin) {
    console.warn("waitlist: reason=bad_origin"); // 값은 남기지 않는다. 운영에서 같은 출처 탭이 여기로 오면 출처 비교 설정 문제
    return plus();
  }
  const form = await request.formData().catch(() => null);
  const intent = form?.get("intent");

  if (intent === "tap") {
    const slot = form?.get("slot");
    // 탭은 로그인과 무관하게 센다. 저장이 실패해도 설명 화면은 연다(가용성 열린 쪽, HANDOFF 3-10)
    if (isTapSlot(slot)) await countLockedSlotTap(slot).catch((e) => console.warn(`waitlist: reason=tap_failed code=${code(e)}`));
    return plus();
  }
  if (intent === "notify") {
    const userId = await getVerifiedUserId();
    if (!userId) return plus(); // 로그인 전·만료 → 설명 화면의 로그인 안내
    try {
      await joinWaitlist(userId);
      return plus();
    } catch (e) {
      console.warn(`waitlist: reason=notify_failed code=${code(e)}`);
      return plus("?notify=failed"); // 등록됨을 보이지 않는다(내용 닫힌 쪽)
    }
  }
  return plus();
}
