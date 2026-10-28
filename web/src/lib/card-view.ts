/** 화면 모델 타입과 표시 형식 순수 함수. 문장은 만들지 않는다: DB 문구 그대로 또는 copy.ts 고정 문구. */
import { CHECKED_PREFIX, DAY_CLOSE, MY_STOCK_NOTICE, NOT_COVERED, PREV_CLOSE, UPDATE_DELAYED } from "./copy";

export type LineStatus = "checked_found" | "checked_none" | "delayed" | "unsupported"; // DB enum line_status
type TextLine = { text: string; status: LineStatus };
/** locked = 무료 범위의 세 번째 줄(#9): 글자 없이 상태만 온다. 화면은 copy.ts의 PRICE_FACTS_IN_PLUS */
export type LineView = TextLine | { status: "locked" };
/** label = 등락률이 다루는 종가 날짜(#16). 등락률이 지연·미지원이어도 같은 날짜다 */
export type ChangeView = { text: string; tone: "up" | "down" | "flat" | "delayed" | "unsupported"; label: string };
export type CardView = {
  ticker: string;
  name: string;
  change: ChangeView;
  lines: LineView[]; // 항상 3개(첫 번째·두 번째·세 번째 줄)
  leverageTag: string | null;
  checked: string | null; // "Checked 7:30 AM ET · SEC filings"
};
export type DashboardView = { tradingDay: string | null; cards: CardView[] };

export type Stock = { ticker: string; name: string };
/** 로그인한 대시보드(#38). 위 내 종목, 아래 둘러보기, 고르기 목록 */
export type MyDashboardView = {
  mine: (Stock & { card: CardView | null })[]; // 잠기지 않은 내 종목, 넣은 순서. card null = 그날 카드 없음
  browse: CardView[]; // 나머지 카드(잠긴 내 종목 포함)
  pickable: Stock[]; // 커버 범위 중 내 종목(잠긴 것 포함)이 아닌 것
  swapsLeft: number | null; // null = Plus(그리지 않음)
  notice: string | null; // /cards?my_stock=… 결과 문구
};

/** 넣기·빼기 규칙은 DB가 지킨다(ADR-0004). 여기서는 나누고 결과 코드를 고정 문구로 바꿀 뿐이다 */
export function myDashboardView(
  cards: CardView[],
  coverage: Stock[],
  my: { stocks: (Stock & { locked: boolean })[]; swapsLeft: number | null },
  result: unknown,
): MyDashboardView {
  const mine = my.stocks.filter((s) => !s.locked).map(({ ticker, name }) => ({ ticker, name, card: cards.find((c) => c.ticker === ticker) ?? null }));
  const held = new Set(my.stocks.map((s) => s.ticker));
  return {
    mine,
    browse: cards.filter((c) => !mine.some((m) => m.ticker === c.ticker)),
    pickable: coverage.filter((c) => !held.has(c.ticker)),
    swapsLeft: my.swapsLeft,
    // 쿼리 값은 그리지 않는다: 문구표에 있는 코드만(Object.hasOwn: constructor 같은 프로토타입 이름 제외)
    notice: typeof result === "string" && Object.hasOwn(MY_STOCK_NOTICE, result) ? MY_STOCK_NOTICE[result as keyof typeof MY_STOCK_NOTICE] : null,
  };
}

/** DB 등락률(소수 첫째 자리)에 부호·%만 붙인다. 값은 계산함(checked_found)일 때만 있다(DB 제약).
 * previousTradingDay = DB previous_trading_day. 웹은 달력을 모른다: 값을 포맷만 하고, null(#16 전 카드)이면 prev close */
export function changeView(pct: number | null, status: LineStatus, previousTradingDay: string | null): ChangeView {
  const label = previousTradingDay ? DAY_CLOSE(formatCloseDay(previousTradingDay)) : PREV_CLOSE;
  if (status === "unsupported") return { text: NOT_COVERED, tone: "unsupported", label };
  if (status !== "checked_found" || pct === null) return { text: UPDATE_DELAYED, tone: "delayed", label };
  const abs = Math.abs(pct).toFixed(1);
  if (abs === "0.0") return { text: "0.0%", tone: "flat", label }; // -0도 보합
  return pct > 0 ? { text: `+${abs}%`, tone: "up", label } : { text: `−${abs}%`, tone: "down", label };
}

/** 없는 줄(아직 안 만듦, 축소판의 첫 번째 줄)도 숨기지 않고 지연으로 그린다. */
export function lineView(line: TextLine | null): TextLine {
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

const CLOSE_DAY = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short" }); // DAY와 같은 이유로 UTC

/** "2026-10-15" → "Thu 10/15"(두 번째 줄 날짜와 같은 형식). 월·일은 문자열에서 바로 읽어 앞 0만 뗀다 */
export function formatCloseDay(day: string): string {
  const [, m, d] = day.split("-").map(Number);
  return `${CLOSE_DAY.format(new Date(`${day}T00:00:00Z`))} ${m}/${d}`;
}

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
