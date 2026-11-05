import { describe, expect, test } from "vitest";

import {
  cardHeaderView,
  changeView,
  checkedFooter,
  formatCheckedAt,
  formatCloseDay,
  formatTradingDay,
  glanceView,
  lineView,
  myDashboardView,
  QUERY_MAX,
  QUIET_DAY_STATUS,
  SEARCH_MAX,
  searchStocks,
  type CardView,
  type LineStatus,
} from "@/lib/card-view";

describe("changeView: DB 값에 형식만 입힌다", () => {
  test.each([
    [1.2, "+1.2%", "up"],
    [12, "+12.0%", "up"],
    [-1.2, "−1.2%", "down"], // 진짜 마이너스 U+2212
    [0, "0.0%", "flat"],
    [-0, "0.0%", "flat"],
  ] as const)("%s → %s (%s)", (pct, text, tone) => {
    expect(changeView(pct, "checked_found", "2026-10-15")).toEqual({ text, tone, label: "Thu 10/15 close" });
  });

  test("하이픈 마이너스를 쓰지 않는다", () => {
    expect(changeView(-3.4, "checked_found", null).text).not.toContain("-");
  });

  test("지연·미지원은 고정 문구(HANDOFF 3-3 리터럴). 종가 날짜 라벨은 그대로(그날 종가가 지연이라는 뜻, #16 D8)", () => {
    expect(changeView(null, "delayed", "2026-10-15")).toEqual({ text: "Update delayed", tone: "delayed", label: "Thu 10/15 close" });
    expect(changeView(null, "unsupported", "2026-10-15")).toEqual({ text: "Not covered yet", tone: "unsupported", label: "Thu 10/15 close" });
  });

  test("종가 날짜가 없는 옛 카드(#16 전)는 prev close", () => {
    for (const status of ["checked_found", "delayed", "unsupported"] as const) {
      expect(changeView(status === "checked_found" ? 1.2 : null, status, null).label).toBe("prev close");
    }
  });
});

describe("formatCloseDay: 종가 날짜 → 요일 M/D (두 번째 줄 날짜와 같은 형식, #16)", () => {
  test.each([
    ["2026-10-15", "Thu 10/15"],
    ["2026-01-02", "Fri 1/2"], // 월·일 앞 0 없음. 시간대 이동이 있으면 전날(Thu 1/1)로 밀린다
    ["2026-11-25", "Wed 11/25"],
    ["2026-12-31", "Thu 12/31"],
  ])("%s → %s", (day, text) => {
    expect(formatCloseDay(day)).toBe(text);
  });
});

describe("formatCheckedAt: America/New_York 시각", () => {
  test.each([
    ["2026-10-16T11:30:00+00:00", "7:30 AM ET"], // EDT
    ["2026-12-01T12:05:00Z", "7:05 AM ET"], // EST
    ["2026-10-16T20:30:00Z", "4:30 PM ET"],
    ["2026-10-16T04:00:00Z", "12:00 AM ET"],
    // 서머타임 경계 (2026-03-08 시작, 2026-11-01 끝)
    ["2026-03-08T06:59:59Z", "1:59 AM ET"],
    ["2026-03-08T07:00:00Z", "3:00 AM ET"],
    ["2026-11-01T05:59:00Z", "1:59 AM ET"],
    ["2026-11-01T06:00:00Z", "1:00 AM ET"],
  ])("%s → %s", (iso, text) => {
    expect(formatCheckedAt(iso)).toBe(text);
  });
});

test("formatTradingDay: 날짜만(시간대 이동 없음)", () => {
  expect(formatTradingDay("2026-10-16")).toBe("Fri, Oct 16, 2026");
  expect(formatTradingDay("2027-01-01")).toBe("Fri, Jan 1, 2027");
});

describe("lineView", () => {
  test("DB 문구·상태를 그대로", () => {
    expect(lineView({ text: "No confirmed events found", status: "checked_none" })).toEqual({
      text: "No confirmed events found",
      status: "checked_none",
    });
  });

  test("줄이 없으면(축소판의 첫 번째 줄 등) 숨기지 않고 지연 문구", () => {
    expect(lineView(null)).toEqual({ text: "Update delayed", status: "delayed" });
  });
});

describe("cardHeaderView: 첫 번째 줄 상태 → 카드 헤더 고정 문구(#63)", () => {
  test("확인함·있음은 저장 건수로 N new filing(s): 1은 단수, 2 이상 복수", () => {
    expect(cardHeaderView("checked_found", 1)).toEqual({ text: "1 new filing", status: "checked_found" });
    expect(cardHeaderView("checked_found", 2)).toEqual({ text: "2 new filings", status: "checked_found" });
    expect(cardHeaderView("checked_found", 12)).toEqual({ text: "12 new filings", status: "checked_found" });
  });

  test("확인함·없음 Quiet day, 지연 Update delayed, 미지원 Not covered yet(건수는 보지 않는다)", () => {
    expect(cardHeaderView("checked_none", null)).toEqual({ text: "Quiet day", status: "checked_none" });
    expect(cardHeaderView("delayed", null)).toEqual({ text: "Update delayed", status: "delayed" });
    expect(cardHeaderView("unsupported", null)).toEqual({ text: "Not covered yet", status: "unsupported" });
    expect(cardHeaderView("checked_none", 3)).toEqual({ text: "Quiet day", status: "checked_none" }); // DB 제약상 없지만 건수가 와도 상태가 정한다
  });

  test("첫 번째 줄이 없으면(축소판) Update delayed: lineView(null)과 같은 판단", () => {
    expect(cardHeaderView(null, null)).toEqual({ text: "Update delayed", status: "delayed" });
  });

  test("확인함·있음인데 건수가 없거나 1 미만이면(#63 전 카드) 헤더 없음: 숫자를 지어내지 않는다", () => {
    for (const n of [null, 0, -1]) expect(cardHeaderView("checked_found", n), String(n)).toBeNull();
  });

  test("조용한 날 = 첫 번째 줄 checked_none 하나뿐", () => {
    expect(QUIET_DAY_STATUS).toBe("checked_none");
  });
});

describe("checkedFooter: 확인된 줄(확인함·있음/없음)만", () => {
  const at = (checked_at: string, status: LineStatus, source_scope: string | null) => ({ checked_at, status, source_scope });

  test("가장 이른 확인 시각 + 출처 범위(줄 순서, 중복 제외)", () => {
    expect(
      checkedFooter([
        at("2026-10-16T11:45:00Z", "checked_found", "SEC filings"),
        at("2026-10-16T11:30:00Z", "checked_none", "Earnings and dividend calendar"), // 가장 이른 시각이 가운데
        at("2026-10-16T11:50:00Z", "checked_found", "SEC filings"),
      ]),
    ).toBe("Checked 7:30 AM ET · SEC filings · Earnings and dividend calendar");
  });

  test("지연·미지원 줄의 시각·출처는 넣지 않는다", () => {
    expect(
      checkedFooter([
        at("2026-10-16T11:45:00Z", "checked_none", "Earnings and dividend calendar"),
        at("2026-10-16T11:00:00Z", "delayed", "Daily prices"),
        at("2026-10-16T11:10:00Z", "unsupported", null),
      ]),
    ).toBe("Checked 7:45 AM ET · Earnings and dividend calendar");
  });

  test("확인된 줄이 없으면 하단 없음", () => {
    expect(
      checkedFooter([at("2026-10-16T11:30:00Z", "delayed", "Daily prices"), at("2026-10-16T11:30:00Z", "unsupported", null)]),
    ).toBeNull();
    expect(checkedFooter([])).toBeNull();
  });
});

describe("glanceView: 시장 한눈에(#11)", () => {
  const stored = (text: string, status: LineStatus, checked_at: string, source_scope: string | null) => ({ text, status, checked_at, source_scope });

  test("DB 문구·상태를 줄 순서 그대로, 하단은 확인된 줄의 가장 이른 시각 + 범위", () => {
    expect(
      glanceView([
        stored("Thu 10/15 close: S&P 500 (SPY) +0.4%, Nasdaq (QQQ) \u22121.2%", "checked_found", "2026-10-16T11:31:00Z", "Daily prices"),
        stored("No economic releases found", "checked_none", "2026-10-16T11:30:00Z", "Economic calendar"),
        stored("Contoso Labor Bureau reported consumer prices rose 0.3%", "checked_found", "2026-10-16T11:32:00Z", "Official releases"),
      ]),
    ).toEqual({
      lines: [
        { text: "Thu 10/15 close: S&P 500 (SPY) +0.4%, Nasdaq (QQQ) \u22121.2%", status: "checked_found" },
        { text: "No economic releases found", status: "checked_none" },
        { text: "Contoso Labor Bureau reported consumer prices rose 0.3%", status: "checked_found" },
      ],
      checked: "Checked 7:30 AM ET · Daily prices · Economic calendar · Official releases",
    });
  });

  test("운영 지금 값(지연·미지원·미지원): 문구는 그대로, 확인된 줄이 없으니 하단 없음", () => {
    expect(
      glanceView([
        stored("Update delayed", "delayed", "2026-10-16T11:30:00Z", "Daily prices"),
        stored("Not covered yet", "unsupported", "2026-10-16T11:30:00Z", null),
        stored("Not covered yet", "unsupported", "2026-10-16T11:30:00Z", null),
      ]),
    ).toEqual({
      lines: [
        { text: "Update delayed", status: "delayed" },
        { text: "Not covered yet", status: "unsupported" },
        { text: "Not covered yet", status: "unsupported" },
      ],
      checked: null,
    });
  });

  test("그날 행이 없으면(null) 줄을 숨기지 않고 Update delayed 세 줄, 하단 없음", () => {
    expect(glanceView(null)).toEqual({
      lines: Array(3).fill({ text: "Update delayed", status: "delayed" }),
      checked: null,
    });
  });

  test("허용한 키만 옮긴다: 줄에 다른 값(보류 초안 등)이 붙어 와도 화면 모델에 없다", () => {
    const extra = { ...stored("a", "checked_found", "2026-10-16T11:30:00Z", "Daily prices"), hold_draft: "canary-hold" };
    const view = glanceView([extra, extra, extra]);
    expect(Object.keys(view).sort()).toEqual(["checked", "lines"]);
    for (const l of view.lines) expect(Object.keys(l).sort()).toEqual(["status", "text"]);
    expect(JSON.stringify(view)).not.toContain("canary-hold");
  });
});

describe("myDashboardView: 로그인한 대시보드(#38)", () => {
  const card = (ticker: string): CardView => ({
    ticker,
    name: `${ticker} Inc.`,
    change: { text: "+1.0%", tone: "up", label: "Thu 10/15 close" },
    header: null,
    lines: [],
    leverageTag: null,
    checked: null,
  });
  const stock = (ticker: string, locked = false) => ({ ticker, name: `${ticker} Inc.`, locked });
  const coverage = ["AAPL", "MSFT", "NVDA", "TSLA", "TQQQ"].map((t) => ({ ticker: t, name: `${t} Inc.` }));
  const cards = ["AAPL", "MSFT", "NVDA", "TSLA"].map(card);

  test("내 종목 = 잠기지 않은 것만 넣은 순서로(카드 없으면 null), 둘러보기 = 나머지 카드, 고르기 = 내 종목(잠긴 것 포함)이 아닌 커버 범위의 검색 결과(#58)", () => {
    const view = myDashboardView(cards, coverage, { stocks: [stock("TQQQ"), stock("MSFT"), stock("NVDA", true)], swapsLeft: 2 }, undefined, " inc ");
    expect(view).toEqual({
      mine: [
        { ticker: "TQQQ", name: "TQQQ Inc.", card: null },
        { ticker: "MSFT", name: "MSFT Inc.", card: card("MSFT") },
      ],
      browse: [card("AAPL"), card("NVDA"), card("TSLA")],
      pickable: [
        { ticker: "AAPL", name: "AAPL Inc." },
        { ticker: "TSLA", name: "TSLA Inc." },
      ],
      query: "inc",
      more: false,
      swapsLeft: 2,
      notice: null,
    });
  });

  test("검색어가 없으면 고르기 결과 없음(커버 범위 약 550개를 다 그리지 않는다, #58 D10)", () => {
    for (const q of [undefined, "", "   ", ["AAPL"], 1]) {
      const view = myDashboardView(cards, coverage, { stocks: [], swapsLeft: 3 }, undefined, q);
      expect([view.pickable, view.query, view.more], String(q)).toEqual([[], "", false]);
    }
  });

  test("검색 결과에서 내 종목(잠긴 것 포함)은 빠진다: 티커가 같아도", () => {
    const my = { stocks: [stock("NVDA", true), stock("TSLA")], swapsLeft: 1 };
    const pick = (q: string) => myDashboardView(cards, coverage, my, undefined, q).pickable.map((s) => s.ticker);
    expect([pick("nvda"), pick("tsla"), pick("aapl")]).toEqual([[], [], ["AAPL"]]);
  });

  test("Plus는 남은 교체 null 그대로", () => {
    expect(myDashboardView(cards, coverage, { stocks: [], swapsLeft: null }, undefined).swapsLeft).toBeNull();
  });

  test("결과 코드 → 고정 문구(HANDOFF 3-2 리터럴), 모르는 값은 문구 없음", () => {
    const notice = (result: unknown) => myDashboardView([], [], { stocks: [], swapsLeft: 3 }, result).notice;
    expect(notice("free_swap_limit")).toBe("Free plan can swap stocks 3 times a day. Plus has no limit.");
    expect(notice("free_my_stock_limit")).toBe("Free plan can pick 3 stocks. Remove one to add another.");
    expect(notice("failed")).toBe("My stocks could not be updated");
    for (const other of [undefined, "", "ok", "constructor", "__proto__", "toString", ["failed"], "<script>"]) {
      expect(notice(other), String(other)).toBeNull();
    }
  });
});

describe("searchStocks: 서버가 고르기 후보를 거른다(#58 D10)", () => {
  // 커버 범위는 DB에서 티커순으로 온다(getCoverage)
  const COVERAGE = [
    ["AMAT", "Applied Materials"],
    ["AMZN", "Amazon"],
    ["BRK-B", "Berkshire Hathaway"],
    ["KO", "Coca-Cola"],
    ["MA", "Mastercard"],
    ["MAR", "Marriott International"],
    ["MAS", "Masco"],
    ["MSFT", "Microsoft"],
    ["T", "AT&T"],
  ].map(([ticker, name]) => ({ ticker, name }));
  const tickers = (q: unknown) => searchStocks(COVERAGE, q as string).results.map((s) => s.ticker);

  test("순서: 티커 같음 → 티커로 시작 → 이름에 포함, 같은 묶음은 받은(티커) 순서, 중복 없음", () => {
    // MAR·MAS는 티커로 시작하고 이름에도 ma가 있지만 한 번만, AMAT·AMZN은 이름(Applied MAterials, AMAzon)으로
    expect(tickers("ma")).toEqual(["MA", "MAR", "MAS", "AMAT", "AMZN"]);
  });

  test("대소문자·앞뒤 공백 무시", () => {
    for (const q of ["MA", "Ma", "mA", "  ma\t"]) expect(tickers(q), q).toEqual(["MA", "MAR", "MAS", "AMAT", "AMZN"]);
  });

  test("티커의 . 은 - 와 같다(BRK.B = BRK-B)", () => {
    for (const q of ["brk.b", "BRK.B", "brk-b"]) expect(tickers(q), q).toEqual(["BRK-B"]);
    expect(tickers("brk.")).toEqual(["BRK-B"]);
  });

  test("이름은 영숫자 밖 글자를 공백 하나로 보고 비교한다(coca cola = Coca-Cola, at&t = AT&T)", () => {
    for (const q of ["coca cola", "Coca-Cola", "COCA  COLA", "coca.cola"]) expect(tickers(q), q).toEqual(["KO"]);
    expect(tickers("at&t")).toEqual(["T"]);
    expect(tickers("at t")).toEqual(["T"]);
    expect(tickers("berkshire")).toEqual(["BRK-B"]);
  });

  test("빈 검색어·공백·문자열 아닌 값은 결과 없음", () => {
    for (const q of ["", "   ", "\n", undefined, null, ["ma"], 42, { q: "ma" }]) {
      expect(searchStocks(COVERAGE, q as string), JSON.stringify(q)).toEqual({ results: [], more: false });
    }
  });

  test("검색어는 앞 40자만 본다", () => {
    expect(QUERY_MAX).toBe(40);
    const long = [{ ticker: "LONG", name: `${"a".repeat(40)} Holdings` }];
    expect(searchStocks(long, `${"a".repeat(40)}zzz`).results).toEqual(long); // 41자부터는 버린다
    expect(searchStocks(long, `${"a".repeat(39)}z`).results).toEqual([]);
  });

  test("최대 20개, 넘으면 more", () => {
    expect(SEARCH_MAX).toBe(20);
    const many = (n: number) => Array.from({ length: n }, (_, i) => ({ ticker: `X${String(i).padStart(2, "0")}`, name: `Fund ${i}` }));
    expect(searchStocks(many(21), "x")).toEqual({ results: many(20), more: true });
    expect(searchStocks(many(20), "x")).toEqual({ results: many(20), more: false });
  });

  test("이상한 입력(SQL·PostgREST 필터·와일드카드·HTML)은 글자 그대로 비교한다: 전부 맞거나 에러가 나지 않는다", () => {
    for (const q of ["%", "*", "_", "'", '"', ".", "-", "&", "\\", "' OR 1=1 --", "'; DROP TABLE coverage;--", "or(ticker.eq.AAPL)", "name.ilike.*", "a,b", "<script>", "%00", "\u0000", "🙂"]) {
      expect(tickers(q), q).toEqual([]);
    }
  });
});
