/**
 * POST /my-stocks(내 종목 넣기·빼기)의 연결과 실패 경로. DB 없이 supabase-js 응답을 흉내 낸다.
 * 규칙 자체(개수·교체·다시 넣기)는 my-stocks.db.test.ts가 로컬 DB 트리거로 본다.
 */
import { createClient } from "@supabase/supabase-js";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { POST } from "@/app/my-stocks/route";
import { getVerifiedUserId, type VerifiedUserId } from "@/server/auth";

vi.mock("@supabase/supabase-js", () => ({ createClient: vi.fn() }));
vi.mock("@/server/auth", () => ({ getVerifiedUserId: vi.fn() }));

const ME = "11111111-1111-4111-8111-111111111111" as VerifiedUserId;
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
  vi.mocked(createClient).mockReturnValue({ from: (t: string) => (calls.push(["from", [t]]), query) } as never);
}
const ok = { data: null, error: null };
const refused = (message: string) => ({ data: null, error: { code: "23514", message } });
const failed = (code: string) => ({ data: null, error: { code, message: "boom", details: "Key (ticker)=(ZZZZ) is not present" } });

const post = (fields: Record<string, string>) =>
  POST(new NextRequest("http://localhost/my-stocks", { method: "POST", body: new URLSearchParams(fields) }));
const location = (res: Response) => res.headers.get("location");
async function expectBack(res: Promise<Response>, query = "") {
  const r = await res;
  expect(r.status).toBe(303);
  expect(location(r)).toBe(`http://localhost/cards${query}`);
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

test("세션 없음(없음·위조·만료는 getVerifiedUserId가 null) → 쓰지 않고 /cards로", async () => {
  vi.mocked(getVerifiedUserId).mockResolvedValue(null);
  for (const change of ["add", "remove"]) await expectBack(post({ change, ticker: "AAPL" }));
  expect(createClient).not.toHaveBeenCalled();
});

test("넣기: 세션의 유저 id로만 쓴다(본문의 user_id는 무시), 다시 넣기는 on conflict do nothing → /cards", async () => {
  respond(ok);
  await expectBack(post({ change: "add", ticker: "AAPL", user_id: "22222222-2222-4222-8222-222222222222" }));
  expect(calls).toEqual([
    ["from", ["my_stock"]],
    ["upsert", [{ user_id: ME, ticker: "AAPL" }, { onConflict: "user_id,ticker", ignoreDuplicates: true }]],
  ]);
});

test("빼기: 내 행만(user_id + ticker) 지운다 → /cards", async () => {
  respond(ok);
  await expectBack(post({ change: "remove", ticker: "AAPL", user_id: "22222222-2222-4222-8222-222222222222" }));
  expect(calls).toEqual([
    ["from", ["my_stock"]],
    ["delete", []],
    ["eq", ["user_id", ME]],
    ["eq", ["ticker", "AAPL"]],
  ]);
});

test("DB 거절 이름 → 결과 코드(/cards?my_stock=…)", async () => {
  respond(refused("free_my_stock_limit"));
  await expectBack(post({ change: "add", ticker: "AAPL" }), "?my_stock=free_my_stock_limit");
  respond(refused("free_swap_limit"));
  await expectBack(post({ change: "remove", ticker: "AAPL" }), "?my_stock=free_swap_limit");
});

test("교착(40P01)은 한 번만 다시 시도한다", async () => {
  respond({ data: null, error: { code: "40P01", message: "deadlock detected" } }, ok);
  await expectBack(post({ change: "remove", ticker: "AAPL" }));
  expect(calls.filter(([m]) => m === "delete")).toHaveLength(2);

  calls.length = 0;
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  respond(...Array.from({ length: 3 }, () => ({ data: null, error: { code: "40P01", message: "deadlock detected" } })));
  await expectBack(post({ change: "add", ticker: "AAPL" }), "?my_stock=failed");
  expect(calls.filter(([m]) => m === "upsert")).toHaveLength(2);
  expect(warn).toHaveBeenCalledWith("my_stock: reason=write_failed code=40P01");
});

test("그 밖의 DB 오류(커버 범위 밖 23503 등)·이상한 입력 → 실패 문구 코드, 500·스택 없음. 로그는 고정 이유와 DB 코드만", async () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  for (const code of ["23503", "08000", ""]) {
    respond(failed(code));
    await expectBack(post({ change: "add", ticker: "ZZZZ" }), "?my_stock=failed");
  }
  expect(warn.mock.calls.map((c) => c.join(" "))).toEqual([
    "my_stock: reason=write_failed code=23503",
    "my_stock: reason=write_failed code=08000",
    "my_stock: reason=write_failed code=unknown",
  ]);

  // change가 없거나 모르는 값, 본문이 깨짐 → DB를 부르지 않는다
  vi.mocked(createClient).mockClear();
  for (const body of [{ ticker: "AAPL" }, { change: "update", ticker: "AAPL" }, { change: "constructor", ticker: "AAPL" }] as Record<string, string>[]) {
    await expectBack(post(body), "?my_stock=failed");
  }
  const broken = new NextRequest("http://localhost/my-stocks", {
    method: "POST",
    headers: { "content-type": "multipart/form-data; boundary=x" },
    body: "garbage",
  });
  await expectBack(POST(broken), "?my_stock=failed");
  expect(createClient).not.toHaveBeenCalled();
});

test("next·redirect 값을 무시하고 고정 경로로만 보낸다(열린 리디렉션 없음)", async () => {
  respond(ok);
  const evil = "https://evil.example/x";
  const res = await POST(
    new NextRequest(`http://localhost/my-stocks?next=${encodeURIComponent(evil)}`, {
      method: "POST",
      body: new URLSearchParams({ change: "add", ticker: "AAPL", next: evil, redirect: evil }),
    }),
  );
  expect(location(res)).toBe("http://localhost/cards");
});
