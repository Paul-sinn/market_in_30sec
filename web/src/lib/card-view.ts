/** 화면 모델 타입과 표시 형식 순수 함수. 문장은 만들지 않는다: DB 문구 그대로 또는 copy.ts 고정 문구. */
import { CHECKED_PREFIX, DAY_CLOSE, MY_STOCK_NOTICE, NEW_FILINGS, NOT_COVERED, PREV_CLOSE, QUIET_DAY, UPDATE_DELAYED } from "./copy";

export type LineStatus = "checked_found" | "checked_none" | "delayed" | "unsupported"; // DB enum line_status
type TextLine = { text: string; status: LineStatus };
/** locked = 무료 범위의 세 번째 줄(#9): 글자 없이 상태만 온다. 화면은 copy.ts의 PRICE_FACTS_IN_PLUS */
export type LineView = TextLine | { status: "locked" };
/** label = 등락률이 다루는 종가 날짜(#16). 등락률이 지연·미지원이어도 같은 날짜다 */
export type ChangeView = { text: string; tone: "up" | "down" | "flat" | "delayed" | "unsupported"; label: string };
/** 카드 헤더(#63). status = 첫 번째 줄 상태(색에만 쓴다) */
export type CardHeaderView = { text: string; status: LineStatus };
export type CardView = {
  ticker: string;
  name: string;
  header: CardHeaderView | null; // 모든 viewer 같음. null = #63 전 확인함·있음 카드(건수 없음)
  change?: ChangeView; // 가격 표시 off면 키 자체가 없다(#56). 등락률·종가 날짜 라벨이 이 안에 있다
  lines: LineView[]; // on: 3개(세 번째 = 가격 사실 또는 잠금), off: 2개(첫 번째·두 번째 줄)
  leverageTag: string | null;
  checked: string | null; // "Checked 7:30 AM ET · SEC filings"
};
/** 시장 한눈에(#11). on: 3줄(어제 마감, 오늘 지표 일정, 시장 전체 소식), off: 2줄(어제 마감 없음, #56). 모든 플랜·로그인 전이 같다 */
export type GlanceView = { lines: TextLine[]; checked: string | null };
export type DashboardView = { tradingDay: string | null; glance: GlanceView | null; cards: CardView[] }; // glance null = 카드도 없음

export type Stock = { ticker: string; name: string };
/** 지난 카드(#68). days는 최신순이고 첫 칸이 오늘(card null = 그날 카드 없음). locked = 무료(오늘만, 더 지난 건 Plus). days [] = DB에 카드가 없음 */
export type PastCardsView = Stock & { days: { day: string; card: CardView | null }[]; locked: boolean };
/** 로그인한 대시보드(#38). 위 내 종목, 아래 둘러보기, 고르기 목록 */
export type MyDashboardView = {
  mine: (Stock & { card: CardView | null })[]; // 잠기지 않은 내 종목, 넣은 순서. card null = 그날 카드 없음
  browse: CardView[]; // 나머지 카드(잠긴 내 종목 포함)
  pickable: Stock[]; // 커버 범위 중 내 종목(잠긴 것 포함)이 아닌 것의 검색 결과(최대 SEARCH_MAX, #58). 검색어가 없으면 []
  query: string; // 정리한 검색어. 입력칸에 다시 채운다
  more: boolean; // 결과가 SEARCH_MAX에서 잘렸다
  swapsLeft: number | null; // null = Plus(그리지 않음)
  notice: string | null; // /cards?my_stock=… 결과 문구
};

/** 넣기·빼기 규칙은 DB가 지킨다(ADR-0004). 여기서는 나누고 결과 코드를 고정 문구로 바꿀 뿐이다 */
export function myDashboardView(
  cards: CardView[],
  coverage: Stock[],
  my: { stocks: (Stock & { locked: boolean })[]; swapsLeft: number | null },
  result: unknown,
  q?: unknown, // /cards?q=… 고르기 검색어(#58)
): MyDashboardView {
  const mine = my.stocks.filter((s) => !s.locked).map(({ ticker, name }) => ({ ticker, name, card: cards.find((c) => c.ticker === ticker) ?? null }));
  const held = new Set(my.stocks.map((s) => s.ticker));
  const query = cleanQuery(q);
  const { results, more } = searchStocks(coverage.filter((c) => !held.has(c.ticker)), query);
  return {
    mine,
    browse: cards.filter((c) => !mine.some((m) => m.ticker === c.ticker)),
    pickable: results,
    query,
    more,
    swapsLeft: my.swapsLeft,
    // 쿼리 값은 그리지 않는다: 문구표에 있는 코드만(Object.hasOwn: constructor 같은 프로토타입 이름 제외)
    notice: typeof result === "string" && Object.hasOwn(MY_STOCK_NOTICE, result) ? MY_STOCK_NOTICE[result as keyof typeof MY_STOCK_NOTICE] : null,
  };
}

export const SEARCH_MAX = 20; // 고르기 검색 결과 최대(#58). 넘으면 more
export const QUERY_MAX = 40; // 검색어 앞 글자 수

const cleanQuery = (q: unknown) => (typeof q === "string" ? q.trim().slice(0, QUERY_MAX) : "");
const nameKey = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); // "Coca-Cola" = "coca cola", "AT&T" = "at t"

/** 고르기 검색(#58 D10). stocks = 커버 범위에서 내 종목을 뺀 것(티커순). 순서: 티커 같음 → 티커로 시작 → 이름에 포함, 같은 묶음은 받은 순서.
 * 검색어는 여기서 글자로만 비교한다: SQL·PostgREST 필터에 넣지 않는다(주입·이스케이프 문제 없음) */
export function searchStocks(stocks: Stock[], q: unknown): { results: Stock[]; more: boolean } {
  const query = cleanQuery(q);
  if (!query) return { results: [], more: false };
  const ticker = query.toUpperCase().replaceAll(".", "-"); // BRK.B = BRK-B
  const name = nameKey(query); // 영숫자가 없는 검색어("%", "&")는 "": 이름으로는 아무것도 맞지 않는다
  const rank = (s: Stock) => (s.ticker === ticker ? 0 : s.ticker.startsWith(ticker) ? 1 : name && nameKey(s.name).includes(name) ? 2 : 3);
  const hits = stocks.map((s) => ({ s, r: rank(s) })).filter((h) => h.r < 3).sort((a, b) => a.r - b.r); // sort는 안정 정렬: 묶음 안은 티커순 그대로
  return { results: hits.slice(0, SEARCH_MAX).map((h) => h.s), more: hits.length > SEARCH_MAX };
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

/** 조용한 날(GLOSSARY QuietDay) = 첫 번째 줄 checked_none. 다른 줄과 무관. 카드 헤더(#63)·알아두기(#66)가 이 값만 쓴다 */
export const QUIET_DAY_STATUS = "checked_none" satisfies LineStatus;

/** 카드 헤더(#63). status = 첫 번째 줄 상태(null = 축소판 → 지연, lineView와 같다), filings = DB news_line_filing_count.
 * checked_found인데 건수가 없거나 1 미만이면(#63 전 카드) null: 건수를 지어내지 않는다 */
export function cardHeaderView(status: LineStatus | null, filings: number | null): CardHeaderView | null {
  if (status === QUIET_DAY_STATUS) return { text: QUIET_DAY, status };
  if (status === "unsupported") return { text: NOT_COVERED, status };
  if (status !== "checked_found") return { text: UPDATE_DELAYED, status: "delayed" };
  return filings !== null && filings >= 1 ? { text: NEW_FILINGS(filings), status } : null;
}

/** 없는 줄(아직 안 만듦, 축소판의 첫 번째 줄)도 숨기지 않고 지연으로 그린다. */
export function lineView(line: TextLine | null): TextLine {
  return line ?? { text: UPDATE_DELAYED, status: "delayed" };
}

/** 그날 행이 없으면(null: #11 전 날짜, 시장 한눈에 전에 끝난 실행) 지연 count줄, 하단 없음. 허용한 키만 옮긴다(펼치기 금지) */
export function glanceView(
  lines: { text: string; status: LineStatus; checked_at: string; source_scope: string | null }[] | null,
  count = 3,
): GlanceView {
  if (!lines) return { lines: Array.from({ length: count }, () => lineView(null)), checked: null };
  return { lines: lines.map((l) => ({ text: l.text, status: l.status })), checked: checkedFooter(lines) };
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
