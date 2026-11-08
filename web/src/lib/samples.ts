/**
 * 랜딩 샘플 카드(#93): 2026-11-06 실제 카드 세 장. 로그인 전 대시보드가 그 행을 exposeCards로 그린 모양 그대로(가격 표시 off).
 * 지어낸 예시가 아니다. 행 → 이 값은 tests/landing-samples.test.ts가 확인한다(픽스처 tests/fixtures/cards-2026-11-06.json).
 * 고른 이유: 초보가 읽기 쉬운 공시(MSFT 이사 불출마), ETF(SCHD 상위 편입 종목 공시), 조용한 날 + 실적 D-12(NVDA).
 * 그날은 세 번째 줄(#67) 전이라 두 줄이고, 알아두기 1번 행이 없었다.
 */
import type { CardView } from "./card-view";

export const SAMPLE_DAY = "2026-11-06";

export const SAMPLES = [
  {
    ticker: "MSFT",
    name: "Microsoft",
    header: { text: "1 new filing", status: "checked_found" },
    lines: [
      { text: "Microsoft said director Emma Walmsley will not stand for re-election at its annual meeting (SEC filing)", status: "checked_found" },
      { text: "Earnings Wed 1/27 after close (est.) (D-82)", status: "checked_found" },
    ],
    leverageTag: null,
    checked: "Checked 4:17 AM ET · SEC filings",
    lockedSlot: "big_holders", // 추정 실적일까지 82일(7일 밖)
  },
  {
    ticker: "SCHD",
    name: "Schwab U.S. Dividend Equity ETF",
    header: { text: "1 new filing", status: "checked_found" },
    lines: [
      {
        text: "ConocoPhillips reported third-quarter cash from operations of $7.2B and raised its quarterly dividend (SEC filing)",
        status: "checked_found",
      },
      { text: "Not covered yet", status: "unsupported" }, // ETF: 실적 없음, 배당 출처 없음
    ],
    leverageTag: null,
    checked: "Checked 4:17 AM ET · SEC filings of 10 top holdings", // ETF 첫 번째 줄 = 상위 편입 종목 공시
  },
  {
    ticker: "NVDA",
    name: "NVIDIA",
    header: { text: "Quiet day", status: "checked_none" },
    lines: [
      { text: "No new SEC filings found", status: "checked_none" },
      { text: "Earnings Wed 11/18 after close (est.) (D-12)", status: "checked_found" },
    ],
    leverageTag: null,
    checked: "Checked 4:17 AM ET · SEC filings",
    lockedSlot: "big_holders", // D-12(7일 밖)
  },
] satisfies CardView[];
