/** getDashboard의 실패 경로. DB 없이 supabase-js 응답을 흉내 낸다(정상 경로는 cards.db.test.ts가 로컬 DB로 본다). */
import { createClient } from "@supabase/supabase-js";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { getDashboard } from "@/server/cards";

vi.mock("@supabase/supabase-js", () => ({ createClient: vi.fn() }));

const KEY = "canary-read-test-key";

/** 쿼리 빌더 흉내: 어떤 메서드를 불러도 자신을 돌려주고, await하면 다음 응답을 낸다 */
function respond(...results: object[]) {
  const query: object = new Proxy(
    {},
    { get: (_, prop) => (prop === "then" ? (resolve: (r: object) => void) => resolve(results.shift()!) : () => query) },
  );
  vi.mocked(createClient).mockReturnValue({ from: () => query } as never);
}

const row = (i: number) => ({
  ticker: `T${i}`,
  change_pct: null,
  change_status: "delayed",
  leverage_tag: null,
  coverage: { name: `T${i}` },
  ...Object.fromEntries(
    ["news_line", "event_line", "price_fact_line"].flatMap((l) => ["text", "status", "checked_at", "source_scope"].map((a) => [`${l}_${a}`, null])),
  ),
});
const latest = { data: { trading_day: "2026-10-16" }, error: null };
const failure = { data: null, error: { message: "permission denied for table stock_card" } };

beforeEach(() => {
  vi.stubEnv("SUPABASE_URL", "http://127.0.0.1:54321");
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", KEY);
});
afterEach(() => vi.unstubAllEnvs());

test("최근 거래일 읽기 실패는 '카드 없음'이 아니라 에러", async () => {
  respond(failure);
  await expect(getDashboard()).rejects.toThrow("stock_card read failed: permission denied");
});

test("카드 읽기 실패도 에러", async () => {
  respond(latest, failure);
  await expect(getDashboard()).rejects.toThrow("stock_card read failed: permission denied");
});

test("PostgREST max_rows(1000)에 닿으면 조용히 자르지 않고 에러", async () => {
  respond(latest, { data: Array.from({ length: 1000 }, (_, i) => row(i)), error: null });
  await expect(getDashboard()).rejects.toThrow("1000+ rows");
  respond(latest, { data: Array.from({ length: 999 }, (_, i) => row(i)), error: null });
  expect((await getDashboard()).cards).toHaveLength(999);
});

test("환경 변수가 없으면 이름만 말하는 에러(값 없음)", async () => {
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "");
  await expect(getDashboard()).rejects.toThrow("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set");
});

test("에러 메시지에 키가 없다", async () => {
  respond(failure);
  await expect(getDashboard()).rejects.not.toThrow(KEY);
});
