/**
 * 웹의 유일한 DB 쓰기 지점(src/server/my-stocks.ts)을 로컬 Supabase로 본다. #38이 이 파일을 넓힌다.
 * 로컬 Auth admin으로 만든 진짜 유저만 쓰고 끝나면 지운다(프로필은 cascade).
 */
import { afterAll, expect, test } from "vitest";

import type { VerifiedUserId } from "@/server/auth";
import { ensureProfile } from "@/server/my-stocks";

import { admin, createTestUser, deleteTestUsers } from "./local-supabase";

const created: string[] = [];
afterAll(() => deleteTestUsers(created));

async function newUser() {
  const user = await createTestUser();
  created.push(user.id);
  return user.id as VerifiedUserId; // 테스트에서만: 운영에서는 getVerifiedUserId·exchangeCode만 만든다
}

// 컴파일 검사(npm run build의 tsc): 요청 본문에서 꺼낸 문자열은 VerifiedUserId가 아니라 넘길 수 없다
// @ts-expect-error string은 VerifiedUserId가 아니다
export const fromRequest = () => ensureProfile("user-id-from-request-body", "");

async function profile(id: string) {
  const { data, error } = await admin.from("user_profile").select("plan, timezone").eq("user_id", id).maybeSingle();
  if (error) throw new Error(`user_profile read failed: ${error.code}`);
  return data;
}

test("첫 로그인 → 무료 + 브라우저 타임존, 재로그인은 그대로(다른 타임존·이상한 타임존이어도 throw 없음)", async () => {
  const id = await newUser();
  expect(await profile(id)).toBeNull();

  await ensureProfile(id, "Asia/Seoul");
  expect(await profile(id)).toEqual({ plan: "free", timezone: "Asia/Seoul" });

  await ensureProfile(id, "Europe/Paris");
  expect(await profile(id)).toEqual({ plan: "free", timezone: "Asia/Seoul" });

  // BEFORE INSERT 트리거가 충돌 검사보다 먼저 돌아 timezone_name이 난다 → NY로 다시 시도 → do nothing
  await ensureProfile(id, "Not/AZone");
  expect(await profile(id)).toEqual({ plan: "free", timezone: "Asia/Seoul" });
});

test("새 유저 + DB가 거절하는 타임존 → America/New_York", async () => {
  const id = await newUser();
  await ensureProfile(id, "Not/AZone");
  expect(await profile(id)).toEqual({ plan: "free", timezone: "America/New_York" });
});

test("새 유저 + 빈 타임존(JS 없음) → America/New_York", async () => {
  const id = await newUser();
  await ensureProfile(id, "");
  expect(await profile(id)).toEqual({ plan: "free", timezone: "America/New_York" });
});

test("그 밖의 DB 오류는 코드만 담아 throw(유저 값 없음)", async () => {
  // auth.users에 없는 id → FK 위반(23503)
  const ghost = "00000000-0000-4000-8000-000000000000" as VerifiedUserId;
  await expect(ensureProfile(ghost, "Asia/Seoul")).rejects.toThrow(/^user_profile write failed: 23503$/);
});
