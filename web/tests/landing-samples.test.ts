/** 랜딩 샘플 카드 = 실제 카드(#93). 2026-11-06 원격 행(픽스처) → 대시보드와 같은 변환(dashboardCards → exposeCards, 로그인 전, 가격 표시 off) = SAMPLES. DB 없음 */
import { afterEach, expect, test, vi } from "vitest";

import { formatTradingDay } from "@/lib/card-view";
import { SAMPLE_DAY, SAMPLES } from "@/lib/samples";
import { dashboardCards, type DashboardRow } from "@/server/cards";
import { exposeCards } from "@/server/exposure";

import fixture from "./fixtures/cards-2026-11-06.json";

afterEach(() => vi.unstubAllEnvs());

test("랜딩 샘플은 2026-11-06 실제 행을 로그인 전 대시보드가 그리는 화면 모델과 같다(헤더·줄·잠긴 자리·하단 확인 줄)", () => {
  vi.stubEnv("PRICE_DISPLAY", "off"); // 운영 값(가격 표시 off)
  const stored = dashboardCards(
    fixture.rows as DashboardRow[],
    new Map(fixture.quietFacts.map((f: { ticker: string; text: string }) => [f.ticker, f.text])),
    new Map(fixture.estimates.map((e) => [e.ticker, e.estimate_day])),
    fixture.day,
  );
  expect(SAMPLES).toStrictEqual(exposeCards(stored, null));
  expect(SAMPLE_DAY).toBe(fixture.day);
  expect(formatTradingDay(SAMPLE_DAY)).toBe("Fri, Nov 6, 2026");
});
