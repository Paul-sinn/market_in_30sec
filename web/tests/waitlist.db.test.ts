/**
 * 잠긴 자리 탭 합계·대기 등록(#69): 웹 쓰기 모듈 waitlist.ts를 로컬 Supabase에서 돌린다. 원격 금지.
 * 탭 합계 행은 service_role이 지울 수 없다(의도된 스키마, 일별 합계만 남긴다): 실행 전후 차이로 본다.
 * backend pytest가 public 테이블을 비울 때 같이 지워진다. 유저는 로컬 Auth admin으로 만들고 끝나면 지운다(프로필 cascade).
 */
import { afterAll, expect, test } from "vitest";

import type { VerifiedUserId } from "@/server/auth";
import { ensureProfile } from "@/server/my-stocks";
import { countLockedSlotTap, isWaitlisted, joinWaitlist } from "@/server/waitlist";

import { admin, createTestUser, deleteTestUsers } from "./local-supabase";

const created: string[] = [];
afterAll(() => deleteTestUsers(created));

const todayET = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date()); // "YYYY-MM-DD"

/** 오늘(동부) 자리별 합계. 행이 없으면 0 */
async function taps(): Promise<Record<string, number>> {
  const { data, error } = await admin.from("locked_slot_tap").select("slot, taps").eq("day", todayET());
  if (error) throw new Error(`locked_slot_tap read failed: ${error.code}`);
  return Object.fromEntries(["earnings_summary", "big_holders", "related_lock"].map((s) => [s, data.find((r) => r.slot === s)?.taps ?? 0]));
}

async function user(): Promise<VerifiedUserId> {
  const id = (await createTestUser()).id as VerifiedUserId; // 테스트에서만: 운영에서는 getVerifiedUserId만 만든다
  created.push(id);
  await ensureProfile(id, "America/New_York");
  return id;
}

test("탭: 오늘(동부) 그 자리 합계가 누를 때마다 1씩 오르고, 다른 자리는 따로 센다. 행은 날짜·자리·합계뿐", async () => {
  const before = await taps();
  await countLockedSlotTap("big_holders");
  await countLockedSlotTap("big_holders");
  await countLockedSlotTap("related_lock");
  const after = await taps();
  expect({
    earnings_summary: after.earnings_summary - before.earnings_summary,
    big_holders: after.big_holders - before.big_holders,
    related_lock: after.related_lock - before.related_lock,
  }).toEqual({ earnings_summary: 0, big_holders: 2, related_lock: 1 });
  const { data, error } = await admin.from("locked_slot_tap").select("*").eq("day", todayET()).eq("slot", "big_holders");
  expect(error).toBeNull();
  expect(data).toHaveLength(1); // 하루 한 행
  expect(Object.keys(data![0]).sort()).toEqual(["day", "slot", "taps"]);
});

test("탭: DB가 모르는 자리는 오류(코드만 담아 throw), 합계는 그대로", async () => {
  const before = await taps();
  await expect(countLockedSlotTap("earnings" as never)).rejects.toMatchObject({ cause: "23514" });
  expect(await taps()).toEqual(before);
});

test("대기 등록: 처음 누른 시각을 남기고 다시 눌러도 그대로, 다른 유저 프로필은 바뀌지 않는다. isWaitlisted 전후", async () => {
  const [a, b] = [await user(), await user()];
  expect([await isWaitlisted(a), await isWaitlisted(b)]).toEqual([false, false]);

  await joinWaitlist(a);
  const first = await admin.from("user_profile").select("waitlisted_at").eq("user_id", a).single<{ waitlisted_at: string | null }>();
  expect(first.data!.waitlisted_at).not.toBeNull();
  await new Promise((r) => setTimeout(r, 20));
  await joinWaitlist(a);
  const second = await admin.from("user_profile").select("waitlisted_at").eq("user_id", a).single<{ waitlisted_at: string | null }>();
  expect(second.data!.waitlisted_at).toBe(first.data!.waitlisted_at);

  expect([await isWaitlisted(a), await isWaitlisted(b)]).toEqual([true, false]);
  const other = await admin.from("user_profile").select("plan, timezone, waitlisted_at").eq("user_id", b).single();
  expect(other.data).toEqual({ plan: "free", timezone: "America/New_York", waitlisted_at: null });
});

test("프로필이 없는 유저: 등록은 아무 행도 바꾸지 않고, isWaitlisted는 코드만 담아 throw(페이지가 미등록으로 그린다)", async () => {
  const id = (await createTestUser()).id as VerifiedUserId;
  created.push(id);
  await joinWaitlist(id);
  await expect(isWaitlisted(id)).rejects.toMatchObject({ cause: "PGRST116" });
});
