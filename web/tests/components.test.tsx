import { Inter } from "next/font/google";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

import LegalLayout from "@/app/(legal)/layout";
import Privacy from "@/app/(legal)/privacy/page";
import Terms from "@/app/(legal)/terms/page";
import ErrorPage from "@/app/cards/error";
import CardsLayout from "@/app/cards/layout";
import RootLayout from "@/app/layout";
import Landing from "@/app/page";
import { AuthControl } from "@/components/auth-control";
import { Dashboard, DashboardSkeleton } from "@/components/dashboard";
import { MarketGlance } from "@/components/market-glance";
import { NotifyMe, type NotifyMeView } from "@/components/notify-me";
import { PastCards } from "@/components/past-cards";
import { SiteFooter } from "@/components/site-footer";
import { StockCard } from "@/components/stock-card";
import { TimezoneField } from "@/components/timezone-field";
import { myDashboardView, type CardView, type GlanceView, type MyDashboardView, type PastCardsView } from "@/lib/card-view";
import { SIGN_IN, SIGN_IN_FAILED, SIGN_OUT } from "@/lib/copy";

// next/font/google은 빌드 때 글꼴을 받는다. 레이아웃 렌더 테스트에서는 변수 이름만 준다(Inter 말고 다른 글꼴을 부르면 실패)
vi.mock("next/font/google", () => ({ Inter: vi.fn(() => ({ variable: "font-sans-var" })) }));

const card = (over: Partial<CardView> = {}): CardView => ({
  ticker: "AAPL",
  name: "Apple Inc.",
  header: { text: "1 new filing", status: "checked_found" },
  change: { text: "+1.3%", tone: "up", label: "Thu 10/15 close" },
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

/** 카드 헤더(#63): [상태, 문구] */
const cardHeader = (html: string) => {
  const m = html.match(/data-header-status="([^"]+)"[^>]*>(.*?)<\//);
  return m && [m[1], m[2]];
};
/** 카드 머리(<header>)의 보이는 글자 */
const head = (html: string) => text(html.match(/<header\b.*?<\/header>/)?.[0] ?? "");

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
          change: { text: "−2.0%", tone: "down", label: "Thu 10/15 close" },
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
      { text: "Update delayed", tone: "delayed", label: "Thu 10/15 close" },
      { text: "Not covered yet", tone: "unsupported", label: "Thu 10/15 close" },
      { text: "0.0%", tone: "flat", label: "Thu 10/15 close" },
    ] as const) {
      expect(change(renderToStaticMarkup(<StockCard card={card({ change: c })} />))).toEqual([c.tone, c.text]);
    }
  });

  test("등락률 색: 상승 초록(up)·하락 빨강(down)·보합 중립, 지연·미지원은 흐림", () => {
    const tone = (c: NonNullable<CardView["change"]>) => classOf(renderToStaticMarkup(<StockCard card={card({ change: c })} />), 'data-tone="' + c.tone);
    expect(tone({ text: "+1.3%", tone: "up", label: "Thu 10/15 close" })).toContain("text-up");
    expect(tone({ text: "\u22121.3%", tone: "down", label: "Thu 10/15 close" })).toContain("text-down");
    const flat = tone({ text: "0.0%", tone: "flat", label: "Thu 10/15 close" });
    expect(flat).toContain("text-foreground");
    expect(flat).not.toContain("text-up");
    expect(flat).not.toContain("text-down");
    expect(tone({ text: "Update delayed", tone: "delayed", label: "Thu 10/15 close" })).toContain("text-muted");
    expect(tone({ text: "Not covered yet", tone: "unsupported", label: "Thu 10/15 close" })).toContain("text-muted");
  });

  test("줄 색: 확인함·있음만 본문색, 나머지는 흐림", () => {
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
  });

  test("잠긴 세 번째 줄(#9·#67): 건수만 받아 고정 문구(복수·단수·건수 없음)를 흐리게, 줄을 숨기지 않는다", () => {
    for (const [locked, label] of [
      [{ status: "locked", count: 2 }, "2 related updates in Plus"],
      [{ status: "locked", count: 1 }, "1 related update in Plus"],
      [{ status: "locked" }, "Related updates in Plus"], // 0건·지연(무료에게는 둘을 구분하지 않는다)
    ] as const) {
      const html = renderToStaticMarkup(<StockCard card={card({ lines: [...card().lines.slice(0, 2), locked] })} />);
      expect(lines(html)).toEqual([
        ["checked_found", "Apple reported Q3 results (SEC filing)"],
        ["checked_found", "Earnings Thu 10/29 after close (D-13)"],
        ["locked", label],
      ]);
      expect(classOf(html, 'data-status="locked')).toContain("text-muted");
      expect(html).not.toContain("Price facts in Plus");
    }
  });

  test("등락률 옆 기준 라벨은 화면 모델의 label 그대로: 종가 날짜(#16) 또는 옛 카드의 prev close, 값이 없어도(#27 시안)", () => {
    for (const c of [
      { text: "+1.3%", tone: "up", label: "Thu 10/15 close" },
      { text: "Update delayed", tone: "delayed", label: "Thu 10/15 close" },
      { text: "+1.3%", tone: "up", label: "prev close" },
    ] as const) {
      const html = renderToStaticMarkup(<StockCard card={card({ change: c })} />);
      expect(text(html)).toContain(`${c.text}${c.label}`); // 태그를 지우면 값 바로 뒤에 라벨
    }
    expect(text(renderToStaticMarkup(<StockCard card={card()} />))).not.toContain("prev close");
  });

  test("등락률 키가 없는 카드(가격 표시 off, #56)는 머리에 티커·종목명만, 등락률·라벨 없이 두 줄", () => {
    const off = card({ lines: card().lines.slice(0, 2), checked: "Checked 7:30 AM ET · SEC filings" });
    delete off.change;
    const html = renderToStaticMarkup(<StockCard card={off} />);
    expect(change(html)).toBeNull(); // data-tone 요소 없음
    expect(text(html)).not.toMatch(/Thu 10\/15 close|prev close|%/);
    expect(text(html)).toContain("AAPL");
    expect(text(html)).toContain("Apple Inc.");
    expect(lines(html)).toEqual([
      ["checked_found", "Apple reported Q3 results (SEC filing)"],
      ["checked_found", "Earnings Thu 10/29 after close (D-13)"],
    ]);
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

  test("카드 머리에 헤더 문구를 상태 색으로 그리고 하단 확인 줄은 그대로(#63)", () => {
    for (const [h, color] of [
      [{ text: "3 new filings", status: "checked_found" }, "text-foreground"],
      [{ text: "Quiet day", status: "checked_none" }, "text-muted"],
      [{ text: "Update delayed", status: "delayed" }, "text-muted"],
      [{ text: "Not covered yet", status: "unsupported" }, "text-muted"],
    ] as const) {
      const html = renderToStaticMarkup(<StockCard card={card({ header: h })} />);
      expect(cardHeader(html), h.text).toEqual([h.status, h.text]);
      expect(classOf(html, `data-header-status="${h.status}`), h.text).toContain(color);
      expect(head(html), h.text).toContain(h.text); // 머리 안
      expect(text(html), h.text).toContain("Checked 7:30 AM ET · SEC filings · Daily prices");
    }
  });

  test("머리 순서: 티커 → 종목명 → 헤더 → (가격 표시 on일 때만) 등락률 → 종가 라벨(#63)", () => {
    expect(head(renderToStaticMarkup(<StockCard card={card()} />))).toBe("AAPLApple Inc.1 new filing+1.3%Thu 10/15 close");
    const off = card();
    delete off.change;
    expect(head(renderToStaticMarkup(<StockCard card={off} />))).toBe("AAPLApple Inc.1 new filing");
  });

  test("헤더가 null인 카드(#63 전)는 머리에 티커·종목명만(가격 표시 on이면 등락률은 그대로)", () => {
    const html = renderToStaticMarkup(<StockCard card={card({ header: null })} />);
    expect(cardHeader(html)).toBeNull();
    expect(head(html)).toBe("AAPLApple Inc.+1.3%Thu 10/15 close");
  });

  test("알아두기(#66): 첫 번째 줄 <li> 안, 줄 글자 아래 보조 문단 Did you know: … (Annual report). 줄 수는 그대로", () => {
    const quiet = card({
      header: { text: "Quiet day", status: "checked_none" },
      lines: [{ text: "No new SEC filings found", status: "checked_none" }, ...card().lines.slice(1)],
      quietFact: "Apple makes phones, computers and wearables",
    });
    const html = renderToStaticMarkup(<StockCard card={quiet} />);
    const items = [...html.matchAll(/<li\b[^>]*>(.*?)<\/li>/g)].map((m) => m[1]);
    expect(items).toHaveLength(3);
    const fact = items[0].match(/<p data-quiet-fact[^>]*class="([^"]+)"[^>]*>(.*?)<\/p>/);
    expect(fact?.[2]).toBe("Did you know: Apple makes phones, computers and wearables (Annual report)");
    expect(fact?.[1].split(" ")).toEqual(expect.arrayContaining(["text-sm", "text-muted"])); // 본문 14px, surface 위 5.2:1
    expect(text(items[0]).startsWith("No new SEC filings found")).toBe(true); // 줄 글자 먼저(읽는 순서)
    expect(html.match(/data-quiet-fact/g)).toHaveLength(1);
  });

  test("알아두기가 없으면(키 없음) data-quiet-fact 없음", () => {
    expect(renderToStaticMarkup(<StockCard card={card()} />)).not.toContain("data-quiet-fact");
    expect(renderToStaticMarkup(<StockCard card={card()} />)).not.toContain("Did you know");
  });
});

describe("Dashboard", () => {
  test("거래일 날짜 + 카드를 받은 순서대로", () => {
    const html = renderToStaticMarkup(
      <Dashboard data={{ tradingDay: "Fri, Oct 16, 2026", glance: null, cards: [card(), card({ ticker: "MSFT", name: "Microsoft" })] }} />,
    );
    expect(html).toMatch(/<h1[^>]*>.*Fri, Oct 16, 2026.*<\/h1>/);
    expect(text(html).indexOf("AAPL")).toBeLessThan(text(html).indexOf("MSFT"));
    expect(text(html)).not.toContain("No cards yet");
  });

  test("카드 없음은 고정 문구", () => {
    const html = renderToStaticMarkup(<Dashboard data={{ tradingDay: null, glance: null, cards: [] }} />);
    expect(html).toMatch(/<h1[^>]*>No cards yet<\/h1>/);
    expect(text(html)).not.toContain("Market at a glance"); // 카드가 없으면 시장 한눈에 블록도 없다(#11)
  });
});

test("모든 페이지(루트 레이아웃) 하단에 Not investment advice. 하단 링크는 랜딩 앵커 또는 약관·개인정보 페이지로(절대 경로)", () => {
  const html = renderToStaticMarkup(
    RootLayout({ children: <p>page</p>, params: Promise.resolve({}) } as unknown as LayoutProps<"/">),
  );
  expect(html).toMatch(/<p>page<\/p>.*<footer[^>]*>.*Not investment advice.*<\/footer>/);
  // Inter: html에 next/font 변수 클래스, body가 그 변수를 쓰는 font-sans, CSS의 font-sans가 같은 변수 이름(--font-inter)
  expect(vi.mocked(Inter)).toHaveBeenCalledWith(expect.objectContaining({ variable: "--font-inter" }));
  expect(html.match(/<html[^>]*class="([^"]*)"/)?.[1].split(" ")).toContain("font-sans-var");
  expect(html.match(/<body[^>]*class="([^"]*)"/)?.[1].split(" ")).toContain("font-sans");
  expect(readFileSync(join(__dirname, "..", "src", "app", "globals.css"), "utf8")).toMatch(/--font-sans: var\(--font-inter\),/);
  const footer = html.slice(html.indexOf("<footer"));
  expect(hrefs(footer).length).toBeGreaterThan(0);
  for (const h of hrefs(footer)) expect(h, h).toMatch(/^\/((#[a-z]+)?|terms(#[a-z-]+)?|privacy(#[a-z-]+)?)$/); // 어느 경로에서 눌러도 같은 곳
  // 가격 표시가 꺼져 있어 사실이 아닌 가격 문장은 없다(#62, 스토리 24). 아레나는 웹에 없다(#70)
  expect(text(footer)).toContain("For informational purposes only. Not investment advice.");
  expect(text(footer)).not.toMatch(/Prices are daily closes|SPY|QQQ|Arena|virtual money/);
});

test("하단 Product: 랜딩 앵커 셋(#70, 웹에 없는 알림·위젯·아레나 칸 없음). Legal: Terms of service → /terms, Privacy → /privacy. Support: Request a stock·Contact → /terms#contact, Delete my account → /privacy#delete(#62)", () => {
  const html = renderToStaticMarkup(<SiteFooter />);
  expect([...html.matchAll(/<h2[^>]*>([^<]*)<\/h2>/g)].map((m) => m[1])).toEqual(["Product", "Support", "Legal"]);
  const links = Object.fromEntries([...html.matchAll(/<a[^>]*href="([^"]*)"[^>]*>([^<]*)<\/a>/g)].map((m) => [m[2], m[1]]));
  expect(Object.keys(links)).toHaveLength(8);
  expect(links).toMatchObject({
    "The card": "/#card",
    "How it works": "/#how",
    Plus: "/#plus",
    "Terms of service": "/terms",
    Privacy: "/privacy",
    "Request a stock": "/terms#contact",
    Contact: "/terms#contact",
    "Delete my account": "/privacy#delete",
  });
  // 가리키는 절 id가 페이지에 있다
  expect(renderToStaticMarkup(<Terms />)).toContain('id="contact"');
  expect(renderToStaticMarkup(<Privacy />)).toContain('id="delete"');
});

/** 링크·버튼의 href / class */
const hrefs = (html: string) => [...html.matchAll(/<a[^>]*href="([^"]*)"/g)].map((m) => m[1]);
const targets = (html: string) => [...html.matchAll(/<(a|button)\b[^>]*>/g)].map((m) => m[0]);

describe("랜딩 / (#27 사용자 시안, #70 1단계 기능)", () => {
  const html = renderToStaticMarkup(<Landing />);
  const plain = (h: string) => text(h).replaceAll("&#x27;", "'").replaceAll("&amp;", "&").replaceAll("&quot;", '"');
  const page = plain(html);
  const footerHtml = renderToStaticMarkup(<SiteFooter />);
  /** [href, 보이는 글자] */
  const links = (h: string) => [...h.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/g)].map((m) => [m[1], plain(m[2])]);

  test("섹션 + 머리 메뉴·하단 Product 앵커가 가리키는 섹션이 있다", () => {
    for (const id of ["top", "card", "how", "plus", "get"]) expect(html).toContain(`id="${id}"`);
    for (const h of hrefs(html).filter((h) => h.startsWith("#"))) expect(html, h).toContain(`id="${h.slice(1)}"`);
    const footerAnchors = hrefs(footerHtml).filter((h) => h.startsWith("/#"));
    expect(footerAnchors.length).toBeGreaterThan(0);
    for (const h of footerAnchors) expect(html, h).toContain(`id="${h.slice(2)}"`);
  });

  test("지금 제공하지 않는 것을 약속하지 않는다(#70): 가격·체험·결제, 아레나, Apple 로그인, 위젯·푸시·아침 알림, 무제한, 미리보기 안내", () => {
    for (const t of [page, plain(footerHtml)]) {
      expect(t).not.toMatch(/\$|trial|billed|\/ year|yearly|monthly|per month|subscribe|upgrade|checkout|pricing/i);
      expect(t).not.toMatch(/arena|agents?\b|mock trad|virtual money|verdict|hits – misses/i);
      expect(t).not.toMatch(/with Apple|Apple or Google|App Store|iPhone/i);
      expect(t).not.toMatch(/widget|lock screen|push|notification|morning time|8:00/i);
      expect(t).not.toMatch(/unlimited|removes the limit|no limit|preview|monthly report|vs\. S&P/i);
    }
    expect(html).not.toMatch(/id="(arena|pricing)"/);
  });

  test("로그인은 Google만(약관 accounts 절과 같다)", () => {
    expect(page).toContain("Sign in with Google");
  });

  test("샘플 카드: 무료로 보이는 실제 카드 문구(#62·#63·#66·#67·#69). 잠금은 같은 글자의 /plus 링크, 탭 폼 없음", () => {
    expect(lines(html).map(([s, t]) => [s, t.replace(/Did you know: .*$/, "")])).toEqual([
      ["checked_found", "Apple named a new CFO +2 more (SEC filing)"],
      ["checked_found", "Earnings Thu 10/15 after close (est.) (D-2)"],
      ["locked", "2 related updates in Plus"],
      ["checked_none", "No new SEC filings found"], // ETF 조용한 날: 헤더 Quiet day와 같은 첫 번째 줄
      ["unsupported", "Not covered yet"],
      ["unsupported", "Not covered yet"], // ETF는 연관 소식이 없어 모든 viewer에게 미지원
      ["checked_none", "No new SEC filings found"],
      ["checked_none", "No confirmed events found"],
      ["locked", "Related updates in Plus"], // 0건·지연은 건수 없이
    ]);
    // 카드 헤더(#63): 첫 번째 줄에 맞춘 고정 문구(AAPL은 1등 + 2 more)
    expect([...html.matchAll(/data-header-status="([^"]+)"[^>]*>(.*?)<\//g)].map((m) => [m[1], m[2]])).toEqual([
      ["checked_found", "3 new filings"],
      ["checked_none", "Quiet day"],
      ["checked_none", "Quiet day"],
    ]);
    // 알아두기(#66): 주식의 조용한 날에만(ETF에는 없다)
    expect([...html.matchAll(/data-quiet-fact[^>]*>(.*?)<\/p>/g)].map((m) => plain(m[1]))).toEqual([
      "Did you know: Coca-Cola makes beverage concentrates and syrups for bottling partners (Annual report)",
    ]);
    // 잠긴 자리(#69, ETF 없음)·세 번째 줄 잠금(#67)은 /plus 링크. 탭 폼이면 랜딩 방문이 탭 합계에 섞인다
    expect(html).not.toContain("<form");
    expect(links(html).filter(([h]) => h === "/plus").map(([, t]) => t)).toEqual([
      "2 related updates in Plus",
      "Earnings summary in Plus",
      "Related updates in Plus",
      "Insider and big holder filings in Plus",
      "About Plus",
    ]);
    // 카드마다 하단 확인 줄(잠긴 줄은 범위에 넣지 않는다, 실제 카드와 같은 모양)
    expect(page.match(/Checked 7:30 AM ET · SEC filings/g)).toHaveLength(3);
    for (const old of ["No major news today", "No events in next 2 weeks", "No notable price moves", "Top holdings", "No related filings found", "prev close"]) {
      expect(page).not.toContain(old);
    }
    expect(page).toContain("Sample cards. Figures are illustrative.");
  });

  test("랜딩에 가격 숫자·가격 사실 문구가 없다(#55 스토리 24, #62)", () => {
    expect(page).not.toMatch(/\d%|52-week|prev close|days in a row|Price fact|price-fact|closing prices|Prices are daily closes/i);
    expect(html).not.toContain("data-tone"); // 등락률 요소 0개(샘플·Step 미니 카드)
  });

  test("1단계 기능 설명(#70): 카드 헤더, 알아두기, 추정 실적일, 연관 소식(무료는 본문 없음), 내 종목 3개·교체, 7:45 AM ET, 커버 범위", () => {
    expect(page).toContain("says up top what it found: new filings or a quiet day.");
    expect(page).toContain("On a quiet day, it may add one background fact from the company's annual report.");
    expect(page).toContain("The next earnings date, estimated from past filings and marked (est.), with a countdown.");
    expect(page).toContain(
      "Same-day filings from a competitor, customer, supplier or peer. The relationship and the fact — never what it means for your stock. Free cards don't show the filings themselves.",
    );
    expect(page).toContain("From the S&P 500 and popular ETFs, with up to three swaps a day.");
    expect(page).toContain("New cards are ready by 7:45 AM ET.");
    expect(page).not.toMatch(/are in Plus|only the count/); // 판매 전 Plus를 지금 있는 것처럼, 0건·지연·ETF에 안 맞는 말(#70 검수)
  });

  test("Plus(#70): 판매 전·계획 기능 + Notify me만. /plus 설명 화면과 같은 문장, 약관·방침과 같은 말", () => {
    const plus = plain(html.slice(html.indexOf('id="plus"'), html.indexOf('id="get"')));
    expect(plus).toContain("Free to use. No payments."); // 약관 service 절: The Service is free … we do not take any payments
    expect(plus).toContain(
      "Plus is not available yet. Planned: any number of covered stocks, earnings summaries, insider and big holder filings, related company filings, and past cards from the last 90 days. All from SEC filings.",
    );
    expect(plus).toContain("Sign in and tap Notify me on the About Plus page. We'll email your sign-in address once when Plus launches."); // 방침 use 절
  });

  test("흰 Plus 섹션의 링크는 어두운 포커스 링(흰 링은 안 보인다)", () => {
    const plus = html.slice(html.indexOf('id="plus"'), html.indexOf('id="get"'));
    expect(targets(plus)).toHaveLength(1);
    for (const t of targets(plus)) expect(t).toContain("focus-visible:outline-background");
  });

  test("copy-reviewer 1차 교체 문구(03_orchestrator_decisions)", () => {
    // 첫 번째 줄 생성기는 날짜를 쓰지 않는다: 샘플·미리보기 모두 같은 줄
    expect(page).not.toContain("effective Jan 1");
    expect(page.match(/Apple named a new CFO \+2 more \(SEC filing\)/g)).toHaveLength(2);
    expect(page).toContain("Settings required");
    expect(page).toContain("The next cards are ready at 7:45 AM ET.");
    for (const old of ["Start free trial", "Settings to tune", "closing prices only", "Tomorrow's cards"]) expect(page).not.toContain(old);
  });

  test("앱 다운로드 CTA 대신 웹 카드(/cards), 자리표시·설계 메모 없음", () => {
    expect(page).not.toMatch(/App Store|Get the app|iPhone only|\[/);
    // 머리·첫 화면·마지막 섹션 3곳. 하나라도 다른 곳으로 가면 실패
    expect(links(html).filter(([, t]) => t === "Open the latest cards")).toEqual(Array(3).fill(["/cards", "Open the latest cards"]));
    expect(links(html).filter(([h]) => h === "/cards")).toHaveLength(3);
    expect(page).toContain("market_in_30sec");
  });

  test("DB를 읽지 않는 정적 페이지라 카드 대시보드 문구가 없다", () => {
    expect(page).not.toMatch(/No cards yet|Cards could not be loaded|Update delayed/);
  });

  test("링크·버튼은 터치 영역 44px 이상(min-h-11 이상)", () => {
    const cards = renderToStaticMarkup(CardsLayout({ children: null } as unknown as LayoutProps<"/cards">));
    expect(hrefs(cards)).toContain("/"); // 카드 화면의 브랜드는 랜딩으로
    const legal = [LegalLayout({ children: null }), <Terms key="t" />, <Privacy key="p" />].map((el) => targets(renderToStaticMarkup(el)));
    expect(hrefs(renderToStaticMarkup(LegalLayout({ children: null })))).toContain("/"); // 법률 페이지 머리의 브랜드도 랜딩으로
    const all = [...targets(html), ...targets(footerHtml), ...targets(cards), ...legal.flat()];
    expect(all.length).toBeGreaterThan(10);
    for (const t of all) expect(t, t).toMatch(/class="[^"]*\b(min-)?h-1[12]\b/);
  });
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

describe("로그인 버튼(#37)", () => {
  const forms = (html: string) => [...html.matchAll(/<form\b([^>]*)>(.*?)<\/form>/g)].map((m) => ({ attrs: m[1], body: m[2] }));

  test("로그인 전: POST /auth/sign-in 폼 + 숨은 타임존 + Sign in 버튼, 실패 문구 없음", () => {
    const html = renderToStaticMarkup(<AuthControl signedIn={false} failed={false} />);
    const [form, ...rest] = forms(html);
    expect(rest).toEqual([]);
    expect(form.attrs).toMatch(/method="post"/);
    expect(form.attrs).toMatch(/action="\/auth\/sign-in"/);
    expect(form.body).toMatch(/<input type="hidden" name="timezone" value=""\/>/);
    expect(form.body).toMatch(new RegExp(`<button[^>]*type="submit"[^>]*>${SIGN_IN}</button>`));
    expect(text(html)).not.toContain(SIGN_IN_FAILED);
    expect(text(html)).not.toContain(SIGN_OUT);
  });

  test("로그인 실패: 실패 문구를 role=status로", () => {
    const html = renderToStaticMarkup(<AuthControl signedIn={false} failed />);
    expect(html).toMatch(new RegExp(`<p[^>]*role="status"[^>]*>${SIGN_IN_FAILED}</p>`));
    expect(forms(html)[0].attrs).toMatch(/action="\/auth\/sign-in"/);
  });

  test("로그인됨: POST /auth/sign-out 폼 + Sign out, failed여도 실패 문구 없음", () => {
    const html = renderToStaticMarkup(<AuthControl signedIn failed />);
    const [form, ...rest] = forms(html);
    expect(rest).toEqual([]);
    expect(form.attrs).toMatch(/method="post"/);
    expect(form.attrs).toMatch(/action="\/auth\/sign-out"/);
    expect(form.body).toMatch(new RegExp(`<button[^>]*type="submit"[^>]*>${SIGN_OUT}</button>`));
    expect(text(html)).not.toContain(SIGN_IN_FAILED);
    expect(text(html)).not.toContain(SIGN_IN);
  });

  test("버튼은 터치 영역 44px 이상(min-h-11 이상)", () => {
    const all = [true, false].flatMap((signedIn) => targets(renderToStaticMarkup(<AuthControl signedIn={signedIn} failed />)));
    expect(all).toHaveLength(2);
    for (const t of all) expect(t, t).toMatch(/class="[^"]*\b(min-)?h-1[12]\b/);
  });

  test("타임존 칸을 서버에서 그리면 빈 값(서버 타임존이 박히지 않게, 브라우저가 채운다)", () => {
    expect(renderToStaticMarkup(<TimezoneField />)).toBe('<input type="hidden" name="timezone" value=""/>');
  });
});

describe("내 종목·둘러보기(#38)", () => {
  const forms = (html: string) =>
    [...html.matchAll(/<form\b([^>]*)>(.*?)<\/form>/g)].map((m) => ({
      method: m[1].match(/\bmethod="([^"]*)"/)?.[1],
      action: m[1].match(/\baction="([^"]*)"/)?.[1],
      fields: Object.fromEntries([...m[2].matchAll(/<input type="hidden" name="([^"]+)" value="([^"]*)"\/>/g)].map((f) => [f[1], f[2]])),
      button: text(m[2].match(/<button\b[^>]*>(.*?)<\/button>/)?.[1] ?? ""),
    }));
  const coverage = [
    { ticker: "AAPL", name: "Apple Inc." },
    { ticker: "MSFT", name: "Microsoft" },
    { ticker: "NVDA", name: "NVIDIA" },
    { ticker: "TQQQ", name: "ProShares UltraPro QQQ" },
  ];
  const data = {
    tradingDay: "Fri, Oct 16, 2026",
    glance: null,
    cards: [card(), card({ ticker: "MSFT", name: "Microsoft" }), card({ ticker: "NVDA", name: "NVIDIA" })],
  };
  const view = (stocks: string[], swapsLeft: number | null, result?: string, q?: string, cover = coverage): MyDashboardView =>
    myDashboardView(
      data.cards,
      cover,
      { stocks: stocks.map((t) => ({ ...cover.find((c) => c.ticker === t)!, locked: false })), swapsLeft },
      result,
      q,
    );
  const SEARCH_FORM = { method: "get", action: "/cards#pick", fields: {}, button: "Search" };
  const pick = (html: string) => html.match(/<details\b.*?<\/details>/)?.[0] ?? "";
  const render = (mine?: MyDashboardView) => renderToStaticMarkup(<Dashboard data={data} mine={mine} />);
  const headings = (html: string) => [...html.matchAll(/<h([12])\b[^>]*>(.*?)<\/h\1>/g)].map((m) => `h${m[1]} ${text(m[2])}`);

  test("로그인 전: 지금 대시보드 그대로(내 종목·둘러보기·고르기 없음)", () => {
    const html = render();
    expect(text(html)).not.toMatch(/My stocks|Browse|Pick your stocks|Swaps left|Search/);
    expect(forms(html)).toEqual([]);
    expect(html).not.toMatch(/role="search"|<input/);
    expect(lines(html)).toHaveLength(9);
  });

  test("내 종목 0개: 고르기(검색창만, #58)가 열린 채 먼저, 그 아래 둘러보기(카드 전부)", () => {
    const html = render(view([], 3));
    expect(html).toMatch(/<details[^>]*\bopen=""/);
    expect(text(html).indexOf("Pick your stocks")).toBeLessThan(text(html).indexOf("Browse"));
    expect(forms(html)).toEqual([SEARCH_FORM]); // 검색어가 없으면 목록 없음(커버 범위 약 550개를 다 그리지 않는다)
    expect(text(pick(html))).not.toMatch(/No matching stocks|Type more/);
    expect(headings(html)).toEqual(["h1 Fri, Oct 16, 2026", "h2 My stocks", "h2 Browse", "h2 AAPL", "h2 MSFT", "h2 NVDA"]);
  });

  test("고르기: 검색 폼은 GET /cards#pick, 라벨 있는 검색칸, 결과마다 넣기 버튼(#58)", () => {
    const html = render(view([], 3, undefined, "a"));
    expect(pick(html)).toMatch(/^<details id="pick"/); // 검색 뒤 새 페이지가 이 칸으로 간다
    const form = pick(html).match(/<form\b[^>]*>/)![0];
    expect(form).toMatch(/\brole="search"/);
    expect(form).toMatch(/\bmethod="get"/);
    expect(form).toMatch(/\baction="\/cards#pick"/);
    const input = pick(html).match(/<input\b[^>]*>/)![0];
    const id = input.match(/\bid="([^"]+)"/)![1];
    expect(pick(html)).toMatch(new RegExp(`<label[^>]*for="${id}"[^>]*>Search by ticker or company</label>`));
    for (const attr of ['type="search"', 'name="q"', 'value="a"', 'maxLength="40"', 'autoComplete="off"', 'autoCorrect="off"', 'spellCheck="false"', 'enterKeyHint="search"'])
      expect(input, attr).toContain(attr);
    expect(input.match(/class="([^"]*)"/)![1].split(" ")).toEqual(expect.arrayContaining(["min-h-11", "min-w-0", "grow", "text-base"])); // 높이 44px, 좁은 폭에서 줄어듦, 16px(iOS 확대 방지)
    expect(forms(html)).toEqual([
      SEARCH_FORM,
      // a: 티커로 시작(AAPL) → 이름에 포함(NVIDIA, ProShares …). MSFT(Microsoft)는 a가 없다
      ...["AAPL", "NVDA", "TQQQ"].map((t) => ({
        method: "post",
        action: "/my-stocks",
        fields: { change: "add", ticker: t },
        button: `Add ${t}`, // 보이는 글자는 Add, 화면 읽기 프로그램에는 티커까지
      })),
    ]);
  });

  test("고르기: 검색어가 있으면 열리고(내 종목이 있어도), 0개면 No matching stocks, 20개에서 잘리면 Type more to narrow the list", () => {
    const none = render(view(["MSFT"], 2, undefined, "zzz"));
    expect(pick(none)).toMatch(/^<details[^>]*\bopen=""/);
    expect(pick(none)).toMatch(/<p id="pick-note"[^>]*>No matching stocks<\/p>/);
    expect(pick(none)).toMatch(/<input\b[^>]*aria-describedby="pick-note"/); // 입력칸에 머무는 화면 읽기 프로그램도 듣는다
    expect(forms(pick(none))).toEqual([SEARCH_FORM]);
    expect(render(view(["MSFT"], 2, undefined, "msft"))).toContain("No matching stocks"); // 이미 내 종목인 것만 맞음

    const many = Array.from({ length: 25 }, (_, i) => ({ ticker: `ZZ${String.fromCharCode(65 + i)}`, name: `Test Fund ${i}` }));
    const cut = render(view([], 3, undefined, "zz", many));
    expect(pick(cut)).toMatch(/<p id="pick-note"[^>]*>Type more to narrow the list<\/p>/);
    expect(forms(cut).filter((f) => f.fields.change === "add")).toHaveLength(20);

    const fits = render(view([], 3, undefined, "a"));
    expect(text(pick(fits))).not.toMatch(/No matching stocks|Type more/);
    expect(fits).not.toContain("aria-describedby");
  });

  test("고르기: 검색어는 입력칸 값으로만 돌아오고(이스케이프) 문구 영역에는 그리지 않는다", () => {
    const html = render(view([], 3, undefined, '"><b>q-canary</b>'));
    expect(html).not.toContain("<b>");
    expect(pick(html)).toContain('value="&quot;&gt;&lt;b&gt;q-canary&lt;/b&gt;"');
    expect(html.replace(/<input\b[^>]*>/, "")).not.toContain("q-canary");
  });

  test("고르기: 휴대폰 폭(320px)에서 가로 스크롤이 생기지 않는 구조(고정 폭 없음, 입력칸은 줄고 버튼은 안 준다)", () => {
    // 브라우저 자동화가 없어 구조로 고정: 폼 줄은 flex, 입력칸 min-w-0 grow, 버튼 shrink-0, 결과 이름 min-w-0 wrap-break-word
    const html = pick(render(view([], 3, undefined, "a")));
    expect(html).not.toMatch(/class="[^"]*\b(min-|max-)?w-(\[|[1-9])/);
    expect(html).not.toMatch(/\b(whitespace-nowrap|text-nowrap|truncate|overflow-x-)/);
    const row = html.match(/<div class="([^"]*)"><input\b[^>]*>(<button\b[^>]*>)/)!;
    expect(row[1].split(" ")).toContain("flex");
    expect(row[2].match(/class="([^"]*)"/)![1].split(" ")).toContain("shrink-0");
    const name = html.match(/<span class="([^"]*)">NVIDIA<\/span>/)![1].split(" ");
    expect(name).toEqual(expect.arrayContaining(["min-w-0", "wrap-break-word"]));
  });

  test("내 종목 있음: 위 My stocks(카드 또는 Summary arrives tomorrow morning + 빼기), 아래 Browse(나머지 카드), 고르기는 접힘", () => {
    const html = render(view(["TQQQ", "MSFT"], 2));
    expect(headings(html)).toEqual(["h1 Fri, Oct 16, 2026", "h2 My stocks", "h2 TQQQ", "h2 MSFT", "h2 Browse", "h2 AAPL", "h2 NVDA"]);
    const mine = text(html.slice(0, html.indexOf("Browse")));
    expect(mine).toContain("ProShares UltraPro QQQ");
    expect(mine).toContain("Summary arrives tomorrow morning"); // TQQQ는 이 날 카드가 없다
    expect(mine).toContain("Swaps left today: 2");
    expect(html).not.toMatch(/<details[^>]*\bopen=/);

    const all = forms(html);
    expect(all.filter((f) => f.fields.change === "remove")).toEqual(
      ["TQQQ", "MSFT"].map((t) => ({ method: "post", action: "/my-stocks", fields: { change: "remove", ticker: t }, button: `Remove ${t}` })),
    );
    expect(all.filter((f) => f.method === "get")).toEqual([SEARCH_FORM]); // 검색어가 없으면 검색창만
    expect(all.filter((f) => f.fields.change === "add")).toEqual([]);
    const found = forms(render(view(["TQQQ", "MSFT"], 2, undefined, "a")));
    expect(found.filter((f) => f.fields.change === "add").map((f) => f.fields.ticker)).toEqual(["AAPL", "NVDA"]); // 내 종목(TQQQ) 빼고
  });

  test("내 종목마다 지난 카드 링크(#68): /cards/티커, 보이는 글자 Past cards, 화면 읽기 프로그램에는 티커까지. 카드 없는 내 종목에도, 둘러보기에는 없다", () => {
    const html = render(view(["TQQQ", "MSFT"], 2));
    const links = [...html.matchAll(/<a\b[^>]*href="(\/cards\/[^"]*)"[^>]*>(.*?)<\/a>/g)].map((m) => [m[1], text(m[2])]);
    expect(links).toEqual([
      ["/cards/TQQQ", "Past cards TQQQ"],
      ["/cards/MSFT", "Past cards MSFT"],
    ]);
  });

  test("Plus(남은 교체 null)는 횟수를 그리지 않는다. 무료 0회는 그린다", () => {
    expect(text(render(view(["MSFT"], null)))).not.toContain("Swaps left");
    expect(text(render(view(["MSFT"], 0)))).toContain("Swaps left today: 0");
  });

  test("결과 문구는 role=status로 내 종목 칸에", () => {
    for (const [code, copy] of [
      ["free_swap_limit", "Free plan can swap stocks 3 times a day. Swaps reset tomorrow."],
      ["free_my_stock_limit", "Free plan can pick 3 stocks. Remove one to add another."],
      ["failed", "My stocks could not be updated"],
    ]) {
      const html = render(view(["MSFT"], 0, code));
      expect(html).toMatch(new RegExp(`<p[^>]*role="status"[^>]*>${copy}</p>`));
      expect(html.indexOf(copy)).toBeLessThan(html.indexOf("Browse"));
    }
    expect(render(view(["MSFT"], 0))).not.toContain('role="status"');
  });

  test("넣기·빼기·검색 버튼, 검색칸, 고르기 펼침은 터치 영역 44px 이상(min-h-11 이상)", () => {
    const html = render(view(["MSFT"], 2, undefined, "a"));
    const all = [...targets(html), ...[...html.matchAll(/<(summary|input(?! type="hidden"))\b[^>]*>/g)].map((m) => m[0])];
    expect(all.length).toBe(1 + 1 + 1 + 3 + 1 + 1); // 지난 카드 1 + 빼기 1 + 검색 1 + 넣기 3 + 펼침 1 + 검색칸 1
    for (const t of all) expect(t, t).toMatch(/class="[^"]*\b(min-)?h-1[12]\b/);
  });
});

describe("시장 한눈에(#11)", () => {
  const glance: GlanceView = {
    lines: [
      { text: "Thu 10/15 close: S&P 500 (SPY) +0.4%, Nasdaq (QQQ) \u22121.2%", status: "checked_found" },
      { text: "No economic releases found", status: "checked_none" },
      { text: "Not covered yet", status: "unsupported" },
    ],
    checked: "Checked 7:30 AM ET · Daily prices · Economic calendar",
  };
  const headings = (html: string) => [...html.matchAll(/<h([12])\b[^>]*>(.*?)<\/h\1>/g)].map((m) => `h${m[1]} ${text(m[2])}`);
  const section = (html: string) => html.match(/<section[^>]*aria-labelledby="market-glance"[^>]*>.*?<\/section>/)?.[0];

  test("제목 Market at a glance(h2, 섹션 이름) + DB 문구 세 줄을 순서대로 + 하단 확인 범위", () => {
    const html = renderToStaticMarkup(<MarketGlance glance={glance} />);
    expect(html).toMatch(/<section[^>]*aria-labelledby="market-glance"/);
    expect(html).toMatch(/<h2 id="market-glance"[^>]*>Market at a glance<\/h2>/);
    expect(lines(html)).toEqual([
      ["checked_found", "Thu 10/15 close: S&amp;P 500 (SPY) +0.4%, Nasdaq (QQQ) \u22121.2%"],
      ["checked_none", "No economic releases found"],
      ["unsupported", "Not covered yet"],
    ]);
    expect(text(html)).toContain("Checked 7:30 AM ET · Daily prices · Economic calendar");
  });

  test("하단이 없으면(확인된 줄 없음·그날 행 없음) Checked를 그리지 않는다. 줄은 숨기지 않는다", () => {
    const delayed: GlanceView = { lines: Array(3).fill({ text: "Update delayed", status: "delayed" }), checked: null };
    const html = renderToStaticMarkup(<MarketGlance glance={delayed} />);
    expect(lines(html)).toEqual(Array(3).fill(["delayed", "Update delayed"]));
    expect(text(html)).not.toContain("Checked");
  });

  test("줄 색은 카드와 같은 규칙: 확인함·있음만 본문색, 나머지는 흐림", () => {
    const html = renderToStaticMarkup(
      <MarketGlance glance={{ ...glance, lines: [...glance.lines.slice(0, 2), { text: "Update delayed", status: "delayed" }] }} />,
    );
    expect(classOf(html, 'data-status="checked_found')).toContain("text-foreground");
    expect(classOf(html, 'data-status="checked_none')).toContain("text-muted");
    expect(classOf(html, 'data-status="delayed')).toContain("text-muted");
    expect(classOf(renderToStaticMarkup(<MarketGlance glance={glance} />), 'data-status="unsupported')).toContain("text-muted");
  });

  test("거래일 제목 바로 아래, 카드 목록 위(로그인 전)", () => {
    const html = renderToStaticMarkup(<Dashboard data={{ tradingDay: "Fri, Oct 16, 2026", glance, cards: [card()] }} />);
    expect(headings(html)).toEqual(["h1 Fri, Oct 16, 2026", "h2 Market at a glance", "h2 AAPL"]);
  });

  test("로그인: 거래일 제목 → 시장 한눈에 → My stocks → Browse. 로그인 전·무료·Plus 모두 같은 블록", () => {
    const data = { tradingDay: "Fri, Oct 16, 2026", glance, cards: [card(), card({ ticker: "MSFT", name: "Microsoft" })] };
    const coverage = [
      { ticker: "AAPL", name: "Apple Inc." },
      { ticker: "MSFT", name: "Microsoft" },
    ];
    const mine = (swapsLeft: number | null) =>
      myDashboardView(data.cards, coverage, { stocks: [{ ...coverage[1], locked: false }], swapsLeft }, undefined);
    const [out, free, plus] = [undefined, mine(3), mine(null)].map((m) => renderToStaticMarkup(<Dashboard data={data} mine={m} />));
    expect(headings(free)).toEqual(["h1 Fri, Oct 16, 2026", "h2 Market at a glance", "h2 My stocks", "h2 MSFT", "h2 Browse", "h2 AAPL"]);
    expect(section(out)).toBeDefined();
    expect(section(free)).toBe(section(out));
    expect(section(plus)).toBe(section(out));
  });

  test("읽는 동안 스켈레톤에 시장 한눈에 자리(제목 1 + 시장 한눈에 1 + 카드 3)", () => {
    expect(renderToStaticMarkup(<DashboardSkeleton />).match(/bg-surface/g)).toHaveLength(5);
  });
});

// ---- 이용약관·개인정보처리방침(#62). 정적 페이지: DB를 읽지 않는다(guards.test.ts) ----

const EMAIL = "tlsrudgk13@gmail.com"; // 사용자 결정(2026-11-04): 공개 연락 이메일. 법률 페이지와 이 테스트에만 쓴다
/** 보이는 글자(엔티티 풀기) */
const visible = (html: string) => text(html).replaceAll("&#x27;", "'").replaceAll("&amp;", "&").replaceAll("&quot;", '"');
/** <section id="…">의 보이는 글자 */
const section = (html: string, id: string) => visible(html.match(new RegExp(`<section id="${id}"[^>]*>(.*?)</section>`))?.[1] ?? "");
const sectionIds = (html: string) => [...html.matchAll(/<section id="([^"]+)"/g)].map((m) => m[1]);
const mailtos = (html: string) => [...html.matchAll(/<a[^>]*href="mailto:([^"]*)"[^>]*>([^<]*)<\/a>/g)].map((m) => [m[1], m[2]]);

describe("이용약관 /terms(#62)", () => {
  const html = renderToStaticMarkup(<Terms />);
  const page = visible(html);

  test("제목·마지막 수정일·운영자·절 id 전부", () => {
    expect(html).toMatch(/<h1[^>]*>Terms of Service<\/h1>/);
    expect(page).toMatch(/Last updated: [A-Z][a-z]+ \d{1,2}, 20\d\d/);
    expect(page).toContain("Paul Sin");
    expect(sectionIds(html)).toEqual(["service", "not-advice", "sources", "accounts", "use", "disclaimers", "changes", "contact"]);
    expect(html.match(/<h2\b/g)).toHaveLength(8); // 절마다 h2(h1 → h2 순서)
  });

  test("not-advice 절: Not investment advice + 증권사·투자자문업자 아님 + 사고팔라는 권유 아님 + AI가 틀릴 수 있음", () => {
    const s = section(html, "not-advice");
    expect(s).toContain("Not investment advice");
    expect(s).toMatch(/not a broker-dealer or an investment adviser/);
    expect(s).toMatch(/not a recommendation to buy, sell or hold/);
    expect(s).toMatch(/AI/);
    expect(s).toMatch(/mistakes/);
    expect(s).toContain("(est.)");
  });

  test("데이터 출처는 SEC·정부 공개 자료, 가격·실시간 시세는 제공하지 않고 결제도 받지 않는다", () => {
    expect(section(html, "sources")).toMatch(/SEC EDGAR.*BLS.*BEA.*Census.*Federal Reserve/);
    expect(section(html, "sources")).toMatch(/not affiliated with or endorsed by/);
    const service = section(html, "service");
    expect(service).toMatch(/does not provide stock prices or real-time quotes/);
    expect(service).toMatch(/do not take any payments/);
    expect(service).toMatch(/free/);
    // 매일 카드는 고른 종목·기본 종목에만(커버 범위 전체 아님, #70 검수)
    expect(service).toContain("morning cards for the stocks users have picked and for a set of default stocks");
    expect(service).not.toContain("for each stock in its coverage");
  });

  test("최소 연령 18세, 준거법 California, 중재 조항 없음", () => {
    expect(section(html, "accounts")).toMatch(/at least 18 years old/);
    expect(section(html, "accounts")).toMatch(/Google/);
    expect(section(html, "disclaimers")).toMatch(/laws of the State of California/);
    expect(page).not.toMatch(/arbitration/i);
  });

  test("연락처 절에 연락 이메일 mailto 링크, 변경 절에서 삭제 방법(/privacy#delete)으로", () => {
    expect(mailtos(html.match(/<section id="contact".*?<\/section>/)![0])).toEqual([[EMAIL, EMAIL]]);
    expect(hrefs(html.match(/<section id="changes".*?<\/section>/)![0])).toContain("/privacy#delete");
  });
});

describe("개인정보처리방침 /privacy(#62)", () => {
  const html = renderToStaticMarkup(<Privacy />);
  const page = visible(html);

  test("제목·마지막 수정일·운영자·절 id 전부", () => {
    expect(html).toMatch(/<h1[^>]*>Privacy Policy<\/h1>/);
    expect(page).toMatch(/Last updated: [A-Z][a-z]+ \d{1,2}, 20\d\d/);
    expect(page).toContain("Paul Sin");
    expect(sectionIds(html)).toEqual(["collect", "not-collect", "use", "share", "cookies", "keep", "delete", "rights", "children", "changes", "contact"]);
    expect(html).not.toMatch(/<h[4-6]\b/); // h1 → h2 → h3까지
  });

  test("Google 로그인 때 저장하는 것: 이메일·Google 이름과 사진 링크·계정 식별자·로그인 IP와 브라우저, 플랜·타임존·아침 알림 시간·대기 등록, 내 종목과 이력, 아침 요약", () => {
    const s = section(html, "collect");
    for (const fact of [
      "email address",
      "Google account ID",
      "name and profile photo link",
      "IP address and browser details of your sign-in sessions",
      "plan (Free or Plus)",
      "time zone",
      "morning notification time",
      "Notify me",
      "the stocks you pick",
      "history of each add and remove",
      "local date",
      "one-line summary",
      "Supabase",
    ]) {
      expect(s, fact).toContain(fact);
    }
    // 로그인하지 않아도: 서버 기록, 요청 제한 IP 약 1분, 잠긴 기능 탭은 날짜별 합계만
    expect(s).toMatch(/server logs/);
    expect(s).toMatch(/about a minute/);
    expect(s).toMatch(/daily totals/);
  });

  test("삭제 절(id=delete): 연락 이메일 + 30일 + 지우는 범위 + 로그아웃 위치", () => {
    const raw = html.match(/<section id="delete".*?<\/section>/)![0];
    const s = section(html, "delete");
    expect(mailtos(raw)).toEqual([[EMAIL, EMAIL]]);
    expect(s).toContain("Delete my account");
    expect(s).toMatch(/within 30 days/i);
    for (const item of ["profile", "your stocks and their history", "morning summaries", "Notify me"]) expect(s, item).toContain(item);
    expect(hrefs(raw)).toContain("/cards");
  });

  test("팔지 않음·맞춤 광고 공유 없음·광고 쿠키 없음·Do Not Track 문장, Plus 출시 알림은 로그인 이메일로 한 번", () => {
    expect(section(html, "use")).toMatch(/do not sell your personal information/);
    expect(section(html, "use")).toMatch(/targeted advertising/);
    expect(section(html, "use")).toMatch(/email .*once when Plus launches/);
    expect(section(html, "cookies")).toMatch(/No advertising or analytics cookies/);
    expect(section(html, "cookies")).toContain("Do Not Track");
    expect(section(html, "not-collect")).toMatch(/Payment information/);
  });

  test("서비스 제공자 Supabase·Vercel·Google·GitHub, AI에는 개인정보를 보내지 않음, 저장 지역은 단정하지 않는다", () => {
    const s = section(html, "share");
    for (const p of ["Supabase", "Vercel", "Google", "GitHub"]) expect(s, p).toContain(p);
    expect(s).toMatch(/AI .*only public filings.*never your personal information/);
    expect(section(html, "keep")).toMatch(/Supabase.*Vercel/);
    expect(page).not.toMatch(/United States|U\.S\. region|\bEU\b|region/); // 사용자 결정: 지역 미확인
  });

  test("권리·아동(13세 미만)·연락처", () => {
    expect(section(html, "rights")).toMatch(/California/);
    expect(section(html, "rights")).toMatch(/not discriminate/);
    expect(section(html, "children")).toMatch(/under 13/);
    expect(mailtos(html.match(/<section id="contact".*?<\/section>/)![0])).toEqual([[EMAIL, EMAIL]]);
  });
});

test("법률 페이지 머리: 브랜드(→ 랜딩) + 본문 <main>, 하단 고지는 루트 레이아웃이 그린다", () => {
  const html = renderToStaticMarkup(LegalLayout({ children: <p>legal</p> }));
  expect(hrefs(html)).toEqual(["/"]);
  expect(html).toMatch(/<main\b[^>]*>.*<p>legal<\/p>.*<\/main>/);
});

describe("지난 카드 /cards/[ticker](#68)", () => {
  const quiet = card({
    header: { text: "Quiet day", status: "checked_none" },
    lines: [
      { text: "No new SEC filings found", status: "checked_none" },
      { text: "No confirmed events found", status: "checked_none" },
      { status: "locked" },
    ],
  });
  const view = (over: Partial<PastCardsView> = {}): PastCardsView => ({
    ticker: "AAPL",
    name: "Apple Inc.",
    locked: false,
    days: [
      { day: "Fri, Oct 16, 2026", card: card() },
      { day: "Thu, Oct 15, 2026", card: quiet },
    ],
    ...over,
  });
  const render = (v: PastCardsView) => renderToStaticMarkup(<PastCards view={v} />);
  const headings = (html: string) => [...html.matchAll(/<h([12])\b[^>]*>(.*?)<\/h\1>/g)].map((m) => `h${m[1]} ${text(m[2])}`);

  test("Plus: 뒤로(My stocks → /cards#my-stocks), Past cards 라벨, h1 티커 + 종목명, 날짜(h2)마다 카드 최신순, 잠금 안내 없음", () => {
    const html = render(view());
    expect(headings(html)).toEqual(["h1 AAPL", "h2 Fri, Oct 16, 2026", "h2 AAPL", "h2 Thu, Oct 15, 2026", "h2 AAPL"]);
    expect([...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/g)].map((m) => [m[1], text(m[2])])).toEqual([["/cards#my-stocks", "My stocks"]]);
    const t = text(html);
    expect(t.indexOf("Past cards")).toBeLessThan(t.indexOf("Apple Inc."));
    expect(t.indexOf("Apple reported Q3 results (SEC filing)")).toBeLessThan(t.indexOf("No new SEC filings found"));
    expect(t).not.toContain("Past 90 days in Plus");
  });

  test("무료: 오늘 카드 + Past 90 days in Plus(글자뿐, 결제·누르는 곳 없음: 링크·버튼은 뒤로 하나 + 세 번째 줄 잠금 탭(#69))", () => {
    const html = render(view({ locked: true, days: [{ day: "Fri, Oct 16, 2026", card: quiet }] }));
    expect(headings(html)).toEqual(["h1 AAPL", "h2 Fri, Oct 16, 2026", "h2 AAPL"]);
    expect(text(html).indexOf("Related updates in Plus")).toBeLessThan(text(html).indexOf("Past 90 days in Plus"));
    expect(targets(html)).toHaveLength(2);
    expect(html).toMatch(/<p[^>]*>Past 90 days in Plus<\/p>/); // 잠금 안내 자체는 링크·버튼이 아니다
    expect([...html.matchAll(/name="slot" value="([^"]+)"/g)].map((m) => m[1])).toEqual(["related_lock"]); // 잠긴 자리는 지난 카드에 없다(U3)
  });

  test("오늘 카드 없음은 Summary arrives tomorrow morning 자리, 날이 하나도 없으면 No cards yet", () => {
    const pending = render(view({ locked: true, days: [{ day: "Fri, Oct 16, 2026", card: null }] }));
    expect(headings(pending)).toEqual(["h1 AAPL", "h2 Fri, Oct 16, 2026", "h2 AAPL"]);
    expect(text(pending)).toContain("Summary arrives tomorrow morning");
    expect(text(pending)).toContain("Past 90 days in Plus");
    const empty = render(view({ days: [] }));
    expect(text(empty)).toContain("No cards yet");
    expect(headings(empty)).toEqual(["h1 AAPL"]);
  });

  test("뒤로 링크는 터치 영역 44px 이상, 휴대폰 폭에서 가로 스크롤이 생기지 않는 구조(고정 폭·줄바꿈 금지 없음)", () => {
    const html = render(view({ locked: true }));
    for (const t of targets(html)) expect(t, t).toMatch(/class="[^"]*\b(min-)?h-1[12]\b/);
    expect(html).not.toMatch(/class="[^"]*\b(min-|max-)?w-(\[|[1-9])/);
    expect(html).not.toMatch(/\b(text-nowrap|truncate|overflow-x-)/);
  });
});

describe("잠긴 자리·Notify me(#69)", () => {
  const forms = (html: string) =>
    [...html.matchAll(/<form\b([^>]*)>(.*?)<\/form>/g)].map((m) => ({
      method: m[1].match(/\bmethod="([^"]*)"/)?.[1],
      action: m[1].match(/\baction="([^"]*)"/)?.[1],
      fields: Object.fromEntries([...m[2].matchAll(/<input type="hidden" name="([^"]+)" value="([^"]*)"\/>/g)].map((f) => [f[1], f[2]])),
      button: text(m[2].match(/<button\b.*?<\/button>/)?.[0] ?? ""),
      buttonTag: m[2].match(/<button\b[^>]*>/)?.[0] ?? "",
    }));
  const plain = (s: string) => s.replaceAll("&#x27;", "'");

  test("카드의 잠긴 자리: 자리 종류별 글자의 탭 폼(POST /waitlist, intent=tap, slot) 하나, 줄 목록 아래·하단 위, 줄 수에 세지 않는다", () => {
    for (const [slot, label] of [
      ["earnings_summary", "Earnings summary in Plus"],
      ["big_holders", "Insider and big holder filings in Plus"],
    ] as const) {
      const html = renderToStaticMarkup(<StockCard card={card({ lockedSlot: slot })} />);
      expect(forms(html).map(({ method, action, fields, button }) => ({ method, action, fields, button }))).toEqual([
        { method: "post", action: "/waitlist", fields: { intent: "tap", slot }, button: label },
      ]);
      expect(lines(html)).toHaveLength(3);
      const t = text(html);
      expect(t.indexOf("Up 5 days in a row")).toBeLessThan(t.indexOf(label));
      expect(t.indexOf(label)).toBeLessThan(t.indexOf("Checked 7:30 AM ET"));
    }
  });

  test("세 번째 줄 잠금도 같은 탭 폼(slot=related_lock, #67에서도 그대로), 글자는 건수 문구. 잠긴 자리와 둘 다 있으면 폼 둘", () => {
    const locked = card({ lines: [...card().lines.slice(0, 2), { status: "locked", count: 2 }], lockedSlot: "big_holders" });
    const html = renderToStaticMarkup(<StockCard card={locked} />);
    expect(lines(html)[2]).toEqual(["locked", "2 related updates in Plus"]);
    expect(forms(html).map((f) => [f.action, f.fields, f.button])).toEqual([
      ["/waitlist", { intent: "tap", slot: "related_lock" }, "2 related updates in Plus"],
      ["/waitlist", { intent: "tap", slot: "big_holders" }, "Insider and big holder filings in Plus"],
    ]);
  });

  test("랜딩 샘플(sample, #70): 잠긴 자리·세 번째 줄 잠금은 같은 글자·같은 모양의 /plus 링크, 탭 폼 없음(랜딩 방문이 탭 합계에 섞이지 않게)", () => {
    const locked = card({ lines: [...card().lines.slice(0, 2), { status: "locked", count: 2 }], lockedSlot: "big_holders" });
    const html = renderToStaticMarkup(<StockCard card={locked} sample />);
    expect(forms(html)).toEqual([]);
    expect(lines(html)[2]).toEqual(["locked", "2 related updates in Plus"]);
    const anchors = [...html.matchAll(/<a\b([^>]*)>(.*?)<\/a>/g)];
    expect(anchors.map((m) => [m[1].match(/href="([^"]*)"/)?.[1], text(m[2])])).toEqual([
      ["/plus", "2 related updates in Plus"],
      ["/plus", "Insider and big holder filings in Plus"],
    ]);
    // 실제 카드의 탭 버튼과 같은 클래스(터치 영역 44px 포함)
    const real = forms(renderToStaticMarkup(<StockCard card={locked} />)).map((f) => f.buttonTag.match(/class="([^"]*)"/)?.[1]);
    expect(anchors.map((m) => m[1].match(/class="([^"]*)"/)?.[1])).toEqual(real);
  });

  test("ETF 카드(lockedSlot 없음)·잠금 없는 카드에는 폼이 없다", () => {
    expect(forms(renderToStaticMarkup(<StockCard card={card()} />))).toEqual([]);
  });

  test("탭 버튼은 터치 영역 44px 이상(min-h-11), 누를 수 있는 모양(cursor-pointer), 가로 고정 폭 없음", () => {
    const html = renderToStaticMarkup(<StockCard card={card({ lines: [...card().lines.slice(0, 2), { status: "locked" }], lockedSlot: "earnings_summary" })} />);
    const buttons = forms(html).map((f) => f.buttonTag);
    expect(buttons).toHaveLength(2);
    for (const b of buttons) {
      expect(b, b).toMatch(/class="[^"]*\bmin-h-1[12]\b/);
      expect(b, b).toMatch(/\bcursor-pointer\b/);
      expect(b, b).toMatch(/type="submit"/);
    }
    expect(html).not.toMatch(/class="[^"]*\b(min-|max-)?w-(\[|[1-9])/);
  });

  const notify = (over: Partial<NotifyMeView> = {}) => renderToStaticMarkup(<NotifyMe view={{ signedIn: true, waitlisted: false, failed: false, ...over }} />);
  const PLANNED = "Plus is not available yet. Planned: any number of covered stocks, earnings summaries, insider and big holder filings, related company filings, and past cards from the last 90 days. All from SEC filings.";
  const NOTE = "Tap Notify me and we'll email your sign-in address once when Plus launches.";

  test("설명 화면: 카드로 돌아가는 링크, 제목 About Plus(h1), 설명은 상태와 무관하게 같다. 이메일 입력칸 없음", () => {
    for (const view of [{ signedIn: false }, {}, { waitlisted: true }, { failed: true }]) {
      const html = notify(view);
      expect([...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/g)].map((m) => [m[1], text(m[2])])).toEqual([["/cards", "Open the latest cards"]]);
      expect(html).toMatch(/<h1\b[^>]*>About Plus<\/h1>/);
      expect(plain(text(html))).toContain(PLANNED);
      expect(html).not.toMatch(/type="email"|name="email"|@/);
    }
  });

  test("로그인 전: 안내 + 로그인 폼만(POST /auth/sign-in, 숨은 타임존, Sign in to use Notify me). Notify 폼 없음", () => {
    const html = notify({ signedIn: false, failed: true });
    expect(forms(html).map(({ method, action, fields, button }) => ({ method, action, fields, button }))).toEqual([
      { method: "post", action: "/auth/sign-in", fields: { timezone: "" }, button: "Sign in to use Notify me" },
    ]);
    expect(plain(text(html))).toContain(NOTE);
    expect(text(html)).not.toContain("could not be saved"); // 세션이 없으면 실패 문구도 없다
  });

  test("로그인·미등록: 안내 + Notify me 폼(POST /waitlist, intent=notify, 유저 값 없음)", () => {
    const html = notify();
    expect(forms(html).map(({ method, action, fields, button }) => ({ method, action, fields, button }))).toEqual([
      { method: "post", action: "/waitlist", fields: { intent: "notify" }, button: "Notify me" },
    ]);
    expect(plain(text(html))).toContain(NOTE);
    expect(html).not.toContain('role="status"');
  });

  test("등록됨: You're on the list(role=status), 버튼·안내 없음(failed여도)", () => {
    for (const failed of [false, true]) {
      const html = notify({ waitlisted: true, failed });
      expect(forms(html)).toEqual([]);
      expect(plain(html)).toMatch(/<p[^>]*role="status"[^>]*>You're on the list<\/p>/);
      expect(plain(text(html))).not.toContain(NOTE);
      expect(text(html)).not.toContain("could not be saved");
    }
  });

  test("저장 실패: Notify me could not be saved(role=status) + Notify me 다시", () => {
    const html = notify({ failed: true });
    expect(html).toMatch(/<p[^>]*role="status"[^>]*>Notify me could not be saved<\/p>/);
    expect(forms(html).map((f) => [f.action, f.fields])).toEqual([["/waitlist", { intent: "notify" }]]);
  });

  test("링크·버튼은 터치 영역 44px 이상, 휴대폰 폭에서 가로 스크롤이 생기지 않는 구조", () => {
    for (const view of [{ signedIn: false }, {}, { waitlisted: true }, { failed: true }]) {
      const html = notify(view);
      for (const t of targets(html)) expect(t, t).toMatch(/class="[^"]*\b(min-)?h-1[12]\b/);
      expect(html).not.toMatch(/class="[^"]*\b(min-|max-)?w-(\[|[1-9])/);
      expect(html).not.toMatch(/\b(text-nowrap|truncate|overflow-x-)/);
    }
  });
});
