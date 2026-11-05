/**
 * 로컬 Supabase에 카드를 넣고 getDashboard → exposeCards(#9)가 화면 모델로 바꾸는지 본다. 원격 금지.
 * 먼 미래 거래일(2099)·테스트 전용 티커만 쓰고 끝나면 지운다(시드 데이터는 건드리지 않는다).
 * 노출 비교용 유저는 로컬 Auth admin으로 만들고 끝나면 지운다(프로필·내 종목·이력은 cascade).
 * 시장 한눈에(#11) 2099 행 2개는 지우지 못한다(service_role에 delete 권한 없음, 의도된 스키마): 매번 upsert로 덮어쓴다.
 * backend pytest가 public 테이블을 비울 때 같이 지워진다.
 */
import { randomUUID } from "node:crypto";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";

import { Dashboard } from "@/components/dashboard";
import { myDashboardView } from "@/lib/card-view";
import type { VerifiedUserId } from "@/server/auth";
import { getCoverage, getDashboard } from "@/server/cards";
import { exposeCards } from "@/server/exposure";
import { addMyStock, ensureProfile, getMyStocks } from "@/server/my-stocks";

import { admin, createTestUser, deleteTestUsers } from "./local-supabase";

const DAY = "2099-12-31";
const EARLIER = "2099-12-30";
const TICKERS = ["ZZWA", "ZZWB", "ZZWC", "ZZWD", "ZZWE", "ZZWF", "ZZWG"];
const SUSPENDED_TEXT = "Web Test E suspended line"; // 발행 중단 카드(ZZWE)에만 있는 문구
const AT = "2099-12-31T12:30:00+00:00"; // 7:30 AM EST
const HOLD = `canary-hold-${randomUUID()}`; // 시장 한눈에 보류 기록(검수 안 된 문장). 웹은 읽지 않는다
const EARLIER_GLANCE = `canary-earlier-glance-${randomUUID()}`; // 이전 거래일 행에만 있는 문구

const glanceRow = (trading_day: string, close: string) => ({
  trading_day,
  close_line_text: close,
  close_line_status: "checked_found",
  close_line_checked_at: AT,
  close_line_source_scope: "Daily prices",
  indicator_line_text: "CPI 8:30 AM ET · Retail sales 10:00 AM ET",
  indicator_line_status: "checked_found",
  indicator_line_checked_at: "2099-12-31T12:20:00+00:00", // 7:20 AM EST: 하단은 가장 이른 시각
  indicator_line_source_scope: "Economic calendar",
  market_news_line_text: "Update delayed", // 검수에 걸려 대체된 소식 줄
  market_news_line_status: "delayed",
  market_news_line_checked_at: AT,
  market_news_line_source_scope: "Official releases",
  market_news_hold_draft: HOLD,
  market_news_hold_rules: [`1 copy_rules: ${HOLD}`],
});
const CLOSE = "Wed 12/30 close: S&P 500 (SPY) +0.4%, Nasdaq (QQQ) \u22121.2%";
const GLANCE = {
  lines: [
    { text: CLOSE, status: "checked_found" },
    { text: "CPI 8:30 AM ET · Retail sales 10:00 AM ET", status: "checked_found" },
    { text: "Update delayed", status: "delayed" },
  ],
  checked: "Checked 7:20 AM ET · Daily prices · Economic calendar", // 지연된 소식 줄의 출처는 빠진다
};

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
    status: "normal", // 첫 번째 줄이 있으면 normal(DB 제약 fallback_iff_no_news_line)
    change_pct: null,
    change_status: "unsupported",
    ...line("news_line", "Not covered yet", "unsupported", null),
    ...line("event_line", "Not covered yet", "unsupported", null),
    ...line("price_fact_line", "Not covered yet", "unsupported", null),
    leverage_tag: "−3x inverse · resets daily",
  },
  {
    ticker: "ZZWA",
    trading_day: DAY,
    previous_trading_day: EARLIER, // 종가 날짜 라벨(#16)
    status: "normal",
    change_pct: 1.3,
    change_status: "checked_found",
    ...line("news_line", "Web Test A reported Q3 results (SEC filing)", "checked_found", "SEC filings"),
    news_line_filing_count: 3, // 카드 헤더(#63): 문장에 +N more가 없어도 저장 건수 그대로(웹은 문장을 파싱하지 않는다)
    ...line("event_line", "Earnings Thu 1/7 after close (D-7)", "checked_found", "Earnings and dividend calendar"),
    ...line("price_fact_line", "Up 5 days in a row", "checked_found", "Daily prices"),
    leverage_tag: null,
  },
  {
    ticker: "ZZWC",
    trading_day: DAY,
    previous_trading_day: EARLIER, // 등락률이 지연이어도 종가 날짜는 있다(그날 종가가 지연)
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
  // 발행 중단(#16 D7): 읽히지만(suspended) 화면 모델에는 없다
  {
    ticker: "ZZWE",
    trading_day: DAY,
    previous_trading_day: EARLIER,
    publish_suspended: true,
    status: "normal",
    change_pct: 4.4,
    change_status: "checked_found",
    ...line("news_line", SUSPENDED_TEXT, "checked_found", "SEC filings"),
    ...line("event_line", "No confirmed events found", "checked_none", "Earnings and dividend calendar"),
    ...line("price_fact_line", "No additional price highlights", "checked_none", "Daily prices"),
    leverage_tag: null,
  },
  // 카드 헤더(#63): 첫 번째 줄 지연(수집 실패), 공시 1건
  {
    ticker: "ZZWF",
    trading_day: DAY,
    status: "normal",
    change_pct: null,
    change_status: "delayed",
    ...line("news_line", "Update delayed", "delayed", "SEC filings"),
    leverage_tag: null,
  },
  {
    ticker: "ZZWG",
    trading_day: DAY,
    status: "normal",
    change_pct: null,
    change_status: "delayed",
    ...line("news_line", "Web Test G named a new CFO (SEC filing)", "checked_found", "SEC filings"),
    news_line_filing_count: 1,
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
  const ins = await admin.from("stock_card").insert(cards, { defaultToNull: false }); // 행마다 키가 달라도 빠진 컬럼은 DB 기본값(publish_suspended = false)
  if (ins.error) throw new Error(`stock_card insert failed: ${ins.error.message}`);
  const glance = await admin.from("market_glance").upsert([glanceRow(DAY, CLOSE), glanceRow(EARLIER, EARLIER_GLANCE)]);
  if (glance.error) throw new Error(`market_glance upsert failed: ${glance.error.message}`);
});

const created: string[] = [];
afterAll(async () => {
  await deleteTestUsers(created); // 내 종목이 먼저 지워져야 커버 범위 행을 지울 수 있다(FK)
  await cleanup();
});

afterEach(() => vi.unstubAllEnvs()); // 가격 표시 플래그는 설정 기본값 on(vitest.config.mts)

/** 네 종목 전부가 잠기지 않은 내 종목인 Plus 유저(세 줄 전부) */
const PLUS_ALL = { plan: "plus" as const, stocks: TICKERS.map((ticker) => ({ ticker, locked: false })) };

test("가장 최근 거래일의 카드를 종목순으로 화면 모델로(Plus 내 종목 = 세 줄 전부, 발행 중단 카드는 빠진다)", async () => {
  const data = await getDashboard();
  expect(data.tradingDay).toBe("Thu, Dec 31, 2099");
  // 발행 중단은 읽기에서 거르지 않고 suspended로 담는다: 거르는 곳은 exposeCards 한 곳(#16 D7)
  // 공시 수(#63)는 DB 값 그대로 담는다. 헤더는 exposeCards가 만든다
  expect(data.cards.map((c) => [c.ticker, c.suspended, c.newsFilingCount])).toEqual([
    ["ZZWA", false, 3],
    ["ZZWB", false, null],
    ["ZZWC", false, null],
    ["ZZWD", false, null],
    ["ZZWE", true, null],
    ["ZZWF", false, null],
    ["ZZWG", false, 1],
  ]);
  expect(exposeCards(data.cards, PLUS_ALL)).toEqual([
    {
      ticker: "ZZWA",
      name: "Web Test A",
      header: { text: "3 new filings", status: "checked_found" },
      change: { text: "+1.3%", tone: "up", label: "Wed 12/30 close" },
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
      header: { text: "Quiet day", status: "checked_none" },
      change: { text: "−2.0%", tone: "down", label: "prev close" }, // previous_trading_day null = #16 전 카드
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
      header: { text: "Update delayed", status: "delayed" }, // 축소판
      change: { text: "Update delayed", tone: "delayed", label: "Wed 12/30 close" },
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
      header: { text: "Not covered yet", status: "unsupported" },
      change: { text: "Not covered yet", tone: "unsupported", label: "prev close" },
      lines: [
        { text: "Not covered yet", status: "unsupported" },
        { text: "Not covered yet", status: "unsupported" },
        { text: "Not covered yet", status: "unsupported" },
      ],
      leverageTag: "−3x inverse · resets daily",
      checked: null, // 확인된 줄이 없으면 하단 없음
    },
    {
      ticker: "ZZWF",
      name: "Web Test F",
      header: { text: "Update delayed", status: "delayed" },
      change: { text: "Update delayed", tone: "delayed", label: "prev close" },
      lines: [
        { text: "Update delayed", status: "delayed" },
        { text: "Update delayed", status: "delayed" },
        { text: "Update delayed", status: "delayed" },
      ],
      leverageTag: null,
      checked: null,
    },
    {
      ticker: "ZZWG",
      name: "Web Test G",
      header: { text: "1 new filing", status: "checked_found" },
      change: { text: "Update delayed", tone: "delayed", label: "prev close" },
      lines: [
        { text: "Web Test G named a new CFO (SEC filing)", status: "checked_found" },
        { text: "Update delayed", status: "delayed" },
        { text: "Update delayed", status: "delayed" },
      ],
      leverageTag: null,
      checked: "Checked 7:30 AM ET · SEC filings",
    },
  ]);
});

test("카드 헤더 4종(#63): DB 건수 열로 N new filing(s), 없음 Quiet day, 지연·축소판 Update delayed, 미지원 Not covered yet. 로그인 전·무료·Plus 모두 같고 하단은 그대로", async () => {
  const { cards } = await getDashboard();
  const FREE = { plan: "free" as const, stocks: PLUS_ALL.stocks };
  const views = [PLUS_ALL, FREE, null].map((viewer) => exposeCards(cards, viewer));
  for (const v of views) {
    expect(v.map((c) => [c.ticker, c.header])).toEqual([
      ["ZZWA", { text: "3 new filings", status: "checked_found" }],
      ["ZZWB", { text: "Quiet day", status: "checked_none" }],
      ["ZZWC", { text: "Update delayed", status: "delayed" }], // 축소판(첫 번째 줄 없음)
      ["ZZWD", { text: "Not covered yet", status: "unsupported" }],
      ["ZZWF", { text: "Update delayed", status: "delayed" }],
      ["ZZWG", { text: "1 new filing", status: "checked_found" }],
    ]);
  }
  // 무료 범위 하단은 헤더와 관계없이 전과 같다(첫·두 번째 줄의 확인 시각·범위)
  expect(views[2].map((c) => c.checked)).toEqual([
    "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar",
    "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar",
    "Checked 7:30 AM ET · Earnings and dividend calendar",
    null,
    null,
    "Checked 7:30 AM ET · SEC filings",
  ]);
  const html = renderToStaticMarkup(createElement(Dashboard, { data: { tradingDay: "Thu, Dec 31, 2099", glance: null, cards: views[2] } }));
  expect([...html.matchAll(/data-header-status="([^"]+)"[^>]*>(.*?)<\//g)].map((m) => m[2])).toEqual([
    "3 new filings",
    "Quiet day",
    "Update delayed",
    "Not covered yet",
    "Update delayed",
    "1 new filing",
  ]);
});

test("시장 한눈에(#11): 카드의 최신 거래일 행의 세 줄을 순서대로 + 하단. 보류 기록·이전 날 행은 결과 어디에도 없다", async () => {
  const data = await getDashboard();
  expect(data.glance).toEqual(GLANCE);
  const all = JSON.stringify(data);
  expect(all).not.toContain(HOLD);
  expect(all).not.toContain(EARLIER_GLANCE);
});

test("로그인 전 = 무료 범위: 세 번째 줄은 잠금만, 하단에서도 그 줄의 출처가 빠진다. 지연·미지원은 그대로", async () => {
  const cards = exposeCards((await getDashboard()).cards, null);
  // ZZWE(발행 중단)는 없다
  expect(cards.map((c) => [c.ticker, c.change!.text, c.lines, c.checked])).toEqual([
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
      [{ text: "Not covered yet", status: "unsupported" }, { text: "Not covered yet", status: "unsupported" }, { status: "locked" }],
      null,
    ],
    ["ZZWF", "Update delayed", [{ text: "Update delayed", status: "delayed" }, { text: "Update delayed", status: "delayed" }, { status: "locked" }], null],
    [
      "ZZWG",
      "Update delayed",
      [{ text: "Web Test G named a new CFO (SEC filing)", status: "checked_found" }, { text: "Update delayed", status: "delayed" }, { status: "locked" }],
      "Checked 7:30 AM ET · SEC filings",
    ],
  ]);
});

test("같은 카드를 Plus 유저와 무료 유저가 볼 때 세 번째 줄이 다르다(플랜은 user_profile.plan, 세션 유저 id로). 발행 중단한 내 종목은 두 플랜 모두 카드 없음 자리", async () => {
  const user = async (plan: "free" | "plus") => {
    const id = (await createTestUser()).id as VerifiedUserId; // 테스트에서만: 운영에서는 getVerifiedUserId만 만든다
    created.push(id);
    await ensureProfile(id, "America/New_York");
    expect(await addMyStock(id, "ZZWA")).toBe("ok");
    expect(await addMyStock(id, "ZZWE")).toBe("ok"); // 발행 중단 카드의 종목
    const { error } = await admin.from("user_profile").update({ plan }).eq("user_id", id); // 결제(#10) 전이라 서비스 역할로
    if (error) throw new Error(`plan update failed: ${error.code}`);
    return id;
  };
  const [free, plus] = [await user("free"), await user("plus")];

  // /cards 페이지와 같은 순서: 카드·내 종목을 읽고, 컴포넌트로 넘기기 전에 노출을 판단한다
  const { tradingDay, glance, cards } = await getDashboard();
  const coverage = await getCoverage();
  const page = async (id: VerifiedUserId) => {
    const my = await getMyStocks(id);
    const data = { tradingDay, glance, cards: exposeCards(cards, my) };
    return { data, html: renderToStaticMarkup(createElement(Dashboard, { data, mine: myDashboardView(data.cards, coverage, my, undefined) })) };
  };
  const [f, p] = [await page(free), await page(plus)];
  const out = renderToStaticMarkup(createElement(Dashboard, { data: { tradingDay, glance, cards: exposeCards(cards, null) } }));
  const third = (d: typeof f, ticker: string) => d.data.cards.find((c) => c.ticker === ticker)!.lines[2];

  expect(third(p, "ZZWA")).toEqual({ text: "Up 5 days in a row", status: "checked_found" }); // Plus 내 종목
  expect(third(f, "ZZWA")).toEqual({ status: "locked" }); // 무료 내 종목
  expect(third(p, "ZZWB")).toEqual({ status: "locked" }); // Plus 둘러보기
  expect(third(f, "ZZWB")).toEqual({ status: "locked" });
  // ZZWA의 세 번째 줄 문구는 픽스처에서 하나뿐: 무료 HTML에는 없다
  expect(p.html).toContain("Up 5 days in a row");
  expect(f.html).not.toContain("Up 5 days in a row");
  expect(f.html).toContain("Price facts in Plus");

  // 발행 중단 카드는 내 종목에서도 빠지고, 그 자리는 카드 없음과 같다(#16)
  for (const d of [f, p]) {
    expect(d.data.cards.map((c) => c.ticker)).toEqual(["ZZWA", "ZZWB", "ZZWC", "ZZWD", "ZZWF", "ZZWG"]);
    expect(d.html).toContain("Summary arrives tomorrow morning");
    expect(d.html).not.toContain(SUSPENDED_TEXT);
  }

  // 시장 한눈에(#11)는 로그인 전·무료·Plus가 같은 블록이고, 보류 기록은 HTML에 없다
  const section = (html: string) => html.match(/<section[^>]*aria-labelledby="market-glance"[^>]*>.*?<\/section>/)?.[0];
  expect(section(out)).toContain("CPI 8:30 AM ET · Retail sales 10:00 AM ET");
  expect(section(f.html)).toBe(section(out));
  expect(section(p.html)).toBe(section(out));
  for (const html of [out, f.html, p.html]) expect(html).not.toContain(HOLD);
});

test("가격 표시 off(#56)면 DB에 등락률·가격 사실·어제 마감 값이 있어도 화면 모델·HTML에 없다(Plus 내 종목·로그인 전 모두)", async () => {
  vi.stubEnv("PRICE_DISPLAY", undefined);
  const { tradingDay, glance, cards } = await getDashboard();
  expect(glance).toEqual({ lines: GLANCE.lines.slice(1), checked: "Checked 7:20 AM ET · Economic calendar" });
  for (const viewer of [PLUS_ALL, null]) {
    const data = { tradingDay, glance, cards: exposeCards(cards, viewer) };
    expect(data.cards.map((c) => [c.ticker, Object.keys(c).sort(), c.lines.length])).toEqual(
      ["ZZWA", "ZZWB", "ZZWC", "ZZWD", "ZZWF", "ZZWG"].map((t) => [t, ["checked", "header", "leverageTag", "lines", "name", "ticker"], 2]),
    );
    const props = JSON.stringify(data);
    const html = renderToStaticMarkup(createElement(Dashboard, { data }));
    for (const price of ["+1.3%", "\u22122.0%", "Wed 12/30 close", "prev close", "Up 5 days in a row", "No additional price highlights", "Daily prices", CLOSE, "SPY", "Price facts in Plus"]) {
      expect(props, price).not.toContain(price);
      expect(html, price).not.toContain(price);
    }
    expect(html).toContain("Web Test A reported Q3 results (SEC filing)"); // 두 줄은 그대로
  }
});

test("고르기 검색(#58): 로컬 커버 범위(티커순)를 서버 메모리에서 거른다. 이상한 검색어도 결과 없음일 뿐 조회는 같다", async () => {
  const coverage = await getCoverage(); // 검색어를 받지 않는 조회: SQL·PostgREST 필터에 들어갈 길이 없다
  const my = { stocks: [{ ticker: "ZZWA", name: "Web Test A", locked: false }], swapsLeft: 3 };
  const pick = (q: unknown) => myDashboardView([], coverage, my, undefined, q).pickable.map((s) => s.ticker);
  expect(pick("zzw")).toEqual(["ZZWB", "ZZWC", "ZZWD", "ZZWE", "ZZWF", "ZZWG"]); // 티커로 시작, 티커순, 내 종목 ZZWA 빠짐
  expect(pick("ZZWC")).toEqual(["ZZWC"]);
  expect(pick("web-test e")).toEqual(["ZZWE"]); // 이름 정규화
  for (const q of ["%", "*", "'; DROP TABLE coverage;--", "or(ticker.eq.ZZWB)", "name.ilike.*"]) expect(pick(q), q).toEqual([]);
  expect(await getCoverage()).toEqual(coverage);
});
