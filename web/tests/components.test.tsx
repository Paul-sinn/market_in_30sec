import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

import ErrorPage from "@/app/error";
import RootLayout from "@/app/layout";
import { Dashboard } from "@/components/dashboard";
import { StockCard } from "@/components/stock-card";
import type { CardView } from "@/lib/card-view";

// next/font/google은 빌드 때 글꼴을 받는다. 레이아웃 렌더 테스트에서는 변수 이름만 준다
vi.mock("next/font/google", () => ({
  Fira_Sans: () => ({ variable: "font-sans-var" }),
  Fira_Code: () => ({ variable: "font-mono-var" }),
}));

const card = (over: Partial<CardView> = {}): CardView => ({
  ticker: "AAPL",
  name: "Apple Inc.",
  change: { text: "+1.3%", tone: "up" },
  lines: [
    { text: "Apple reported Q3 results (SEC filing)", status: "checked_found" },
    { text: "Earnings Thu 10/29 after close (D-13)", status: "checked_found" },
    { text: "Up 5 days in a row", status: "checked_found" },
  ],
  leverageTag: null,
  checked: "Checked 7:30 AM ET · SEC filings · Daily prices",
  ...over,
});

const text = (html: string) => html.replace(/<[^>]+>/g, "");

/** 줄마다 [상태, 보이는 문구] */
const lines = (html: string) =>
  [...html.matchAll(/<li[^>]*data-status="([^"]+)"[^>]*>(.*?)<\/li>/g)].map((m) => [m[1], text(m[2])]);

const change = (html: string) => {
  const m = html.match(/data-tone="([^"]+)"[^>]*>(.*?)<\//);
  return m && [m[1], m[2]];
};

/** data-tone / data-status 요소의 class */
const classOf = (html: string, attr: string) => html.match(new RegExp(`${attr}"[^>]*class="([^"]+)"`))?.[1].split(" ") ?? [];

describe("StockCard", () => {
  test("티커·종목명·등락률·세 줄·하단 확인 범위", () => {
    const html = renderToStaticMarkup(<StockCard card={card()} />);
    expect(text(html)).toContain("AAPL");
    expect(text(html)).toContain("Apple Inc.");
    expect(change(html)).toEqual(["up", "+1.3%"]);
    expect(lines(html)).toEqual([
      ["checked_found", "Apple reported Q3 results (SEC filing)"],
      ["checked_found", "Earnings Thu 10/29 after close (D-13)"],
      ["checked_found", "Up 5 days in a row"],
    ]);
    expect(text(html)).toContain("Checked 7:30 AM ET · SEC filings · Daily prices");
  });

  test("상태별 문구를 숨기지 않고 그린다(확인함·없음 / 지연 / 미지원)", () => {
    const html = renderToStaticMarkup(
      <StockCard
        card={card({
          change: { text: "−2.0%", tone: "down" },
          lines: [
            { text: "No new SEC filings found", status: "checked_none" },
            { text: "Update delayed", status: "delayed" },
            { text: "Not covered yet", status: "unsupported" },
          ],
        })}
      />,
    );
    expect(change(html)).toEqual(["down", "−2.0%"]);
    expect(lines(html)).toEqual([
      ["checked_none", "No new SEC filings found"],
      ["delayed", "Update delayed"],
      ["unsupported", "Not covered yet"],
    ]);
  });

  test("등락률 지연·미지원, 보합", () => {
    for (const c of [
      { text: "Update delayed", tone: "delayed" },
      { text: "Not covered yet", tone: "unsupported" },
      { text: "0.0%", tone: "flat" },
    ] as const) {
      expect(change(renderToStaticMarkup(<StockCard card={card({ change: c })} />))).toEqual([c.tone, c.text]);
    }
  });

  test("등락률 색: 상승 초록(up)·하락 빨강(down)·보합 중립, 지연·미지원은 흐림", () => {
    const tone = (c: CardView["change"]) => classOf(renderToStaticMarkup(<StockCard card={card({ change: c })} />), 'data-tone="' + c.tone);
    expect(tone({ text: "+1.3%", tone: "up" })).toContain("text-up");
    expect(tone({ text: "\u22121.3%", tone: "down" })).toContain("text-down");
    const flat = tone({ text: "0.0%", tone: "flat" });
    expect(flat).toContain("text-foreground");
    expect(flat).not.toContain("text-up");
    expect(flat).not.toContain("text-down");
    expect(tone({ text: "Update delayed", tone: "delayed" })).toContain("text-muted");
    expect(tone({ text: "Not covered yet", tone: "unsupported" })).toContain("text-muted");
  });

  test("줄 색: 확인함·있음만 본문색, 나머지는 흐림. 지연 아이콘은 경고색", () => {
    const html = renderToStaticMarkup(
      <StockCard
        card={card({
          lines: [
            { text: "a", status: "checked_found" },
            { text: "No confirmed events found", status: "checked_none" },
            { text: "Update delayed", status: "delayed" },
          ],
        })}
      />,
    );
    expect(classOf(html, 'data-status="checked_found')).toContain("text-foreground");
    expect(classOf(html, 'data-status="checked_none')).toContain("text-muted");
    expect(classOf(html, 'data-status="delayed')).toContain("text-muted");
    const unsupported = renderToStaticMarkup(<StockCard card={card({ lines: [{ text: "Not covered yet", status: "unsupported" }] })} />);
    expect(classOf(unsupported, 'data-status="unsupported')).toContain("text-muted");
    expect(html).toMatch(/data-status="delayed"[^>]*><svg[^>]*class="[^"]*text-warning/);
  });

  test("등락률 아래 기준 라벨 Last close (값이 없어도)", () => {
    for (const c of [
      { text: "+1.3%", tone: "up" },
      { text: "Update delayed", tone: "delayed" },
    ] as const) {
      const html = renderToStaticMarkup(<StockCard card={card({ change: c })} />);
      expect(text(html)).toContain(`${c.text}Last close`); // 태그를 지우면 값 바로 뒤에 라벨
    }
  });

  test("레버리지 태그는 있을 때만", () => {
    expect(text(renderToStaticMarkup(<StockCard card={card({ leverageTag: "−3x inverse · resets daily" })} />))).toContain(
      "−3x inverse · resets daily",
    );
    expect(renderToStaticMarkup(<StockCard card={card()} />)).not.toContain("resets daily");
  });

  test("확인 시각이 없으면 하단 줄을 그리지 않는다", () => {
    expect(text(renderToStaticMarkup(<StockCard card={card({ checked: null })} />))).not.toContain("Checked");
  });
});

describe("Dashboard", () => {
  test("거래일 날짜 + 카드를 받은 순서대로", () => {
    const html = renderToStaticMarkup(
      <Dashboard data={{ tradingDay: "Fri, Oct 16, 2026", cards: [card(), card({ ticker: "MSFT", name: "Microsoft" })] }} />,
    );
    expect(html).toMatch(/<h1[^>]*>.*Fri, Oct 16, 2026.*<\/h1>/);
    expect(text(html).indexOf("AAPL")).toBeLessThan(text(html).indexOf("MSFT"));
    expect(text(html)).not.toContain("No cards yet");
  });

  test("카드 없음은 고정 문구", () => {
    const html = renderToStaticMarkup(<Dashboard data={{ tradingDay: null, cards: [] }} />);
    expect(html).toMatch(/<h1[^>]*>No cards yet<\/h1>/);
  });
});

test("모든 페이지(루트 레이아웃) 하단에 Not investment advice", () => {
  const html = renderToStaticMarkup(
    RootLayout({ children: <p>page</p>, params: Promise.resolve({}) } as unknown as LayoutProps<"/">),
  );
  expect(html).toMatch(/<p>page<\/p>.*<footer[^>]*>Not investment advice<\/footer>/);
});

test("DB 읽기 실패 화면: 고정 문구 + 다시 시도. 에러 내용은 그리지 않는다", () => {
  const html = renderToStaticMarkup(
    <ErrorPage error={new Error("stock_card read failed: canary-secret http://127.0.0.1:54321")} retry={() => {}} />,
  );
  expect(text(html)).toContain("Cards could not be loaded");
  expect(html).toMatch(/<button[^>]*type="button"[^>]*>Try again<\/button>/);
  expect(html).not.toMatch(/canary-secret|127\.0\.0\.1|stock_card/);
});

test("Try again을 누르면 retry가 불린다(#24 qa G1)", () => {
  // DOM 없이: 돌려받은 엘리먼트 트리에서 버튼을 찾아 클릭 핸들러를 부른다
  const retry = vi.fn();
  type El = { type: unknown; props: { children?: unknown; onClick?: () => void } };
  const find = (n: unknown): El | undefined => {
    if (Array.isArray(n)) return n.map(find).find(Boolean);
    const el = n as El | null;
    if (!el || typeof el !== "object" || !("props" in el)) return undefined;
    return el.type === "button" ? el : find(el.props.children);
  };
  const button = find(ErrorPage({ error: new Error("x"), retry }));
  expect(button?.props.children).toBe("Try again");
  expect(retry).not.toHaveBeenCalled();
  button!.props.onClick!();
  expect(retry).toHaveBeenCalledTimes(1);
});
