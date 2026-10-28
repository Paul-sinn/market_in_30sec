import { describe, expect, test } from "vitest";

import {
  changeView,
  checkedFooter,
  formatCheckedAt,
  formatCloseDay,
  formatTradingDay,
  lineView,
  myDashboardView,
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

describe("myDashboardView: 로그인한 대시보드(#38)", () => {
  const card = (ticker: string): CardView => ({
    ticker,
    name: `${ticker} Inc.`,
    change: { text: "+1.0%", tone: "up", label: "Thu 10/15 close" },
    lines: [],
    leverageTag: null,
    checked: null,
  });
  const stock = (ticker: string, locked = false) => ({ ticker, name: `${ticker} Inc.`, locked });
  const coverage = ["AAPL", "MSFT", "NVDA", "TSLA", "TQQQ"].map((t) => ({ ticker: t, name: `${t} Inc.` }));
  const cards = ["AAPL", "MSFT", "NVDA", "TSLA"].map(card);

  test("내 종목 = 잠기지 않은 것만 넣은 순서로(카드 없으면 null), 둘러보기 = 나머지 카드, 고르기 = 내 종목(잠긴 것 포함)이 아닌 커버 범위", () => {
    const view = myDashboardView(cards, coverage, { stocks: [stock("TQQQ"), stock("MSFT"), stock("NVDA", true)], swapsLeft: 2 }, undefined);
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
      swapsLeft: 2,
      notice: null,
    });
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
