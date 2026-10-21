/** 화면 모델 타입과 표시 형식 순수 함수. 문장은 만들지 않는다: DB 문구 그대로 또는 copy.ts 고정 문구. */
import { CHECKED_PREFIX, NOT_COVERED, UPDATE_DELAYED } from "./copy";

export type LineStatus = "checked_found" | "checked_none" | "delayed" | "unsupported"; // DB enum line_status
export type LineView = { text: string; status: LineStatus };
export type ChangeView = { text: string; tone: "up" | "down" | "flat" | "delayed" | "unsupported" };
export type CardView = {
  ticker: string;
  name: string;
  change: ChangeView;
  lines: LineView[]; // 항상 3개(첫 번째·두 번째·세 번째 줄)
  leverageTag: string | null;
  checked: string | null; // "Checked 7:30 AM ET · SEC filings"
};
export type DashboardView = { tradingDay: string | null; cards: CardView[] };

/** DB 등락률(소수 첫째 자리)에 부호·%만 붙인다. 값은 계산함(checked_found)일 때만 있다(DB 제약). */
export function changeView(pct: number | null, status: LineStatus): ChangeView {
  if (status === "unsupported") return { text: NOT_COVERED, tone: "unsupported" };
  if (status !== "checked_found" || pct === null) return { text: UPDATE_DELAYED, tone: "delayed" };
  const abs = Math.abs(pct).toFixed(1);
  if (abs === "0.0") return { text: "0.0%", tone: "flat" }; // -0도 보합
  return pct > 0 ? { text: `+${abs}%`, tone: "up" } : { text: `−${abs}%`, tone: "down" };
}

/** 없는 줄(아직 안 만듦, 축소판의 첫 번째 줄)도 숨기지 않고 지연으로 그린다. */
export function lineView(line: LineView | null): LineView {
  return line ?? { text: UPDATE_DELAYED, status: "delayed" };
}

const ET_TIME = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

/** "7:30 AM ET". format() 대신 조각을 이어 붙인다: ICU가 AM 앞에 좁은 공백(U+202F)을 넣는다. */
export function formatCheckedAt(iso: string): string {
  const p = Object.fromEntries(ET_TIME.formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.hour}:${p.minute} ${p.dayPeriod} ET`;
}

const DAY = new Intl.DateTimeFormat("en-US", {
  timeZone: "UTC", // trading_day는 날짜만 있는 값이라 UTC 자정으로 읽고 UTC로 그린다
  weekday: "short",
  month: "short",
  day: "numeric",
  year: "numeric",
});

/** "2026-10-16" → "Fri, Oct 16, 2026" */
export const formatTradingDay = (day: string) => DAY.format(new Date(`${day}T00:00:00Z`));

/** 카드 하단 한 줄. 확인된 줄(확인함·있음/없음)만 넣는다: 지연·미지원 출처가 "Checked"로 읽히지 않게.
 * 시각은 그 줄들 중 가장 이른 시각(더 새것처럼 보이지 않게), 출처 범위는 줄 순서·중복 제거. 확인된 줄이 없으면 null. */
export function checkedFooter(
  lines: { status: LineStatus; checked_at: string; source_scope: string | null }[],
): string | null {
  const checked = lines.filter((l) => l.status === "checked_found" || l.status === "checked_none");
  if (checked.length === 0) return null;
  const first = checked.map((l) => l.checked_at).reduce((a, b) => (Date.parse(a) <= Date.parse(b) ? a : b));
  const scopes = new Set(checked.flatMap((l) => (l.source_scope ? [l.source_scope] : [])));
  return [`${CHECKED_PREFIX} ${formatCheckedAt(first)}`, ...scopes].join(" · ");
}
