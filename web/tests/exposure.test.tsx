/** 줄 노출 판단(#9, HANDOFF 3-2). DB 없이 저장된 카드 → 화면 모델. 실제 DB 경로는 cards.db.test.ts */
import { randomUUID } from "node:crypto";

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";

import { Dashboard } from "@/components/dashboard";
import { myDashboardView, type CardView, type LineView } from "@/lib/card-view";
import type { StoredCard, StoredLine } from "@/server/cards";
import { exposeCards, exposePastCards, pastCardDays } from "@/server/exposure";
import type { MyStocks } from "@/server/my-stocks";

const AT = "2026-10-16T11:30:00Z"; // 7:30 AM ET
const RELATED_AT = "2026-10-16T11:10:00Z"; // 7:10 AM ET: 가장 이른 시각. 잠기면 하단에서도 빠져야 한다

const line = (text: string, status: StoredLine["status"], source_scope: string | null, checked_at = AT): StoredLine => ({
  text,
  status,
  checked_at,
  source_scope,
});

/** 세 번째 줄 = 연관 소식(#67). 범위는 첫 번째 줄과 같은 SEC filings라 하단에서 하나로 합쳐지고, 시각만 다르다 */
const THIRD = {
  있음: line("Competitor Microsoft reported Q3 revenue of $65.6B +1 more (SEC filing)", "checked_found", "SEC filings", RELATED_AT),
  없음: line("No major related filings found", "checked_none", "SEC filings", RELATED_AT),
  지연: line("Update delayed", "delayed", "SEC filings", RELATED_AT),
};

const stored = (third: StoredLine | null, over: Partial<StoredCard> = {}): StoredCard => ({
  ticker: "AAPL",
  name: "Apple Inc.",
  change: { text: "+1.3%", tone: "up", label: "Thu 10/15 close" },
  lines: [
    line("Apple reported Q3 results (SEC filing)", "checked_found", "SEC filings"),
    line("No confirmed events found", "checked_none", "Earnings and dividend calendar"),
    third,
  ],
  leverageTag: null,
  suspended: false,
  newsFilingCount: 1, // 첫 번째 줄이 다룬 공시 수(#63)
  relatedFilingCount: third?.status === "checked_found" ? 2 : null, // 세 번째 줄이 다룬 공시 수(#67, DB가 확인함·있음에만 허용)
  firstQuietFact: null, // 알아두기 1번(#66). 첫 번째 줄이 확인함·있음이라 있어도 안 보인다
  lockedSlot: null, // 잠긴 자리(#69). null = ETF·지난 카드(키 없음)
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

/** 무료 범위: 세 번째 줄은 건수만(확인함·있음일 때 count, 그 밖엔 status 하나). 본문·확인 시각·출처가 새지 않는다 */
const LOCKED: Record<keyof typeof THIRD, LineView> = { 있음: { status: "locked", count: 2 }, 없음: { status: "locked" }, 지연: { status: "locked" } };
const FREE_OF = (kind: keyof typeof THIRD): CardView => ({
  ticker: "AAPL",
  name: "Apple Inc.",
  header: { text: "1 new filing", status: "checked_found" },
  change: { text: "+1.3%", tone: "up", label: "Thu 10/15 close" },
  lines: [...FIRST_TWO, LOCKED[kind]],
  leverageTag: null,
  checked: "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar", // 세 번째 줄의 7:10은 빠진다
});
const FREE = FREE_OF("있음");

const FULL: Record<keyof typeof THIRD, CardView> = {
  있음: {
    ...FREE,
    lines: [...FIRST_TWO, { text: THIRD.있음.text, status: "checked_found" }],
    checked: "Checked 7:10 AM ET · SEC filings · Earnings and dividend calendar",
  },
  없음: {
    ...FREE,
    lines: [...FIRST_TWO, { text: "No major related filings found", status: "checked_none" }],
    checked: "Checked 7:10 AM ET · SEC filings · Earnings and dividend calendar",
  },
  지연: { ...FREE, lines: [...FIRST_TWO, { text: "Update delayed", status: "delayed" }] }, // 지연 줄은 하단에 넣지 않는다
};

describe("exposeCards: 세 번째 줄(연관 소식, #67) 본문은 Plus 유저의 잠기지 않은 내 종목뿐, 그 밖은 건수만", () => {
  for (const [who, viewer, full] of VIEWERS) {
    for (const [kind, third] of Object.entries(THIRD) as [keyof typeof THIRD, StoredLine][]) {
      test(`${who} × 세 번째 줄 ${kind} → ${full ? "본문" : "건수만(잠금)"}`, () => {
        expect(exposeCards([stored(third)], viewer)).toEqual([full ? FULL[kind] : FREE_OF(kind)]);
      });
    }
  }

  test("Plus여도 잠긴 내 종목은 무료 범위(둘러보기와 같은 자리)", () => {
    for (const kind of Object.keys(THIRD) as (keyof typeof THIRD)[]) {
      expect(exposeCards([stored(THIRD[kind])], my("plus", "AAPL", true)), kind).toEqual([FREE_OF(kind)]);
    }
  });

  test("카드마다 따로 판단: Plus 유저의 내 종목만 열리고 같은 화면의 둘러보기 카드는 잠긴다", () => {
    const cards = [stored(THIRD.있음), stored(THIRD.있음, { ticker: "MSFT", name: "Microsoft" })];
    const [mine, browse] = exposeCards(cards, my("plus", "AAPL"));
    expect(mine.lines[2]).toEqual({ text: THIRD.있음.text, status: "checked_found" });
    expect(browse.lines[2]).toEqual({ status: "locked", count: 2 });
  });

  test("건수는 확인함·있음이고 1 이상일 때만 키가 생긴다(저장 건수 그대로, 문장의 +N more는 읽지 않는다)", () => {
    for (const [count, want] of [[1, { status: "locked", count: 1 }], [5, { status: "locked", count: 5 }], [null, { status: "locked" }], [0, { status: "locked" }]] as const) {
      const [view] = exposeCards([stored(THIRD.있음, { relatedFilingCount: count })], null);
      expect(view.lines[2], String(count)).toStrictEqual(want); // toStrictEqual: count: undefined 키도 실패
    }
    // 없음·지연 줄에 건수가 붙어 와도(DB 제약상 없음) 내보내지 않는다
    for (const kind of ["없음", "지연"] as const) expect(exposeCards([stored(THIRD[kind], { relatedFilingCount: 3 })], null)[0].lines[2], kind).toStrictEqual({ status: "locked" });
  });

  test("미지원(ETF·연관 종목 없음)은 모든 viewer에게 Not covered yet: Plus에도 없는 것을 잠그지 않는다. 하단에는 넣지 않는다", () => {
    const unsupported = line("Not covered yet", "unsupported", null, RELATED_AT);
    for (const [who, viewer] of [...VIEWERS, ["Plus 잠긴 내 종목", my("plus", "AAPL", true)] as const]) {
      const [view] = exposeCards([stored(unsupported)], viewer);
      expect(view.lines, who).toEqual([...FIRST_TWO, { text: "Not covered yet", status: "unsupported" }]);
      expect(view.checked, who).toBe("Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar");
      expect(JSON.stringify(view), who).not.toContain('"locked"');
    }
  });

  test("#67 전 카드(세 번째 줄 없음)는 모든 viewer·가격 플래그에 두 줄, 잠금도 없다", () => {
    for (const prices of ["on", "off"]) {
      vi.stubEnv("PRICE_DISPLAY", prices);
      for (const [who, viewer] of VIEWERS) {
        const [view] = exposeCards([stored(null)], viewer);
        expect(view.lines, `${prices} ${who}`).toEqual([...FIRST_TWO]);
        expect(view.checked, `${prices} ${who}`).toBe("Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar");
      }
    }
    vi.unstubAllEnvs();
  });

  test("데이터 상태(지연·미지원·축소판)와 레버리지 태그는 플랜과 관계없이 그대로", () => {
    const card = stored(THIRD.있음, {
      change: { text: "Update delayed", tone: "delayed", label: "prev close" },
      lines: [null, line("Not covered yet", "unsupported", null), THIRD.있음],
      leverageTag: "3x · resets daily",
      newsFilingCount: null,
    });
    for (const [who, viewer, full] of VIEWERS) {
      const [view] = exposeCards([card], viewer);
      expect(view.change, who).toEqual({ text: "Update delayed", tone: "delayed", label: "prev close" });
      expect(view.lines.slice(0, 2), who).toEqual([
        { text: "Update delayed", status: "delayed" }, // 축소판의 첫 번째 줄
        { text: "Not covered yet", status: "unsupported" },
      ]);
      expect(view.leverageTag, who).toBe("3x · resets daily");
      expect(view.header, who).toEqual({ text: "Update delayed", status: "delayed" }); // 축소판 헤더 = 첫 번째 줄과 같은 지연
      // 확인된 줄은 세 번째 줄뿐: 잠기면 하단도 없다
      expect(view.checked, who).toBe(full ? "Checked 7:10 AM ET · SEC filings" : null);
    }
  });

  test("화면 모델은 허용한 키만(화이트리스트): 저장 카드에 다른 값(방향 의견 등)이 붙어 와도 옮기지 않는다", () => {
    const extra = {
      ...stored({ ...THIRD.있음, direction: "bullish" } as StoredLine),
      direction: "bullish",
      change: { text: "+1.3%", tone: "up", label: "Thu 10/15 close", rating: "buy" },
    } as StoredCard;
    for (const [who, viewer] of VIEWERS) {
      const [view] = exposeCards([extra], viewer);
      expect(Object.keys(view).sort(), who).toEqual(["change", "checked", "header", "leverageTag", "lines", "name", "ticker"]);
      expect(Object.keys(view.change!).sort(), who).toEqual(["label", "text", "tone"]);
      expect(Object.keys(view.header!).sort(), who).toEqual(["status", "text"]);
      for (const l of view.lines) expect(Object.keys(l).sort(), who).toEqual(l.status === "locked" ? ["count", "status"] : ["status", "text"]);
      expect(JSON.stringify(view), who).not.toMatch(/bullish|buy/);
    }
  });
});

describe("발행 중단(#16 D7): 데이터는 두고 화면에서 뺀다", () => {
  const SUSPENDED = `canary-suspended-${randomUUID()}`;
  const cards = [
    stored(THIRD.있음),
    stored(line(SUSPENDED, "checked_found", "SEC filings"), { ticker: "MSFT", name: "Microsoft", suspended: true }),
  ];

  for (const [who, viewer] of [...VIEWERS, ["Plus 내 종목이 발행 중단", my("plus", "MSFT"), true] as const]) {
    test(`${who}: 발행 중단 카드는 결과에 없고 나머지는 그대로`, () => {
      const views = exposeCards(cards, viewer);
      expect(views.map((v) => v.ticker)).toEqual(["AAPL"]);
      expect(JSON.stringify(views)).not.toContain(SUSPENDED);
    });
  }

  test("그날 카드가 전부 발행 중단이면 0장", () => {
    expect(exposeCards([stored(THIRD.있음, { suspended: true })], my("plus", "AAPL"))).toEqual([]);
  });

  test("내 종목이 발행 중단이면 그 자리는 카드 없음과 같다(Summary arrives tomorrow morning), 둘러보기에도 없다", () => {
    const viewer: MyStocks = { plan: "plus", stocks: [{ ticker: "MSFT", name: "Microsoft", locked: false }], swapsLeft: null };
    const coverage = [
      { ticker: "AAPL", name: "Apple Inc." },
      { ticker: "MSFT", name: "Microsoft" },
    ];
    const data = { tradingDay: "Fri, Oct 16, 2026", glance: null, cards: exposeCards(cards, viewer) };
    const mine = myDashboardView(data.cards, coverage, viewer, undefined);
    expect(mine.mine).toEqual([{ ticker: "MSFT", name: "Microsoft", card: null }]);
    expect(mine.browse.map((c) => c.ticker)).toEqual(["AAPL"]);
    const html = renderToStaticMarkup(<Dashboard data={data} mine={mine} />);
    expect(html).toContain("Summary arrives tomorrow morning");
    expect(html).not.toContain(SUSPENDED);
  });
});

describe("잠긴 줄의 원문은 화면 모델(RSC props)과 HTML에 없다", () => {
  const CANARY = `canary-related-${randomUUID()}`;
  const SCOPE = `canary-scope-${randomUUID()}`;
  const card = stored(line(CANARY, "checked_found", SCOPE, "2026-10-16T10:07:00Z")); // 6:07 AM ET
  const coverage = [{ ticker: "AAPL", name: "Apple Inc." }];

  const render = (viewer: MyStocks | null) => {
    const cards = exposeCards([card], viewer);
    const data = { tradingDay: "Fri, Oct 16, 2026", glance: null, cards };
    const mine = viewer ? myDashboardView(cards, coverage, viewer, undefined) : undefined;
    return { props: JSON.stringify({ data, mine }), html: renderToStaticMarkup(<Dashboard data={data} mine={mine} />) };
  };

  for (const [who, viewer, full] of VIEWERS) {
    test(`${who}: ${full ? "원문이 보인다(대조군)" : "원문·출처·시각 없음, 건수만 2 related updates in Plus"}`, () => {
      const { props, html } = render(viewer);
      for (const secret of [CANARY, SCOPE, "6:07 AM"]) {
        expect(props.includes(secret), secret).toBe(full);
        expect(html.includes(secret), secret).toBe(full);
      }
      expect(html.includes("2 related updates in Plus")).toBe(!full);
      expect(html).not.toContain("Price facts in Plus"); // #67 U1: 가격 사실 잠금 문구는 없어졌다
    });
  }
});

describe("가격 표시 플래그 off(#56): 화면 모델에 가격 키가 없다. 세 번째 줄(연관 소식)은 플래그와 무관(#67 U1)", () => {
  afterEach(() => vi.unstubAllEnvs()); // 설정 기본값 on으로 돌아간다(vitest.config.mts)

  const unsupported = line("Not covered yet", "unsupported", null);
  for (const [who, viewer] of VIEWERS) {
    for (const [kind, third] of [...Object.entries(THIRD), ["미지원", unsupported], ["없음(#67 전)", null]] as [string, StoredLine | null][]) {
      test(`${who} × 세 번째 줄 ${kind} → off는 on에서 change 키만 빠진다(줄·하단 같음)`, () => {
        const { change, ...on } = exposeCards([stored(third)], viewer)[0];
        expect(change).toBeDefined();
        vi.stubEnv("PRICE_DISPLAY", undefined);
        const [off] = exposeCards([stored(third)], viewer);
        expect(off).toStrictEqual(on); // toStrictEqual: change: undefined도 실패
        expect(Object.keys(off).sort()).toEqual(["checked", "header", "leverageTag", "lines", "name", "ticker"]);
      });
    }
  }

  test("플래그 값: on(대소문자·앞뒤 공백 무시)만 켜고 없음·빈 값·off·true·1은 끈다", () => {
    const on = (value: string | undefined) => {
      vi.stubEnv("PRICE_DISPLAY", value);
      return "change" in exposeCards([stored(THIRD.있음)], my("plus", "AAPL"))[0];
    };
    for (const value of ["on", "ON", "On", " on\n"]) expect(on(value), JSON.stringify(value)).toBe(true);
    for (const value of [undefined, "", " ", "off", "OFF", "true", "1", "yes", "onn", "o n"]) expect(on(value), JSON.stringify(value)).toBe(false);
  });

  test("DB 값(등락률·종가 날짜 라벨)이 화면 모델(RSC props)과 HTML 어디에도 없다. 가격 사실 잠금 문구도 없다", () => {
    vi.stubEnv("PRICE_DISPLAY", "off");
    const [PCT, LABEL] = ["pct", "label"].map((k) => `canary-${k}-${randomUUID()}`);
    const card = stored(THIRD.있음, { change: { text: PCT, tone: "up", label: LABEL } });
    const coverage = [{ ticker: "AAPL", name: "Apple Inc." }];
    for (const [who, viewer, full] of VIEWERS) {
      const cards = exposeCards([card], viewer);
      const data = { tradingDay: "Fri, Oct 16, 2026", glance: null, cards };
      const mine = viewer ? myDashboardView(cards, coverage, viewer, undefined) : undefined;
      const props = JSON.stringify({ data, mine });
      const html = renderToStaticMarkup(<Dashboard data={data} mine={mine} />);
      for (const secret of [PCT, LABEL, "Price facts in Plus", "data-tone"]) {
        expect(props, `${who} ${secret}`).not.toContain(secret);
        expect(html, `${who} ${secret}`).not.toContain(secret);
      }
      expect(html, who).toContain("Apple reported Q3 results (SEC filing)"); // 두 줄은 그대로
      expect(html.includes(THIRD.있음.text), who).toBe(full); // 세 번째 줄은 off에서도 플랜대로
    }
  });
});

describe("카드 헤더(#63): 첫 번째 줄 상태와 저장 건수로만 정한다", () => {
  afterEach(() => vi.unstubAllEnvs());

  const header = (lines: StoredCard["lines"], newsFilingCount: number | null, viewer: MyStocks | null = null) =>
    exposeCards([stored(null, { lines, newsFilingCount })], viewer)[0].header;
  const OTHERS = [line("Earnings Thu 10/29 after close (D-13)", "checked_found", "Earnings and dividend calendar"), THIRD.있음];

  test("헤더 건수는 저장 건수만 쓰고 문장의 +N more는 읽지 않는다", () => {
    const first = line("Apple named a new CFO +5 more (Company)", "checked_found", "SEC filings");
    expect(header([first, ...OTHERS], 2)).toEqual({ text: "2 new filings", status: "checked_found" });
  });

  test("첫 번째 줄이 확인함·없음이면 다른 줄에 일정·사실이 있어도 Quiet day, 지연·미지원은 Quiet day가 아니다", () => {
    expect(header([line("No new SEC filings found", "checked_none", "SEC filings"), ...OTHERS], null)).toEqual({ text: "Quiet day", status: "checked_none" });
    expect(header([line("Update delayed", "delayed", "SEC filings"), ...OTHERS], null)).toEqual({ text: "Update delayed", status: "delayed" });
    expect(header([line("Not covered yet", "unsupported", null), ...OTHERS], null)).toEqual({ text: "Not covered yet", status: "unsupported" });
    // 다른 줄이 전부 없음이어도 첫 번째 줄이 확인함·있음이면 조용한 날이 아니다
    const none = [line("No confirmed events found", "checked_none", "Earnings and dividend calendar"), THIRD.없음];
    expect(header([line("Apple named a new CFO (Company)", "checked_found", "SEC filings"), ...none], 1)).toEqual({ text: "1 new filing", status: "checked_found" });
  });

  test("#63 전 확인함·있음 카드(건수 없음)는 헤더 없음, 줄·하단은 그대로", () => {
    const [view] = exposeCards([stored(THIRD.있음, { newsFilingCount: null })], null);
    expect(view.header).toBeNull();
    expect(view).toEqual({ ...FREE, header: null });
  });

  test("카드 헤더는 로그인 전·무료·Plus·둘러보기 모두 같다", () => {
    const first = line("Apple named a new CFO +2 more (Company)", "checked_found", "SEC filings");
    for (const [who, viewer] of VIEWERS) {
      expect(header([first, ...OTHERS], 3, viewer), who).toEqual({ text: "3 new filings", status: "checked_found" });
      expect(header([line("No new SEC filings found", "checked_none", "SEC filings"), ...OTHERS], null, viewer), who).toEqual({ text: "Quiet day", status: "checked_none" });
    }
  });

  test("가격 표시 on이면 헤더와 등락률이 같이, off면 헤더만(가격 키 없음)", () => {
    const [on] = exposeCards([stored(THIRD.있음)], null);
    expect([on.header, on.change]).toEqual([{ text: "1 new filing", status: "checked_found" }, { text: "+1.3%", tone: "up", label: "Thu 10/15 close" }]);
    vi.stubEnv("PRICE_DISPLAY", "off");
    const [off] = exposeCards([stored(THIRD.있음)], null);
    expect(off.header).toEqual({ text: "1 new filing", status: "checked_found" });
    expect("change" in off).toBe(false);
  });
});

describe("알아두기(#66): 조용한 날에만 한 문장. 잠기지 않은 내 종목은 그 유저 진도, 그 밖(로그인 전·둘러보기·잠긴 내 종목)은 1번", () => {
  afterEach(() => vi.unstubAllEnvs());

  const FIRST = `canary-quiet-first-${randomUUID()}`; // 공용 1번(getDashboard가 카드에 담는다)
  const MINE = `canary-quiet-mine-${randomUUID()}`; // 그 유저 진도의 오늘 번호(getMyQuietFacts)
  const PROGRESS = new Map([["AAPL", MINE]]);
  const QUIET = line("No new SEC filings found", "checked_none", "SEC filings");
  const EVENT = line("No confirmed events found", "checked_none", "Earnings and dividend calendar");
  const quiet = (over: Partial<StoredCard> = {}) =>
    stored(THIRD.있음, { lines: [QUIET, EVENT, THIRD.있음], newsFilingCount: null, firstQuietFact: FIRST, ...over });
  const fact = (card: StoredCard, viewer: MyStocks | null, progress?: ReadonlyMap<string, string>) => exposeCards([card], viewer, progress)[0];

  const WHO: [string, MyStocks | null, string][] = [
    ["로그인 전", null, FIRST], // 진도를 받아도(실제로는 빈 값) 쓰지 않는다
    ["무료 내 종목", my("free", "AAPL"), MINE],
    ["무료 둘러보기", my("free", "MSFT"), FIRST],
    ["Plus 내 종목", my("plus", "AAPL"), MINE],
    ["Plus 둘러보기", my("plus", "MSFT"), FIRST],
    ["무료 잠긴 내 종목", my("free", "AAPL", true), FIRST],
    ["Plus 잠긴 내 종목", my("plus", "AAPL", true), FIRST],
  ];

  for (const [who, viewer, want] of WHO) {
    test(`${who}: 조용한 날 → ${want === MINE ? "그 유저 진도의 문장" : "1번"}, 무료·Plus 같다`, () => {
      expect(fact(quiet(), viewer, PROGRESS).quietFact).toBe(want);
    });
  }

  test("잠기지 않은 내 종목인데 진도에 없으면(넣기 전·풀 끝·풀 없음) 알아두기 없음: 1번으로 돌아가지 않는다", () => {
    for (const viewer of [my("free", "AAPL"), my("plus", "AAPL")]) {
      expect("quietFact" in fact(quiet(), viewer, new Map())).toBe(false);
      expect("quietFact" in fact(quiet(), viewer)).toBe(false); // 셋째 인자 기본값(지난 카드가 이렇게 부른다)
      expect("quietFact" in fact(quiet(), viewer, new Map([["MSFT", MINE]]))).toBe(false); // 다른 종목의 진도는 쓰지 않는다
    }
  });

  test("조용한 날이 아니면(확인함·있음, 지연, 미지원, 축소판) 1번·진도가 있어도 모든 viewer에게 없다", () => {
    const firsts: StoredCard["lines"][0][] = [
      line("Apple named a new CFO (Company)", "checked_found", "SEC filings"),
      line("Update delayed", "delayed", "SEC filings"),
      line("Not covered yet", "unsupported", null),
      null, // 축소판
    ];
    for (const first of firsts) {
      for (const [who, viewer] of WHO) {
        const view = fact(quiet({ lines: [first, EVENT, THIRD.있음], newsFilingCount: 1 }), viewer, PROGRESS);
        expect("quietFact" in view, `${who} ${first?.status ?? "축소판"}`).toBe(false);
      }
    }
  });

  test("풀 없는 종목(ETF 등, 1번 null)은 둘러보기·로그인 전에도 없다", () => {
    for (const [who, viewer, want] of WHO) {
      const view = fact(quiet({ firstQuietFact: null }), viewer, PROGRESS);
      expect(view.quietFact, who).toBe(want === MINE ? MINE : undefined);
      if (want !== MINE) expect("quietFact" in view, who).toBe(false);
    }
  });

  test("카드 줄 수는 그대로(보조 문장): 가격 표시 on·off 모두 3줄(세 번째 = 연관 소식, #67), 알아두기는 가격 플래그와 무관", () => {
    for (const [who, viewer, want] of WHO) {
      vi.stubEnv("PRICE_DISPLAY", "on");
      const on = fact(quiet(), viewer, PROGRESS);
      vi.stubEnv("PRICE_DISPLAY", "off");
      const off = fact(quiet(), viewer, PROGRESS);
      expect([on.lines.length, on.quietFact], who).toEqual([3, want]);
      expect([off.lines.length, off.quietFact, "change" in off], who).toEqual([3, want, false]);
    }
  });

  test("화이트리스트: 알아두기가 있으면 키 목록에 quietFact(문자열)만 더해진다", () => {
    const KEYS = ["change", "checked", "header", "leverageTag", "lines", "name", "ticker"];
    for (const [who, viewer] of WHO) {
      const view = fact(quiet(), viewer, PROGRESS);
      expect(Object.keys(view).sort(), who).toEqual([...KEYS, "quietFact"].sort());
      expect(typeof view.quietFact, who).toBe("string");
    }
  });

  test("다른 viewer의 진도 문장은 화면 모델(RSC props)·HTML에 없고, 보이는 문장은 Did you know: … (Annual report)", () => {
    const coverage = [{ ticker: "AAPL", name: "Apple Inc." }];
    for (const [who, viewer, want] of WHO) {
      const cards = exposeCards([quiet()], viewer, want === MINE ? PROGRESS : new Map());
      const data = { tradingDay: "Fri, Oct 16, 2026", glance: null, cards };
      const mine = viewer ? myDashboardView(cards, coverage, viewer, undefined) : undefined;
      const html = renderToStaticMarkup(<Dashboard data={data} mine={mine} />);
      const other = want === MINE ? FIRST : MINE;
      expect(JSON.stringify({ data, mine }), who).not.toContain(other);
      expect(html, who).not.toContain(other);
      expect(html, who).toContain(`Did you know: ${want} (Annual report)`);
    }
  });
});

describe("지난 카드(#68): 한 종목의 날짜별 카드. Plus = 받은 날 전부, 무료 = 오늘만 + 잠금 안내", () => {
  afterEach(() => vi.unstubAllEnvs());

  const TODAY = "2026-10-16";
  const OLD = `canary-old-${randomUUID()}`; // 지난 날 카드의 세 번째 줄
  const SUSPENDED = `canary-suspended-past-${randomUUID()}`;
  const AAPL = { ticker: "AAPL", name: "Apple Inc." };
  const history = {
    today: TODAY,
    cards: [
      { day: TODAY, card: stored(THIRD.있음) },
      { day: "2026-10-15", card: stored(line(SUSPENDED, "checked_found", "SEC filings"), { suspended: true }) },
      { day: "2026-07-20", card: stored(line(OLD, "checked_found", "SEC filings")) },
    ],
  };
  const KEYS = ["change", "checked", "header", "leverageTag", "lines", "name", "ticker"]; // 오늘 카드(exposeCards)와 같은 키

  test("범위(읽기가 쓰는 값): Plus 90일, 무료 1일(오늘)", () => {
    expect(pastCardDays("plus")).toBe(90);
    expect(pastCardDays("free")).toBe(1);
  });

  test("Plus 내 종목: 최신순, 카드마다 세 번째 줄 본문, 발행 중단 날은 빠짐, 잠금 안내 없음", () => {
    const view = exposePastCards(AAPL, history, my("plus", "AAPL"));
    expect(view).toEqual({
      ...AAPL,
      locked: false,
      days: [
        { day: "Fri, Oct 16, 2026", card: FULL.있음 },
        {
          day: "Mon, Jul 20, 2026",
          card: {
            ...FREE,
            lines: [...FIRST_TWO, { text: OLD, status: "checked_found" }],
            checked: "Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar",
          },
        },
      ],
    });
    expect(JSON.stringify(view)).not.toContain(SUSPENDED);
  });

  test("무료 내 종목: 지난 날 카드를 받아도 오늘만 + locked, 세 번째 줄은 건수만", () => {
    const view = exposePastCards(AAPL, history, my("free", "AAPL"));
    expect(view).toEqual({ ...AAPL, locked: true, days: [{ day: "Fri, Oct 16, 2026", card: FREE }] });
    expect(JSON.stringify(view)).not.toContain(OLD);
  });

  test("오늘 카드가 없거나 발행 중단이면 첫 칸은 card null(카드 없음 자리), 지난 날은 그대로", () => {
    const missing = exposePastCards(AAPL, { today: TODAY, cards: history.cards.slice(1) }, my("plus", "AAPL"));
    expect(missing.days.map((d) => [d.day, d.card && d.card.lines[2]])).toEqual([
      ["Fri, Oct 16, 2026", null],
      ["Mon, Jul 20, 2026", { text: OLD, status: "checked_found" }],
    ]);
    const suspended = { today: TODAY, cards: [{ day: TODAY, card: stored(THIRD.있음, { suspended: true }) }] };
    for (const plan of ["free", "plus"] as const) expect(exposePastCards(AAPL, suspended, my(plan, "AAPL")).days).toEqual([{ day: "Fri, Oct 16, 2026", card: null }]);
  });

  test("DB에 카드가 하나도 없으면(today null) 날 없음", () => {
    expect(exposePastCards(AAPL, { today: null, cards: [] }, my("plus", "AAPL"))).toEqual({ ...AAPL, locked: false, days: [] });
  });

  test("가격 표시 off: 모든 날 카드에 가격 키 없음, 세 번째 줄은 on과 같다(Plus 지난 날 본문, 무료 오늘 건수만)", () => {
    vi.stubEnv("PRICE_DISPLAY", undefined);
    for (const plan of ["free", "plus"] as const) {
      const view = exposePastCards(AAPL, history, my(plan, "AAPL"));
      expect(view.days.length, plan).toBe(plan === "plus" ? 2 : 1);
      for (const { card } of view.days) {
        expect(Object.keys(card!).sort(), plan).toEqual(KEYS.filter((k) => k !== "change"));
        expect(card!.lines, plan).toHaveLength(3);
      }
      expect(view.days[0].card!.lines[2], plan).toEqual(plan === "plus" ? { text: THIRD.있음.text, status: "checked_found" } : { status: "locked", count: 2 });
      expect(JSON.stringify(view).includes(OLD), plan).toBe(plan === "plus");
      expect(JSON.stringify(view), plan).not.toMatch(/Thu 10\/15 close|\+1\.3%/);
    }
  });

  test("알아두기(#66)는 지난 카드에 없다: 조용한 날 카드에 1번이 담겨 와도(읽기는 null을 담는다) 유저 진도를 넘기지 않는다", () => {
    const FACT = `canary-past-quiet-${randomUUID()}`;
    const QUIET = line("No new SEC filings found", "checked_none", "SEC filings");
    const quiet = stored(THIRD.있음, { lines: [QUIET, null, null], newsFilingCount: null, firstQuietFact: FACT });
    const days = { today: TODAY, cards: [{ day: TODAY, card: quiet }, { day: "2026-10-14", card: quiet }] };
    for (const plan of ["free", "plus"] as const) {
      const view = exposePastCards(AAPL, days, my(plan, "AAPL"));
      expect(view.days.length, plan).toBe(plan === "plus" ? 2 : 1);
      for (const d of view.days) expect("quietFact" in d.card!, plan).toBe(false);
      expect(JSON.stringify(view), plan).not.toContain(FACT);
    }
  });

  test("화이트리스트: 날 칸은 day·card만, 카드는 오늘 카드와 같은 키만(알아두기 등 새 키는 지난 카드에 붙이지 않는다)", () => {
    for (const plan of ["free", "plus"] as const) {
      const view = exposePastCards(AAPL, history, my(plan, "AAPL"));
      expect(Object.keys(view).sort(), plan).toEqual(["days", "locked", "name", "ticker"]);
      for (const d of view.days) {
        expect(Object.keys(d).sort(), plan).toEqual(["card", "day"]);
        expect(Object.keys(d.card!).sort(), plan).toEqual(KEYS);
      }
    }
  });
});

describe("잠긴 자리(#69): 공용 카드 속성이라 모든 viewer·가격 플래그에 같고, 값이 있을 때만 키가 생긴다", () => {
  const SLOTS = ["earnings_summary", "big_holders"] as const;

  test("비 ETF 카드: 로그인 전·무료·Plus·내 종목·둘러보기 모두 같은 lockedSlot, 키 = 기존 + lockedSlot", () => {
    for (const lockedSlot of SLOTS) {
      for (const [who, viewer] of VIEWERS) {
        const [view] = exposeCards([stored(THIRD.있음, { lockedSlot })], viewer);
        expect(view.lockedSlot, who).toBe(lockedSlot);
        expect(Object.keys(view).sort(), who).toEqual(["change", "checked", "header", "leverageTag", "lines", "lockedSlot", "name", "ticker"]);
      }
    }
  });

  test("가격 표시 off여도 그대로(가격 키가 아니다)", () => {
    vi.stubEnv("PRICE_DISPLAY", undefined);
    for (const [who, viewer] of VIEWERS) {
      const [view] = exposeCards([stored(THIRD.있음, { lockedSlot: "big_holders" })], viewer);
      expect(view.lockedSlot, who).toBe("big_holders");
      expect("change" in view, who).toBe(false);
    }
  });

  test("ETF(lockedSlot null)는 키 자체가 없다(undefined 키도 아니다)", () => {
    for (const [who, viewer] of VIEWERS) expect("lockedSlot" in exposeCards([stored(THIRD.있음)], viewer)[0], who).toBe(false);
  });

  test("발행 중단 카드는 잠긴 자리가 있어도 빠진다", () => {
    expect(exposeCards([stored(THIRD.있음, { suspended: true, lockedSlot: "earnings_summary" })], null)).toEqual([]);
  });
});
