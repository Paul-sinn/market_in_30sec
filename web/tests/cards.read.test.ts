/** getDashboard의 실패 경로. DB 없이 supabase-js 응답을 흉내 낸다(정상 경로는 cards.db.test.ts가 로컬 DB로 본다). */
import { createClient } from "@supabase/supabase-js";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { getDashboard } from "@/server/cards";

vi.mock("@supabase/supabase-js", () => ({ createClient: vi.fn() }));

const KEY = "canary-read-test-key";

/** 테이블마다 마지막 select 인자 */
let selects: Record<string, string> = {};

/** 쿼리 빌더 흉내: 어떤 메서드를 불러도 자신을 돌려주고, await하면 다음 응답을 낸다(await 순서대로) */
function respond(...results: object[]) {
  let table = "";
  selects = {};
  const query: object = new Proxy(
    {},
    {
      get: (_, prop) =>
        prop === "then"
          ? (resolve: (r: object) => void) => resolve(results.shift()!)
          : (...args: unknown[]) => {
              if (prop === "select") selects[table] = String(args[0]);
              return query;
            },
    },
  );
  vi.mocked(createClient).mockReturnValue({ from: (t: string) => ((table = t), query) } as never);
}

const row = (i: number) => ({
  ticker: `T${i}`,
  change_pct: null,
  change_status: "delayed",
  leverage_tag: null,
  coverage: { name: `T${i}`, holdings_ticker: null },
  news_filing: null, // 1등 공시 분류(#69). 첫 번째 줄이 없으면 null
  ...Object.fromEntries(
    ["news_line", "event_line", "price_fact_line"].flatMap((l) => ["text", "status", "checked_at", "source_scope"].map((a) => [`${l}_${a}`, null])),
  ),
});
const latest = { data: { trading_day: "2026-10-16" }, error: null };
const failure = { data: null, error: { message: "permission denied for table stock_card" } };
const noCards = { data: [], error: null };
const noGlance = { data: null, error: null }; // maybeSingle: 그날 행 없음
const noQuiet = { data: [], error: null }; // 알아두기 1번(#66) 행 없음
const noEstimates = { data: [], error: null }; // 그날 실적 추정 행 없음(잠긴 자리, #69)
const GLANCE_LINES = ["close_line", "indicator_line", "market_news_line"];

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
  respond(latest, { data: Array.from({ length: 999 }, (_, i) => row(i)), error: null }, noGlance, noQuiet, noEstimates);
  expect((await getDashboard()).cards).toHaveLength(999);
});

test("카드가 없으면 시장 한눈에도 읽지 않는다(glance null, No cards yet만)", async () => {
  respond({ data: null, error: null });
  expect(await getDashboard()).toEqual({ tradingDay: null, day: null, glance: null, cards: [] });
  expect(selects).not.toHaveProperty("market_glance");
  expect(selects).not.toHaveProperty("quiet_fact");
  expect(selects).not.toHaveProperty("earnings_estimate");
});

test("시장 한눈에 읽기 실패도 에러(빈 블록·지연으로 보이지 않게)", async () => {
  respond(latest, noCards, { data: null, error: { message: "permission denied for table market_glance" } });
  await expect(getDashboard()).rejects.toThrow("market_glance read failed: permission denied");
});

test("그날 시장 한눈에 행이 없으면 Update delayed 세 줄, 하단 없음", async () => {
  respond(latest, noCards, noGlance, noQuiet, noEstimates);
  expect((await getDashboard()).glance).toEqual({ lines: Array(3).fill({ text: "Update delayed", status: "delayed" }), checked: null });
});

test("시장 한눈에는 줄 컬럼 12개만 select한다: 보류 기록(market_news_hold_*, 검수 안 된 문장)·updated_at·* 없음", async () => {
  const stored = Object.fromEntries(
    GLANCE_LINES.flatMap((l) => [
      [`${l}_text`, `${l} text`],
      [`${l}_status`, "checked_found"],
      [`${l}_checked_at`, "2026-10-16T11:30:00Z"],
      [`${l}_source_scope`, "Daily prices"],
    ]),
  );
  respond(latest, noCards, { data: stored, error: null }, noQuiet, noEstimates);
  const { glance } = await getDashboard();
  expect(selects.market_glance.split(",")).toEqual(
    GLANCE_LINES.flatMap((l) => [`${l}_text`, `${l}_status`, `${l}_checked_at`, `${l}_source_scope`]),
  );
  expect(selects.market_glance).not.toMatch(/hold|updated_at|\*/);
  expect(glance?.lines.map((l) => l.text)).toEqual(["close_line text", "indicator_line text", "market_news_line text"]);
});

test("가격 표시 off면 시장 한눈에는 어제 마감 줄 컬럼을 select하지 않고 두 줄만(DB에 옛 값이 있어도)", async () => {
  vi.stubEnv("PRICE_DISPLAY", undefined);
  // 모의 응답은 select와 상관없이 어제 마감 값을 돌려준다(옛 값이 남은 행). 그래도 화면 모델에 닿으면 안 된다
  const stored = {
    close_line_text: "Wed 10/15 close: S&P 500 (SPY) +0.4%",
    close_line_status: "checked_found",
    close_line_checked_at: "2026-10-16T11:10:00Z", // 7:10 AM ET: 가장 이른 시각
    close_line_source_scope: "Daily prices",
    indicator_line_text: "CPI 8:30 AM ET",
    indicator_line_status: "checked_found",
    indicator_line_checked_at: "2026-10-16T11:30:00Z",
    indicator_line_source_scope: "Economic calendar",
    market_news_line_text: "No official releases found",
    market_news_line_status: "checked_none",
    market_news_line_checked_at: "2026-10-16T11:30:00Z",
    market_news_line_source_scope: "Official releases",
  };
  respond(latest, noCards, { data: stored, error: null }, noQuiet, noEstimates);
  const { glance } = await getDashboard();
  expect(selects.market_glance.split(",")).toEqual(
    ["indicator_line", "market_news_line"].flatMap((l) => [`${l}_text`, `${l}_status`, `${l}_checked_at`, `${l}_source_scope`]),
  );
  expect(glance).toEqual({
    lines: [
      { text: "CPI 8:30 AM ET", status: "checked_found" },
      { text: "No official releases found", status: "checked_none" },
    ],
    checked: "Checked 7:30 AM ET · Economic calendar · Official releases",
  });
});

test("가격 표시 off에 그날 시장 한눈에 행이 없으면 Update delayed 두 줄, 하단 없음", async () => {
  vi.stubEnv("PRICE_DISPLAY", "off");
  respond(latest, noCards, noGlance, noQuiet, noEstimates);
  expect((await getDashboard()).glance).toEqual({ lines: Array(2).fill({ text: "Update delayed", status: "delayed" }), checked: null });
});

test("알아두기 1번(#66)은 카드와 같은 공용 읽기: ticker·text만 select해 종목마다 firstQuietFact, 없으면 null. day는 원래 날짜", async () => {
  respond(latest, { data: [row(0), row(1)], error: null }, noGlance, { data: [{ ticker: "T1", text: "T1 makes test widgets" }], error: null }, noEstimates);
  const data = await getDashboard();
  expect(selects.quiet_fact).toBe("ticker, text");
  expect([data.day, data.tradingDay]).toEqual(["2026-10-16", "Fri, Oct 16, 2026"]);
  expect(data.cards.map((c) => [c.ticker, c.firstQuietFact])).toEqual([
    ["T0", null],
    ["T1", "T1 makes test widgets"],
  ]);
});

test("알아두기 1번 읽기 실패·max_rows(1000)도 에러(알아두기 없음으로 보이지 않게)", async () => {
  respond(latest, noCards, noGlance, { data: null, error: { message: "permission denied for table quiet_fact" } });
  await expect(getDashboard()).rejects.toThrow("quiet_fact read failed: permission denied");
  respond(latest, noCards, noGlance, { data: Array.from({ length: 1000 }, (_, i) => ({ ticker: `T${i}`, text: "x" })), error: null });
  await expect(getDashboard()).rejects.toThrow("quiet_fact has 1000+ rows");
});

test("잠긴 자리(#69): 카드 select에 1등 공시 분류 embed(힌트 !news_line_accession)·ETF 판정 열, 추정은 그날 거래일의 ticker·estimate_day만", async () => {
  const card = (ticker: string, holdings: string | null, kinds: [string, string | null][] | null) => ({
    ...row(0),
    ticker,
    coverage: { name: ticker, holdings_ticker: holdings },
    news_filing: kinds && { filing_classification: kinds.map(([t, kind]) => ({ ticker: t, kind })) },
  });
  respond(
    latest,
    {
      data: [
        card("E1", null, [["E1", "earnings"]]),
        card("E2", null, [["XX", "earnings"], ["E2", "deal"]]), // 실적 분류는 다른 종목 행에만
        card("E3", null, [["E3", null]]), // 분류 못 함
        card("E4", null, null),
        card("E5", "QQQ", [["E5", "earnings"]]), // ETF
      ],
      error: null,
    },
    noGlance,
    noQuiet,
    { data: [{ ticker: "E4", estimate_day: "2026-10-23" }], error: null }, // D-7
  );
  const { cards } = await getDashboard();
  expect(cards.map((c) => [c.ticker, c.lockedSlot])).toEqual([
    ["E1", "earnings_summary"],
    ["E2", "big_holders"],
    ["E3", "big_holders"],
    ["E4", "earnings_summary"],
    ["E5", null],
  ]);
  expect(selects.stock_card).toContain("coverage(name,holdings_ticker)");
  expect(selects.stock_card).toContain("news_filing:sec_filing!news_line_accession(filing_classification(ticker,kind))");
  expect(selects.earnings_estimate).toBe("ticker, estimate_day");
});

test("실적 추정 읽기 실패·max_rows(1000)도 에러(잠긴 자리가 큰손 움직임으로 잘못 보이지 않게)", async () => {
  respond(latest, noCards, noGlance, noQuiet, { data: null, error: { message: "permission denied for table earnings_estimate" } });
  await expect(getDashboard()).rejects.toThrow("earnings_estimate read failed: permission denied");
  respond(latest, noCards, noGlance, noQuiet, { data: Array.from({ length: 1000 }, (_, i) => ({ ticker: `T${i}`, estimate_day: "2026-10-16" })), error: null });
  await expect(getDashboard()).rejects.toThrow("earnings_estimate has 1000+ rows");
});

test("환경 변수가 없으면 이름만 말하는 에러(값 없음)", async () => {
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "");
  await expect(getDashboard()).rejects.toThrow("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set");
});

test("에러 메시지에 키가 없다", async () => {
  respond(failure);
  await expect(getDashboard()).rejects.not.toThrow(KEY);
});
