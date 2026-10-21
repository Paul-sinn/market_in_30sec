import { describe, expect, test } from "vitest";

import { changeView, checkedFooter, formatCheckedAt, formatTradingDay, lineView, type LineStatus } from "@/lib/card-view";

describe("changeView: DB 값에 형식만 입힌다", () => {
  test.each([
    [1.2, "+1.2%", "up"],
    [12, "+12.0%", "up"],
    [-1.2, "−1.2%", "down"], // 진짜 마이너스 U+2212
    [0, "0.0%", "flat"],
    [-0, "0.0%", "flat"],
  ] as const)("%s → %s (%s)", (pct, text, tone) => {
    expect(changeView(pct, "checked_found")).toEqual({ text, tone });
  });

  test("하이픈 마이너스를 쓰지 않는다", () => {
    expect(changeView(-3.4, "checked_found").text).not.toContain("-");
  });

  test("지연·미지원은 고정 문구(HANDOFF 3-3 리터럴)", () => {
    expect(changeView(null, "delayed")).toEqual({ text: "Update delayed", tone: "delayed" });
    expect(changeView(null, "unsupported")).toEqual({ text: "Not covered yet", tone: "unsupported" });
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
