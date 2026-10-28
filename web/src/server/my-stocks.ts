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

// ---- 내 종목(#38). 개수·교체·다시 넣기 규칙은 DB 트리거만 지킨다(ADR-0004). 여기서는 쓰고 거절 이름을 돌려줄 뿐이다 ----

const FREE_SWAPS_PER_DAY = 3; // 표시용. 막는 건 DB 트리거(log_my_stock_change)

/** stocks는 넣은 순서(added_at, ticker), 잠긴 것 포함. swapsLeft null = Plus(제한 없음) */
export type MyStocks = { stocks: { ticker: string; name: string; locked: boolean }[]; swapsLeft: number | null };
export type MyStockWrite = "ok" | "free_my_stock_limit" | "free_swap_limit";

/** 남은 교체 = 3 − 오늘(프로필 타임존 자정 기준, user_local_date) 빼기 수, 0 미만은 0. 무료만 */
export async function getMyStocks(userId: VerifiedUserId): Promise<MyStocks> {
  const client = db();
  const [stocks, profile, today] = await Promise.all([
    client
      .from("my_stock")
      .select("ticker, locked, coverage(name)")
      .eq("user_id", userId)
      .order("added_at")
      .order("ticker")
      .overrideTypes<{ ticker: string; locked: boolean; coverage: { name: string } }[], { merge: false }>(),
    client.from("user_profile").select("plan").eq("user_id", userId).single<{ plan: "free" | "plus" }>(),
    // 하루 경계는 DB 함수 한 곳(타임존 변경 보류 포함). 이력의 local_date도 같은 함수로 찍힌다
    client.rpc("user_local_date", { uid: userId, instant: new Date().toISOString() }),
  ]);
  for (const { error } of [stocks, profile, today]) if (error) throw new Error(`my_stock read failed: ${error.code}`);

  let swapsLeft: number | null = null;
  if (profile.data!.plan === "free") {
    const { count, error } = await client
      .from("my_stock_history")
      .select("id", { count: "exact", head: true })
      .eq("user_id", userId)
      .eq("change", "remove")
      .eq("local_date", today.data);
    if (error) throw new Error(`my_stock read failed: ${error.code}`);
    swapsLeft = Math.max(0, FREE_SWAPS_PER_DAY - count!);
  }
  return { stocks: stocks.data!.map((s) => ({ ticker: s.ticker, name: s.coverage.name, locked: s.locked })), swapsLeft };
}

/** 이미 내 종목이면 아무 일 없음(DB가 건너뜀, 이력 없음). 커버 범위 밖 티커는 FK가 막아 throw */
export function addMyStock(userId: VerifiedUserId, ticker: string): Promise<MyStockWrite> {
  return write(() =>
    db().from("my_stock").upsert({ user_id: userId, ticker }, { onConflict: "user_id,ticker", ignoreDuplicates: true }),
  );
}

/** 내 행만 지운다. 내 종목이 아니면(형식이 깨진 티커 포함) 지울 행이 없어 아무 일 없음 */
export function removeMyStock(userId: VerifiedUserId, ticker: string): Promise<MyStockWrite> {
  return write(() => db().from("my_stock").delete().eq("user_id", userId).eq("ticker", ticker));
}

/** 거절 이름 → 결과. 교착(40P01)은 한 번만 다시. 그 밖의 오류는 코드만 담아 throw(details에 유저 값이 있다) */
async function write(run: () => PromiseLike<{ error: { code: string; message: string } | null }>): Promise<MyStockWrite> {
  let { error } = await run();
  if (error?.code === "40P01") ({ error } = await run());
  if (!error) return "ok";
  if (error.code === "23514" && (error.message === "free_my_stock_limit" || error.message === "free_swap_limit")) return error.message;
  const code = error.code || "unknown";
  throw new Error(`my_stock write failed: ${code}`, { cause: code });
}
