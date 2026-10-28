/** 줄 노출 판단(#9, HANDOFF 3-2). DB 없이 저장된 카드 → 화면 모델. 실제 DB 경로는 cards.db.test.ts */
import { randomUUID } from "node:crypto";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

import { Dashboard } from "@/components/dashboard";
import { myDashboardView, type CardView } from "@/lib/card-view";
import type { StoredCard, StoredLine } from "@/server/cards";
import { exposeCards } from "@/server/exposure";
import type { MyStocks } from "@/server/my-stocks";

const AT = "2026-10-16T11:30:00Z"; // 7:30 AM ET
const PRICE_AT = "2026-10-16T11:10:00Z"; // 7:10 AM ET: 가장 이른 시각. 잠기면 하단에서도 빠져야 한다

const line = (text: string, status: StoredLine["status"], source_scope: string | null, checked_at = AT): StoredLine => ({
  text,
  status,
  checked_at,
  source_scope,
});

const THIRD = {
  "사실 있음": line("Up 5 days in a row", "checked_found", "Daily prices", PRICE_AT),
  "사실 없음": line("No additional price highlights", "checked_none", "Daily prices", PRICE_AT),
  지연: line("Update delayed", "delayed", "Daily prices", PRICE_AT),
};

const stored = (third: StoredLine | null, over: Partial<StoredCard> = {}): StoredCard => ({
  ticker: "AAPL",
  name: "Apple Inc.",
  change: { text: "+1.3%", tone: "up" },
  lines: [
    line("Apple reported Q3 results (SEC filing)", "checked_found", "SEC filings"),
    line("No confirmed events found", "checked_none", "Earnings and dividend calendar"),
    third,
  ],
  leverageTag: null,
  ...over,
});

const my = (plan: MyStocks["plan"], ticker: string, locked = false): MyStocks => ({
  plan,
  stocks: [{ ticker, name: `${ticker} name`, locked }],
  swapsLeft: plan === "plus" ? null : 3,
});

const VIEWERS: [string, MyStocks | null, boolean][] = [
  ["로그인 전", null, false],
  ["무료 내 종목", my("free", "AAPL"), false],
  ["무료 둘러보기", my("free", "MSFT"), false],
  ["Plus 내 종목", my("plus", "AAPL"), true],
  ["Plus 둘러보기", my("plus", "MSFT"), false],
];

const FIRST_TWO = [
  { text: "Apple reported Q3 results (SEC filing)", status: "checked_found" },
  { text: "No confirmed events found", status: "checked_none" },
] as const;

/** 무료 범위: 세 번째 줄이 무엇이든 같은 결과(글자·상태·확인 시각·출처가 새지 않는다) */
const FREE: CardView = {
  ticker: "AAPL",
  name: "Apple Inc.",
  change: { text: "+1.3%", tone: "up" },
  lines: [...FIRST_TWO, { status: "locked" }],
  leverageTag: null,
  checked: "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar",
};

const FULL: Record<keyof typeof THIRD, CardView> = {
  "사실 있음": {
    ...FREE,
    lines: [...FIRST_TWO, { text: "Up 5 days in a row", status: "checked_found" }],
    checked: "Checked 7:10 AM ET · SEC filings · Earnings and dividend calendar · Daily prices",
  },
  "사실 없음": {
    ...FREE,
    lines: [...FIRST_TWO, { text: "No additional price highlights", status: "checked_none" }],
    checked: "Checked 7:10 AM ET · SEC filings · Earnings and dividend calendar · Daily prices",
  },
  지연: { ...FREE, lines: [...FIRST_TWO, { text: "Update delayed", status: "delayed" }] }, // 지연 줄은 하단에 넣지 않는다
};

describe("exposeCards: 세 줄 전부는 Plus 유저의 내 종목 카드뿐", () => {
  for (const [who, viewer, full] of VIEWERS) {
    for (const [kind, third] of Object.entries(THIRD) as [keyof typeof THIRD, StoredLine][]) {
      test(`${who} × 세 번째 줄 ${kind} → ${full ? "세 줄 전부" : "무료 범위(잠금)"}`, () => {
        expect(exposeCards([stored(third)], viewer)).toEqual([full ? FULL[kind] : FREE]);
      });
    }
  }

  test("Plus여도 잠긴 내 종목은 무료 범위(둘러보기와 같은 자리)", () => {
    expect(exposeCards([stored(THIRD["사실 있음"])], my("plus", "AAPL", true))).toEqual([FREE]);
  });

  test("카드마다 따로 판단: Plus 유저의 내 종목만 열리고 같은 화면의 둘러보기 카드는 잠긴다", () => {
    const cards = [stored(THIRD["사실 있음"]), stored(THIRD["사실 있음"], { ticker: "MSFT", name: "Microsoft" })];
    const [mine, browse] = exposeCards(cards, my("plus", "AAPL"));
    expect(mine.lines[2]).toEqual({ text: "Up 5 days in a row", status: "checked_found" });
    expect(browse.lines[2]).toEqual({ status: "locked" });
  });

  test("데이터 상태(지연·미지원·축소판)와 레버리지 태그는 플랜과 관계없이 그대로", () => {
    const card = stored(THIRD["사실 있음"], {
      change: { text: "Update delayed", tone: "delayed" },
      lines: [null, line("Not covered yet", "unsupported", null), THIRD["사실 있음"]],
      leverageTag: "3x · resets daily",
    });
    for (const [who, viewer, full] of VIEWERS) {
      const [view] = exposeCards([card], viewer);
      expect(view.change, who).toEqual({ text: "Update delayed", tone: "delayed" });
      expect(view.lines.slice(0, 2), who).toEqual([
        { text: "Update delayed", status: "delayed" }, // 축소판의 첫 번째 줄
        { text: "Not covered yet", status: "unsupported" },
      ]);
      expect(view.leverageTag, who).toBe("3x · resets daily");
      // 확인된 줄은 세 번째 줄뿐: 잠기면 하단도 없다
      expect(view.checked, who).toBe(full ? "Checked 7:10 AM ET · Daily prices" : null);
    }
  });

  test("화면 모델은 허용한 키만(화이트리스트): 저장 카드에 다른 값(방향 의견 등)이 붙어 와도 옮기지 않는다", () => {
    const extra = {
      ...stored({ ...THIRD["사실 있음"], direction: "bullish" } as StoredLine),
      direction: "bullish",
      change: { text: "+1.3%", tone: "up", rating: "buy" },
    } as StoredCard;
    for (const [who, viewer] of VIEWERS) {
      const [view] = exposeCards([extra], viewer);
      expect(Object.keys(view).sort(), who).toEqual(["change", "checked", "leverageTag", "lines", "name", "ticker"]);
      expect(Object.keys(view.change).sort(), who).toEqual(["text", "tone"]);
      for (const l of view.lines) expect(Object.keys(l).sort(), who).toEqual(l.status === "locked" ? ["status"] : ["status", "text"]);
      expect(JSON.stringify(view), who).not.toMatch(/bullish|buy/);
    }
  });
});

describe("잠긴 줄의 원문은 화면 모델(RSC props)과 HTML에 없다", () => {
  const CANARY = `canary-price-fact-${randomUUID()}`;
  const SCOPE = `canary-scope-${randomUUID()}`;
  const card = stored(line(CANARY, "checked_found", SCOPE, "2026-10-16T10:07:00Z")); // 6:07 AM ET
  const coverage = [{ ticker: "AAPL", name: "Apple Inc." }];

  const render = (viewer: MyStocks | null) => {
    const cards = exposeCards([card], viewer);
    const data = { tradingDay: "Fri, Oct 16, 2026", cards };
    const mine = viewer ? myDashboardView(cards, coverage, viewer, undefined) : undefined;
    return { props: JSON.stringify({ data, mine }), html: renderToStaticMarkup(<Dashboard data={data} mine={mine} />) };
  };

  for (const [who, viewer, full] of VIEWERS) {
    test(`${who}: ${full ? "원문이 보인다(대조군)" : "원문·출처·시각 없음, Price facts in Plus"}`, () => {
      const { props, html } = render(viewer);
      for (const secret of [CANARY, SCOPE, "6:07 AM"]) {
        expect(props.includes(secret), secret).toBe(full);
        expect(html.includes(secret), secret).toBe(full);
      }
      expect(html.includes("Price facts in Plus")).toBe(!full);
    });
  }
});
