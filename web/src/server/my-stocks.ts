import "server-only";

import type { VerifiedUserId } from "./auth";
import { db } from "./db";

// 웹의 유일한 DB 쓰기 지점(#37, tests/guards.test.ts). 개수·교체·타임존 규칙은 DB 트리거가 지킨다(ADR-0004)
export const DEFAULT_TIMEZONE = "America/New_York";

/** 없으면 무료 + timezone으로 만들고, 있으면 아무것도 바꾸지 않는다(insert … on conflict do nothing).
 *  timezone이 비었거나 DB가 timezone_name으로 거절하면 DEFAULT_TIMEZONE으로 1회. 그 밖의 오류는 코드만 담아 throw */
export async function ensureProfile(userId: VerifiedUserId, timezone: string): Promise<void> {
  const insert = (tz: string) =>
    db().from("user_profile").upsert({ user_id: userId, plan: "free", timezone: tz }, { onConflict: "user_id", ignoreDuplicates: true });
  let { error } = await insert(timezone || DEFAULT_TIMEZONE);
  // 트리거가 충돌 검사보다 먼저 돌아 기존 유저도 여기로 온다. 다시 시도하면 do nothing이라 기존 프로필은 그대로
  if (error?.code === "23514" && error.message === "timezone_name") ({ error } = await insert(DEFAULT_TIMEZONE));
  if (error) throw new Error(`user_profile write failed: ${error.code}`); // details(유저 값)는 넣지 않는다
}
