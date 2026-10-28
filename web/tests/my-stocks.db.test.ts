/**
 * 웹의 유일한 DB 쓰기 지점(src/server/my-stocks.ts)을 로컬 Supabase로 본다(#37 프로필, #38 내 종목).
 * 로컬 Auth admin으로 만든 진짜 유저만 쓰고 끝나면 지운다(프로필·내 종목·이력은 cascade).
 * 커버 범위는 테스트 전용 티커(ZZM*)만 넣고 끝나면 지운다(시드한 종목은 건드리지 않는다).
 */
import { afterAll, beforeAll, expect, test } from "vitest";

import type { VerifiedUserId } from "@/server/auth";
import { addMyStock, ensureProfile, getMyStocks, removeMyStock } from "@/server/my-stocks";

import { admin, createTestUser, deleteTestUsers } from "./local-supabase";

const [A, B, C, D, E] = ["ZZMA", "ZZMB", "ZZMC", "ZZMD", "ZZME"];
const name = (t: string) => `Web Test ${t}`;

const created: string[] = [];
beforeAll(async () => {
  const { error } = await admin.from("coverage").upsert([A, B, C, D, E].map((t) => ({ ticker: t, name: name(t) })));
  if (error) throw new Error(`coverage seed failed: ${error.code}`);
});
afterAll(async () => {
  await deleteTestUsers(created); // 내 종목·이력이 먼저 지워져야 커버 범위 행을 지울 수 있다(FK)
  const { error } = await admin.from("coverage").delete().in("ticker", [A, B, C, D, E]);
  if (error) throw new Error(`coverage cleanup failed: ${error.code}`);
});

async function newUser() {
  const user = await createTestUser();
  created.push(user.id);
  return user.id as VerifiedUserId; // 테스트에서만: 운영에서는 getVerifiedUserId·exchangeCode만 만든다
}

// 컴파일 검사(npm run build의 tsc): 요청 본문에서 꺼낸 문자열은 VerifiedUserId가 아니라 넘길 수 없다
// @ts-expect-error string은 VerifiedUserId가 아니다
export const fromRequest = () => ensureProfile("user-id-from-request-body", "");
// @ts-expect-error 내 종목 쓰기도 같다(#38)
export const addFromRequest = () => addMyStock("user-id-from-request-body", "AAPL");

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

// ---- 내 종목(#38). 개수·교체 규칙은 DB 트리거가 지키고(ADR-0004) 웹 모듈은 거절 이름을 돌려줄 뿐이다 ----

async function newProfile(timezone = "Asia/Seoul") {
  const id = await newUser();
  await ensureProfile(id, timezone);
  return id;
}

/** 이력 전체(바뀌었는지 비교용) */
async function history(id: string) {
  const { data, error } = await admin
    .from("my_stock_history")
    .select("change, ticker, local_date, occurred_at")
    .eq("user_id", id)
    .order("id");
  if (error) throw new Error(`my_stock_history read failed: ${error.code}`);
  return data;
}

async function setPlan(id: string, plan: "free" | "plus") {
  const { error } = await admin.from("user_profile").update({ plan }).eq("user_id", id);
  if (error) throw new Error(`plan update failed: ${error.code}`);
}

const held = (...tickers: string[]) => tickers.map((t) => ({ ticker: t, name: name(t), locked: false }));

test("무료: 3개 넣기(교체 아님) → 4번째 넣기 거절 → 빼기 = 교체 1회(남은 2) → 두 번 더 → 4번째 빼기 거절 → 다시 넣기는 아무 일 없음", async () => {
  const id = await newProfile();
  expect(await getMyStocks(id)).toEqual({ stocks: [], swapsLeft: 3, plan: "free" });

  for (const t of [A, B, C]) expect(await addMyStock(id, t)).toBe("ok");
  expect(await getMyStocks(id)).toEqual({ stocks: held(A, B, C), swapsLeft: 3, plan: "free" }); // 넣은 순서, 넣기는 교체가 아니다

  expect(await addMyStock(id, D)).toBe("free_my_stock_limit");
  expect(await getMyStocks(id)).toEqual({ stocks: held(A, B, C), swapsLeft: 3, plan: "free" });

  expect(await removeMyStock(id, A)).toBe("ok");
  expect(await getMyStocks(id)).toEqual({ stocks: held(B, C), swapsLeft: 2, plan: "free" });
  expect(await removeMyStock(id, B)).toBe("ok");
  expect(await removeMyStock(id, C)).toBe("ok");
  expect(await getMyStocks(id)).toEqual({ stocks: [], swapsLeft: 0, plan: "free" });

  for (const t of [D, E, A]) expect(await addMyStock(id, t)).toBe("ok"); // 빈 칸 채우기는 교체가 아니다
  expect(await removeMyStock(id, D)).toBe("free_swap_limit");
  expect(await getMyStocks(id)).toEqual({ stocks: held(D, E, A), swapsLeft: 0, plan: "free" }); // 거절된 빼기는 되돌려진다

  // 3개가 찬 상태에서 이미 내 종목인 종목 다시 넣기(두 번 누르기): 오류·이력 없음
  const before = await history(id);
  expect(await addMyStock(id, E)).toBe("ok");
  expect(await getMyStocks(id)).toEqual({ stocks: held(D, E, A), swapsLeft: 0, plan: "free" });
  expect(await history(id)).toEqual(before);
});

test("남은 교체 = 프로필 타임존의 오늘 빼기 수(지난날 이력·넣기는 세지 않는다)", async () => {
  // UTC+14와 UTC−11은 언제나 날짜가 다르다: UTC 날짜로 세면 둘 중 하나는 틀린다
  for (const tz of ["Pacific/Kiritimati", "Pacific/Pago_Pago"]) {
    const id = await newProfile(tz);
    const { error } = await admin.from("my_stock_history").insert({ user_id: id, change: "remove", ticker: A, local_date: "2000-01-01" });
    if (error) throw new Error(`history seed failed: ${error.code}`);
    expect(await addMyStock(id, A)).toBe("ok");
    expect(await addMyStock(id, B)).toBe("ok");
    expect(await removeMyStock(id, A)).toBe("ok");
    expect((await getMyStocks(id)).swapsLeft, tz).toBe(2);
  }
});

test("Plus: 남은 교체 없음(null), 개수·교체 제한 없음. 그날 무료로 바뀌면 삭제 수가 3을 넘어도 0(음수 아님)", async () => {
  const id = await newProfile();
  await setPlan(id, "plus");
  for (const t of [A, B, C, D, E]) expect(await addMyStock(id, t)).toBe("ok");
  for (const t of [A, B, C, D]) expect(await removeMyStock(id, t)).toBe("ok");
  expect(await getMyStocks(id)).toEqual({ stocks: held(E), swapsLeft: null, plan: "plus" });

  await setPlan(id, "free");
  expect(await getMyStocks(id)).toEqual({ stocks: held(E), swapsLeft: 0, plan: "free" });
});

test("다운그레이드로 잠긴 내 종목은 locked로 온다. 다시 넣어도 잠금은 그대로", async () => {
  const id = await newProfile();
  await setPlan(id, "plus");
  for (const t of [A, B, C, D]) expect(await addMyStock(id, t)).toBe("ok");
  await setPlan(id, "free"); // 먼저 넣은 3개만 남기고 잠근다(DB 트리거)
  const locked = [...held(A, B, C), { ticker: D, name: name(D), locked: true }];
  expect(await getMyStocks(id)).toEqual({ stocks: locked, swapsLeft: 3, plan: "free" });
  expect(await addMyStock(id, D)).toBe("ok");
  expect((await getMyStocks(id)).stocks).toEqual(locked);
});

test("다른 유저의 내 종목·교체 횟수는 보이지 않고, 빼기도 남의 행을 건드리지 않는다", async () => {
  const a = await newProfile();
  const b = await newProfile();
  for (const t of [A, B]) expect(await addMyStock(a, t)).toBe("ok");
  expect(await removeMyStock(a, B)).toBe("ok");

  expect(await getMyStocks(b)).toEqual({ stocks: [], swapsLeft: 3, plan: "free" });
  expect(await removeMyStock(b, A)).toBe("ok"); // b에게는 없는 종목: 아무 일 없음
  expect(await history(b)).toEqual([]);
  expect(await getMyStocks(a)).toEqual({ stocks: held(A), swapsLeft: 2, plan: "free" });
});

test("커버 범위 밖·형식이 깨진 티커는 쓰지 않는다: 넣기는 코드만 담은 오류, 빼기는 아무 일 없음", async () => {
  const id = await newProfile();
  expect(await addMyStock(id, A)).toBe("ok");
  const before = await history(id);
  for (const bad of ["ZZMZZZ", "zzma", "", "ZZMA'); delete from my_stock;--", "ZZMA,ZZMB", "x".repeat(2000)]) {
    await expect(addMyStock(id, bad), bad).rejects.toThrow(/^my_stock write failed: 23503$/); // FK: 유저 값은 메시지에 없다
    expect(await removeMyStock(id, bad), bad).toBe("ok");
  }
  expect(await getMyStocks(id)).toEqual({ stocks: held(A), swapsLeft: 3, plan: "free" });
  expect(await history(id)).toEqual(before);
});
