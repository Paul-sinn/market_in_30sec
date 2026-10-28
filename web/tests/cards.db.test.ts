/**
 * 로컬 Supabase에 카드를 넣고 getDashboard → exposeCards(#9)가 화면 모델로 바꾸는지 본다. 원격 금지.
 * 먼 미래 거래일(2099)·테스트 전용 티커만 쓰고 끝나면 지운다(시드 데이터는 건드리지 않는다).
 * 노출 비교용 유저는 로컬 Auth admin으로 만들고 끝나면 지운다(프로필·내 종목·이력은 cascade).
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, expect, test } from "vitest";

import { Dashboard } from "@/components/dashboard";
import { myDashboardView } from "@/lib/card-view";
import type { VerifiedUserId } from "@/server/auth";
import { getCoverage, getDashboard } from "@/server/cards";
import { exposeCards } from "@/server/exposure";
import { addMyStock, ensureProfile, getMyStocks } from "@/server/my-stocks";

import { admin, createTestUser, deleteTestUsers } from "./local-supabase";

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

const created: string[] = [];
afterAll(async () => {
  await deleteTestUsers(created); // 내 종목이 먼저 지워져야 커버 범위 행을 지울 수 있다(FK)
  await cleanup();
});

/** 네 종목 전부가 잠기지 않은 내 종목인 Plus 유저(세 줄 전부) */
const PLUS_ALL = { plan: "plus" as const, stocks: TICKERS.map((ticker) => ({ ticker, locked: false })) };

test("가장 최근 거래일의 카드를 종목순으로 화면 모델로(Plus 내 종목 = 세 줄 전부)", async () => {
  const data = await getDashboard();
  expect(data.tradingDay).toBe("Thu, Dec 31, 2099");
  expect(exposeCards(data.cards, PLUS_ALL)).toEqual([
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

test("로그인 전 = 무료 범위: 세 번째 줄은 잠금만, 하단에서도 그 줄의 출처가 빠진다. 지연·미지원은 그대로", async () => {
  const cards = exposeCards((await getDashboard()).cards, null);
  expect(cards.map((c) => [c.ticker, c.change.text, c.lines, c.checked])).toEqual([
    [
      "ZZWA",
      "+1.3%",
      [
        { text: "Web Test A reported Q3 results (SEC filing)", status: "checked_found" },
        { text: "Earnings Thu 1/7 after close (D-7)", status: "checked_found" },
        { status: "locked" },
      ],
      "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar",
    ],
    [
      "ZZWB",
      "−2.0%",
      [
        { text: "No new SEC filings found", status: "checked_none" },
        { text: "No confirmed events found", status: "checked_none" },
        { status: "locked" },
      ],
      "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar",
    ],
    [
      "ZZWC",
      "Update delayed",
      [{ text: "Update delayed", status: "delayed" }, { text: "No confirmed events found", status: "checked_none" }, { status: "locked" }],
      "Checked 7:30 AM ET · Earnings and dividend calendar",
    ],
    [
      "ZZWD",
      "Not covered yet",
      [{ text: "Update delayed", status: "delayed" }, { text: "Not covered yet", status: "unsupported" }, { status: "locked" }],
      null,
    ],
  ]);
});

test("같은 카드를 Plus 유저와 무료 유저가 볼 때 세 번째 줄이 다르다(플랜은 user_profile.plan, 세션 유저 id로)", async () => {
  const user = async (plan: "free" | "plus") => {
    const id = (await createTestUser()).id as VerifiedUserId; // 테스트에서만: 운영에서는 getVerifiedUserId만 만든다
    created.push(id);
    await ensureProfile(id, "America/New_York");
    expect(await addMyStock(id, "ZZWA")).toBe("ok");
    const { error } = await admin.from("user_profile").update({ plan }).eq("user_id", id); // 결제(#10) 전이라 서비스 역할로
    if (error) throw new Error(`plan update failed: ${error.code}`);
    return id;
  };
  const [free, plus] = [await user("free"), await user("plus")];

  // /cards 페이지와 같은 순서: 카드·내 종목을 읽고, 컴포넌트로 넘기기 전에 노출을 판단한다
  const { tradingDay, cards } = await getDashboard();
  const coverage = await getCoverage();
  const page = async (id: VerifiedUserId) => {
    const my = await getMyStocks(id);
    const data = { tradingDay, cards: exposeCards(cards, my) };
    return { data, html: renderToStaticMarkup(createElement(Dashboard, { data, mine: myDashboardView(data.cards, coverage, my, undefined) })) };
  };
  const [f, p] = [await page(free), await page(plus)];
  const third = (d: typeof f, ticker: string) => d.data.cards.find((c) => c.ticker === ticker)!.lines[2];

  expect(third(p, "ZZWA")).toEqual({ text: "Up 5 days in a row", status: "checked_found" }); // Plus 내 종목
  expect(third(f, "ZZWA")).toEqual({ status: "locked" }); // 무료 내 종목
  expect(third(p, "ZZWB")).toEqual({ status: "locked" }); // Plus 둘러보기
  expect(third(f, "ZZWB")).toEqual({ status: "locked" });
  // ZZWA의 세 번째 줄 문구는 픽스처에서 하나뿐: 무료 HTML에는 없다
  expect(p.html).toContain("Up 5 days in a row");
  expect(f.html).not.toContain("Up 5 days in a row");
  expect(f.html).toContain("Price facts in Plus");
});
