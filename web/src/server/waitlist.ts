import "server-only";

import type { TapSlot } from "@/lib/card-view";

import type { VerifiedUserId } from "./auth";
import { db } from "./db";

// 웹 DB 쓰기 지점 둘 중 하나(#69, tests/guards.test.ts. 다른 하나는 my-stocks.ts). 잠긴 자리 탭 합계와 대기 등록 시각만 쓴다.
// 오류는 코드만 담아 throw한다(details에 유저 값이 있을 수 있다). 부르는 쪽(app/waitlist/route.ts)이 고정 이유 + 코드로 로그
const fail = (what: string, code: string) => new Error(`${what} failed: ${code || "unknown"}`, { cause: code || "unknown" });

/** 오늘(동부, DB가 정한다) 그 자리 합계 +1. 유저 값은 넘기지 않는다(인자는 { slot }뿐, 방침 "not linked to you") */
export async function countLockedSlotTap(slot: TapSlot): Promise<void> {
  const { error } = await db().rpc("count_locked_slot_tap", { slot });
  if (error) throw fail("locked_slot_tap write", error.code);
}

/** 처음이면 지금 시각, 이미 등록했으면 아무것도 안 한다(다시 눌러도 처음 시각). 이메일은 받지 않는다(출시 알림은 로그인 계정 이메일로 1회) */
export async function joinWaitlist(userId: VerifiedUserId): Promise<void> {
  const { error } = await db()
    .from("user_profile")
    .update({ waitlisted_at: new Date().toISOString() })
    .eq("user_id", userId)
    .is("waitlisted_at", null);
  if (error) throw fail("user_profile write", error.code);
}

/** /plus 설명 화면의 등록 상태. 요청마다 읽는다(공용 카드 캐시 밖). 프로필이 없으면 PGRST116으로 throw */
export async function isWaitlisted(userId: VerifiedUserId): Promise<boolean> {
  const { data, error } = await db().from("user_profile").select("waitlisted_at").eq("user_id", userId).single<{ waitlisted_at: string | null }>();
  if (error) throw fail("user_profile read", error.code);
  return data.waitlisted_at !== null;
}
