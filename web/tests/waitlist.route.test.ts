/**
 * POST /waitlist(잠긴 자리 탭·Notify me, #69)의 연결과 실패 경로. DB 없이 supabase-js 응답을 흉내 낸다.
 * 실제 DB 동작(합계 +1, 처음 시각 유지)은 waitlist.db.test.ts가 로컬 DB로 본다.
 */
import { createClient } from "@supabase/supabase-js";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import * as route from "@/app/waitlist/route";
import { getVerifiedUserId, type VerifiedUserId } from "@/server/auth";

vi.mock("@supabase/supabase-js", () => ({ createClient: vi.fn() }));
vi.mock("@/server/auth", () => ({ getVerifiedUserId: vi.fn() }));

const ME = "11111111-1111-4111-8111-111111111111" as VerifiedUserId;
const OTHER = "22222222-2222-4222-8222-222222222222";
const calls: [string, unknown[]][] = [];

/** 쿼리 빌더 흉내: 부른 메서드를 기록하고 자신을 돌려준다. await하면 다음 응답을 낸다 */
function respond(...results: object[]) {
  const query: object = new Proxy(
    {},
    {
      get: (_, prop) =>
        prop === "then"
          ? (resolve: (r: object) => void) => resolve(results.shift()!)
          : (...args: unknown[]) => (calls.push([String(prop), args]), query),
    },
  );
  vi.mocked(createClient).mockReturnValue({
    from: (t: string) => (calls.push(["from", [t]]), query),
    rpc: (...args: unknown[]) => (calls.push(["rpc", args]), query),
  } as never);
}
const ok = { data: null, error: null };
const failed = (code: string) => ({ data: null, error: { code, message: "boom", details: `Key (user_id)=(${ME})` } });

const SAME = "http://localhost";
const post = (fields: Record<string, string>, origin: string | null = SAME, url = "http://localhost/waitlist") =>
  route.POST(new NextRequest(url, { method: "POST", body: new URLSearchParams(fields), headers: origin === null ? {} : { origin } }));
async function expectPlus(res: Promise<Response>, query = "") {
  const r = await res;
  expect(r.status).toBe(303);
  expect(r.headers.get("location")).toBe(`http://localhost/plus${query}`);
}

beforeEach(() => {
  calls.length = 0;
  vi.resetAllMocks();
  vi.stubEnv("SUPABASE_URL", "http://127.0.0.1:54321");
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "canary-route-test-key");
  vi.mocked(getVerifiedUserId).mockResolvedValue(ME);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

test("탭: 로그인 없이 세 자리 종류마다 count_locked_slot_tap 1회, 인자는 { slot }뿐(유저 값 없음) → /plus", async () => {
  vi.mocked(getVerifiedUserId).mockResolvedValue(null);
  for (const slot of ["earnings_summary", "big_holders", "related_lock"]) {
    calls.length = 0;
    respond(ok);
    await expectPlus(post({ intent: "tap", slot, user_id: OTHER }));
    expect(calls).toEqual([["rpc", ["count_locked_slot_tap", { slot }]]]);
  }
  expect(getVerifiedUserId).not.toHaveBeenCalled(); // 탭은 세션을 읽지 않는다
});

test("탭: 모르는 자리·빈 값·없음·대소문자 다름·프로토타입 이름 → DB를 부르지 않고 /plus", async () => {
  for (const slot of ["earnings", "EARNINGS_SUMMARY", "", " big_holders", "constructor", "__proto__", "toString"]) {
    await expectPlus(post({ intent: "tap", slot }));
  }
  await expectPlus(post({ intent: "tap" }));
  expect(createClient).not.toHaveBeenCalled();
});

test("탭 저장 실패도 설명 화면은 열린다(/plus). 로그는 고정 이유와 DB 코드만(자리 값·유저 값 없음)", async () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  respond(failed("23514"));
  await expectPlus(post({ intent: "tap", slot: "big_holders" }));
  respond({ data: null, error: { code: "", message: "fetch failed" } });
  await expectPlus(post({ intent: "tap", slot: "related_lock" }));
  expect(warn.mock.calls.map((c) => c.join(" "))).toEqual(["waitlist: reason=tap_failed code=23514", "waitlist: reason=tap_failed code=unknown"]);
});

test("Notify me: 세션 없음 → 쓰지 않고 /plus(로그인 안내가 보인다)", async () => {
  vi.mocked(getVerifiedUserId).mockResolvedValue(null);
  await expectPlus(post({ intent: "notify", user_id: OTHER }));
  expect(createClient).not.toHaveBeenCalled();
});

test("Notify me: 세션 유저의 행만, 아직 등록 안 했을 때만 지금 시각(다시 눌러도 처음 시각) → /plus. 본문의 user_id는 무시", async () => {
  respond(ok);
  const before = Date.now();
  await expectPlus(post({ intent: "notify", user_id: OTHER }));
  expect(calls).toEqual([
    ["from", ["user_profile"]],
    ["update", [{ waitlisted_at: expect.any(String) }]],
    ["eq", ["user_id", ME]],
    ["is", ["waitlisted_at", null]],
  ]);
  const at = Date.parse((calls[1][1][0] as { waitlisted_at: string }).waitlisted_at);
  expect(at).toBeGreaterThanOrEqual(before);
  expect(at).toBeLessThanOrEqual(Date.now());
});

test("Notify me 저장 실패 → /plus?notify=failed(등록됨을 보이지 않는다). 로그는 고정 이유와 DB 코드만", async () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  respond(failed("08000"));
  await expectPlus(post({ intent: "notify" }), "?notify=failed");
  expect(warn.mock.calls.map((c) => c.join(" "))).toEqual(["waitlist: reason=notify_failed code=08000"]);
  expect(JSON.stringify(warn.mock.calls)).not.toContain(ME);
});

test("Origin이 다르거나 없으면(교차 사이트 POST) 어떤 intent도 쓰지 않고 /plus, 세션도 읽지 않는다. 로그는 고정 이유만(출처 값 없음)", async () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  const origins = ["https://evil.example", "http://localhost:3000", "null", "", null];
  for (const origin of origins) {
    await expectPlus(post({ intent: "tap", slot: "big_holders" }, origin));
    await expectPlus(post({ intent: "notify" }, origin));
  }
  expect(createClient).not.toHaveBeenCalled();
  expect(getVerifiedUserId).not.toHaveBeenCalled();
  expect(warn.mock.calls.map((c) => c.join(" "))).toEqual(Array(origins.length * 2).fill("waitlist: reason=bad_origin"));
});

test("모르는 intent·없음·폼 안 action 이름·깨진 본문 → DB를 부르지 않고 /plus", async () => {
  for (const body of [{}, { intent: "join" }, { intent: "constructor" }, { action: "notify" }, { change: "add", ticker: "AAPL" }] as Record<string, string>[]) {
    await expectPlus(post(body));
  }
  const broken = new NextRequest("http://localhost/waitlist", {
    method: "POST",
    headers: { origin: SAME, "content-type": "multipart/form-data; boundary=x" },
    body: "garbage",
  });
  await expectPlus(route.POST(broken));
  expect(createClient).not.toHaveBeenCalled();
});

test("next·redirect 값을 무시하고 고정 경로로만 보낸다(열린 리디렉션 없음), GET은 없다(405: 프리페치·크롤러가 세지 않게)", async () => {
  respond(ok);
  const evil = "https://evil.example/x";
  await expectPlus(post({ intent: "tap", slot: "big_holders", next: evil, redirect: evil }, SAME, `http://localhost/waitlist?next=${encodeURIComponent(evil)}`));
  expect(Object.keys(route)).toEqual(["POST"]);
});
