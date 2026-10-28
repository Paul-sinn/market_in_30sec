import { Inter } from "next/font/google";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

import ErrorPage from "@/app/cards/error";
import CardsLayout from "@/app/cards/layout";
import RootLayout from "@/app/layout";
import Landing from "@/app/page";
import { AuthControl } from "@/components/auth-control";
import { Dashboard } from "@/components/dashboard";
import { SiteFooter } from "@/components/site-footer";
import { StockCard } from "@/components/stock-card";
import { TimezoneField } from "@/components/timezone-field";
import { myDashboardView, type CardView, type MyDashboardView } from "@/lib/card-view";
import { SIGN_IN, SIGN_IN_FAILED, SIGN_OUT } from "@/lib/copy";

// next/font/google은 빌드 때 글꼴을 받는다. 레이아웃 렌더 테스트에서는 변수 이름만 준다(Inter 말고 다른 글꼴을 부르면 실패)
vi.mock("next/font/google", () => ({ Inter: vi.fn(() => ({ variable: "font-sans-var" })) }));

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

  test("잠긴 세 번째 줄(#9): 상태만 받아 고정 문구 Price facts in Plus를 흐리게, 줄을 숨기지 않는다", () => {
    const html = renderToStaticMarkup(<StockCard card={card({ lines: [...card().lines.slice(0, 2), { status: "locked" }] })} />);
    expect(lines(html)).toEqual([
      ["checked_found", "Apple reported Q3 results (SEC filing)"],
      ["checked_found", "Earnings Thu 10/29 after close (D-13)"],
      ["locked", "Price facts in Plus"],
    ]);
    expect(classOf(html, 'data-status="locked')).toContain("text-muted");
  });

  test("등락률 옆 기준 라벨 prev close (값이 없어도, #27 시안)", () => {
    for (const c of [
      { text: "+1.3%", tone: "up" },
      { text: "Update delayed", tone: "delayed" },
    ] as const) {
      const html = renderToStaticMarkup(<StockCard card={card({ change: c })} />);
      expect(text(html)).toContain(`${c.text}prev close`); // 태그를 지우면 값 바로 뒤에 라벨
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

test("모든 페이지(루트 레이아웃) 하단에 Not investment advice. 하단 링크는 어느 경로에서나 랜딩 앵커로", () => {
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
  for (const h of hrefs(footer)) expect(h, h).toMatch(/^\/(#[a-z]+)?$/); // /cards에서 눌러도 랜딩 섹션으로 간다
});

/** 링크·버튼의 href / class */
const hrefs = (html: string) => [...html.matchAll(/<a[^>]*href="([^"]*)"/g)].map((m) => m[1]);
const targets = (html: string) => [...html.matchAll(/<(a|button)\b[^>]*>/g)].map((m) => m[0]);

describe("랜딩 / (#27 사용자 시안)", () => {
  const html = renderToStaticMarkup(<Landing />);
  const page = text(html).replaceAll("&#x27;", "'").replaceAll("&amp;", "&");

  test("시안 섹션 전부 + 머리 메뉴 앵커가 가리키는 섹션이 있다", () => {
    for (const id of ["top", "card", "how", "arena", "pricing", "get"]) expect(html).toContain(`id="${id}"`);
    for (const h of hrefs(html).filter((h) => h.startsWith("#"))) expect(html, h).toContain(`id="${h.slice(1)}"`);
  });

  test("샘플 카드: 현재 고정 문구로(폐기 문구·미정 ETF 줄 없음), 안내 문구 유지", () => {
    expect(lines(html)).toEqual([
      ["checked_found", "Apple named a new CFO +2 more (Company)"],
      ["checked_found", "Earnings Thu 10/15 after close (D-2)"],
      ["checked_found", "8.0% below 52-week high"],
      ["checked_none", "No new SEC filings found"],
      ["checked_found", "Ex-dividend 12/21 · $0.70/share"],
      ["checked_found", "Up 5 days in a row"],
      ["checked_none", "No new SEC filings found"],
      ["checked_none", "No confirmed events found"],
      ["checked_none", "No additional price highlights"],
    ]);
    for (const old of ["No major news today", "No events in next 2 weeks", "No notable price moves", "Top holdings"]) {
      expect(page).not.toContain(old);
    }
    expect(page).toContain("Sample cards. Figures are illustrative.");
    expect(page.match(/prev close/g)).toHaveLength(3);
  });

  test("판정 기준은 ADR-0002(모든 콜 당일 시가 → 종가)", () => {
    expect(page).not.toContain("against the previous close");
    expect(page).toContain("against the day's open");
  });

  test("copy-reviewer 1차 교체 문구(03_orchestrator_decisions)", () => {
    // 첫 번째 줄 생성기는 날짜를 쓰지 않는다: 샘플·미리보기 모두 같은 줄
    expect(page).not.toContain("effective Jan 1");
    expect(page.match(/Apple named a new CFO \+2 more \(Company\)/g)).toHaveLength(2);
    expect(page).toContain("The nearest earnings date or dividend. Earnings show a countdown; unconfirmed dates are marked (est.).");
    expect(page).toContain("Settings required");
    expect(page).toContain("long only, daily prices only.");
    expect(page).toContain("The next cards are ready at 7:45 AM ET.");
    for (const old of ["Start free trial", "Settings to tune", "closing prices only", "Tomorrow's cards"]) expect(page).not.toContain(old);
  });

  test("가짜 아레나 전적에는 카드마다 Sample 표시", () => {
    const agents = html.split("<article").filter((a) => a.includes("Hits – misses"));
    expect(agents).toHaveLength(2);
    for (const a of agents) expect(a).toMatch(/>Sample<\/span>/);
  });

  test("아레나 카드 머리: 좁은 폭(320px)에서 Sample 알약이 다음 줄로 내려간다(이름과 겹치지 않게)", () => {
    // 브라우저 없이 폭을 잴 수 없어 구조로 고정: 머리 줄은 flex-wrap, 알약은 아바타·이름 묶음 밖의 형제이고
    // 묶음의 기본 폭(basis-48 = 192px)이 아바타 56 + 간격 16 + "Aggressive" 18px 굵게 약 101px보다 크다
    for (const a of html.split("<article").filter((x) => x.includes("Hits – misses"))) {
      const head = a.match(/^[^>]*><div class="([^"]*)">(.*?)<span[^>]*>Sample<\/span><\/div>/);
      expect(head, a.slice(0, 200)).not.toBeNull();
      expect(head![1].split(" ")).toContain("flex-wrap");
      expect(head![2]).toMatch(/^<div class="[^"]*\bbasis-48\b[^"]*">.*<\/div><\/div>$/); // 묶음이 알약 앞에서 닫힌다
    }
  });

  test("흰 요금 섹션의 버튼은 어두운 포커스 링(흰 링은 안 보인다)", () => {
    const pricing = html.slice(html.indexOf('id="pricing"'), html.indexOf('id="get"'));
    expect(targets(pricing)).toHaveLength(2);
    for (const t of targets(pricing)) expect(t).toContain("focus-visible:outline-background");
  });

  test("앱 다운로드 CTA 대신 웹 카드(/cards), 자리표시·설계 메모 없음", () => {
    expect(page).not.toMatch(/App Store|Get the app|iPhone only|\[/);
    // 머리·첫 화면·Free·Plus·마지막 섹션 5곳. 하나라도 다른 곳으로 가면 실패
    const toCards = [...html.matchAll(/<a[^>]*href="\/cards"[^>]*>([^<]*)<\/a>/g)].map((m) => m[1]);
    expect(toCards).toEqual(Array(5).fill("Open the latest cards"));
    const labelled = [...html.matchAll(/<a[^>]*href="([^"]*)"[^>]*>Open the latest cards<\/a>/g)].map((m) => m[1]);
    expect(labelled).toEqual(Array(5).fill("/cards"));
    expect(page).toContain("market_in_30sec");
  });

  test("DB를 읽지 않는 정적 페이지라 카드 대시보드 문구가 없다", () => {
    expect(page).not.toMatch(/No cards yet|Cards could not be loaded|Update delayed/);
  });

  test("링크·버튼은 터치 영역 44px 이상(min-h-11 이상)", () => {
    const cards = renderToStaticMarkup(CardsLayout({ children: null } as unknown as LayoutProps<"/cards">));
    expect(hrefs(cards)).toContain("/"); // 카드 화면의 브랜드는 랜딩으로
    const all = [...targets(html), ...targets(renderToStaticMarkup(<SiteFooter />)), ...targets(cards)];
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
  const data = { tradingDay: "Fri, Oct 16, 2026", cards: [card(), card({ ticker: "MSFT", name: "Microsoft" }), card({ ticker: "NVDA", name: "NVIDIA" })] };
  const view = (stocks: string[], swapsLeft: number | null, result?: string): MyDashboardView =>
    myDashboardView(
      data.cards,
      coverage,
      { stocks: stocks.map((t) => ({ ...coverage.find((c) => c.ticker === t)!, locked: false })), swapsLeft },
      result,
    );
  const render = (mine?: MyDashboardView) => renderToStaticMarkup(<Dashboard data={data} mine={mine} />);
  const headings = (html: string) => [...html.matchAll(/<h([12])\b[^>]*>(.*?)<\/h\1>/g)].map((m) => `h${m[1]} ${text(m[2])}`);

  test("로그인 전: 지금 대시보드 그대로(내 종목·둘러보기·고르기 없음)", () => {
    const html = render();
    expect(text(html)).not.toMatch(/My stocks|Browse|Pick your stocks|Swaps left/);
    expect(forms(html)).toEqual([]);
    expect(lines(html)).toHaveLength(9);
  });

  test("내 종목 0개: 고르기(커버 범위 전부)가 열린 채 먼저, 그 아래 둘러보기(카드 전부)", () => {
    const html = render(view([], 3));
    expect(html).toMatch(/<details[^>]*\bopen=""/);
    expect(text(html).indexOf("Pick your stocks")).toBeLessThan(text(html).indexOf("Browse"));
    expect(forms(html)).toEqual(
      coverage.map((c) => ({
        method: "post",
        action: "/my-stocks",
        fields: { change: "add", ticker: c.ticker },
        button: `Add ${c.ticker}`, // 보이는 글자는 Add, 화면 읽기 프로그램에는 티커까지
      })),
    );
    expect(headings(html)).toEqual(["h1 Fri, Oct 16, 2026", "h2 My stocks", "h2 Browse", "h2 AAPL", "h2 MSFT", "h2 NVDA"]);
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
    expect(all.filter((f) => f.fields.change === "add").map((f) => f.fields.ticker)).toEqual(["AAPL", "NVDA"]);
  });

  test("Plus(남은 교체 null)는 횟수를 그리지 않는다. 무료 0회는 그린다", () => {
    expect(text(render(view(["MSFT"], null)))).not.toContain("Swaps left");
    expect(text(render(view(["MSFT"], 0)))).toContain("Swaps left today: 0");
  });

  test("결과 문구는 role=status로 내 종목 칸에", () => {
    for (const [code, copy] of [
      ["free_swap_limit", "Free plan can swap stocks 3 times a day. Plus has no limit."],
      ["free_my_stock_limit", "Free plan can pick 3 stocks. Remove one to add another."],
      ["failed", "My stocks could not be updated"],
    ]) {
      const html = render(view(["MSFT"], 0, code));
      expect(html).toMatch(new RegExp(`<p[^>]*role="status"[^>]*>${copy}</p>`));
      expect(html.indexOf(copy)).toBeLessThan(html.indexOf("Browse"));
    }
    expect(render(view(["MSFT"], 0))).not.toContain('role="status"');
  });

  test("넣기·빼기 버튼과 고르기 펼침은 터치 영역 44px 이상(min-h-11 이상)", () => {
    const html = render(view(["MSFT"], 2));
    const all = [...targets(html), ...[...html.matchAll(/<summary\b[^>]*>/g)].map((m) => m[0])];
    expect(all.length).toBe(1 + 3 + 1); // 빼기 1 + 넣기 3 + 펼침 1
    for (const t of all) expect(t, t).toMatch(/class="[^"]*\b(min-)?h-1[12]\b/);
  });
});
