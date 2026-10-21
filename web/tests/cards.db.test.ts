/**
 * 로컬 Supabase에 카드를 넣고 getDashboard가 화면 모델로 바꾸는지 본다. 원격 금지.
 * 먼 미래 거래일(2099)·테스트 전용 티커만 쓰고 끝나면 지운다(시드 데이터는 건드리지 않는다).
 */
import { createClient } from "@supabase/supabase-js";
import { afterAll, beforeAll, expect, test } from "vitest";

import { getDashboard } from "@/server/cards";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);
const url = process.env.SUPABASE_URL ?? "";
const key = process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";
if (!url || !key) {
  throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see web/README.md)");
}
if (!LOCAL_HOSTS.has(new URL(url).hostname)) {
  throw new Error("SUPABASE_URL is not local. DB tests run against local Supabase only");
}
const admin = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });

const DAY = "2099-12-31";
const EARLIER = "2099-12-30";
const TICKERS = ["ZZWA", "ZZWB", "ZZWC", "ZZWD"];
const AT = "2099-12-31T12:30:00+00:00"; // 7:30 AM EST

const line = (prefix: string, text: string | null, status: string | null, scope: string | null) => ({
  [`${prefix}_text`]: text,
  [`${prefix}_status`]: status,
  [`${prefix}_checked_at`]: status && AT,
  [`${prefix}_source_scope`]: scope,
});

const cards = [
  // 넣는 순서를 섞어 종목순 정렬을 확인한다
  {
    ticker: "ZZWD",
    trading_day: DAY,
    status: "fallback",
    change_pct: null,
    change_status: "unsupported",
    ...line("event_line", "Not covered yet", "unsupported", null),
    ...line("price_fact_line", "Not covered yet", "unsupported", null),
    leverage_tag: "−3x inverse · resets daily",
  },
  {
    ticker: "ZZWA",
    trading_day: DAY,
    status: "normal",
    change_pct: 1.3,
    change_status: "checked_found",
    ...line("news_line", "Web Test A reported Q3 results (SEC filing)", "checked_found", "SEC filings"),
    ...line("event_line", "Earnings Thu 1/7 after close (D-7)", "checked_found", "Earnings and dividend calendar"),
    ...line("price_fact_line", "Up 5 days in a row", "checked_found", "Daily prices"),
    leverage_tag: null,
  },
  {
    ticker: "ZZWC",
    trading_day: DAY,
    status: "fallback",
    change_pct: null,
    change_status: "delayed",
    ...line("event_line", "No confirmed events found", "checked_none", "Earnings and dividend calendar"),
    ...line("price_fact_line", "Update delayed", "delayed", "Daily prices"),
    leverage_tag: "3x · resets daily",
  },
  {
    ticker: "ZZWB",
    trading_day: DAY,
    status: "normal",
    change_pct: -2.0,
    change_status: "checked_found",
    ...line("news_line", "No new SEC filings found", "checked_none", "SEC filings"),
    ...line("event_line", "No confirmed events found", "checked_none", "Earnings and dividend calendar"),
    ...line("price_fact_line", "No additional price highlights", "checked_none", "Daily prices"),
    leverage_tag: null,
  },
  // 이전 거래일 카드는 화면에 나오지 않는다
  {
    ticker: "ZZWA",
    trading_day: EARLIER,
    status: "fallback",
    change_pct: 9.9,
    change_status: "checked_found",
    leverage_tag: null,
  },
];

async function cleanup() {
  const a = await admin.from("stock_card").delete().in("ticker", TICKERS);
  const b = await admin.from("coverage").delete().in("ticker", TICKERS);
  if (a.error || b.error) throw new Error(`cleanup failed: ${(a.error ?? b.error)?.message}`);
}

beforeAll(async () => {
  await cleanup();
  const cov = await admin.from("coverage").insert(TICKERS.map((t) => ({ ticker: t, name: `Web Test ${t.at(-1)}` })));
  if (cov.error) throw new Error(`coverage insert failed: ${cov.error.message}`);
  const ins = await admin.from("stock_card").insert(cards);
  if (ins.error) throw new Error(`stock_card insert failed: ${ins.error.message}`);
});

afterAll(cleanup);

test("가장 최근 거래일의 카드를 종목순으로 화면 모델로", async () => {
  const data = await getDashboard();
  expect(data.tradingDay).toBe("Thu, Dec 31, 2099");
  expect(data.cards).toEqual([
    {
      ticker: "ZZWA",
      name: "Web Test A",
      change: { text: "+1.3%", tone: "up" },
      lines: [
        { text: "Web Test A reported Q3 results (SEC filing)", status: "checked_found" },
        { text: "Earnings Thu 1/7 after close (D-7)", status: "checked_found" },
        { text: "Up 5 days in a row", status: "checked_found" },
      ],
      leverageTag: null,
      checked: "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar · Daily prices",
    },
    {
      ticker: "ZZWB",
      name: "Web Test B",
      change: { text: "−2.0%", tone: "down" },
      lines: [
        { text: "No new SEC filings found", status: "checked_none" },
        { text: "No confirmed events found", status: "checked_none" },
        { text: "No additional price highlights", status: "checked_none" },
      ],
      leverageTag: null,
      checked: "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar · Daily prices",
    },
    {
      ticker: "ZZWC",
      name: "Web Test C",
      change: { text: "Update delayed", tone: "delayed" },
      lines: [
        { text: "Update delayed", status: "delayed" }, // 축소판: 첫 번째 줄 없음
        { text: "No confirmed events found", status: "checked_none" },
        { text: "Update delayed", status: "delayed" },
      ],
      leverageTag: "3x · resets daily",
      checked: "Checked 7:30 AM ET · Earnings and dividend calendar", // 지연된 가격 줄의 출처는 빠진다
    },
    {
      ticker: "ZZWD",
      name: "Web Test D",
      change: { text: "Not covered yet", tone: "unsupported" },
      lines: [
        { text: "Update delayed", status: "delayed" },
        { text: "Not covered yet", status: "unsupported" },
        { text: "Not covered yet", status: "unsupported" },
      ],
      leverageTag: "−3x inverse · resets daily",
      checked: null, // 확인된 줄이 없으면 하단 없음
    },
  ]);
});
