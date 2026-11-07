import "server-only";

import {
  changeView,
  formatTradingDay,
  glanceView,
  lockedSlotOf,
  type ChangeView,
  type GlanceView,
  type LineStatus,
  type LockedSlot,
  type Stock,
} from "@/lib/card-view";

import { db } from "./db";
import { priceDisplayOn } from "./price-display";

// DB는 이 모듈에서만 읽는다(ADR-0003). select만 한다: 카드는 파이프라인만 쓴다
// 세 번째 줄 = 연관 소식(#67). 가격 사실(price_fact_line)은 가격 표시 플래그와 무관하게 읽지 않는다(U1: on이면 파이프라인이 저장만 한다)
const LINES = ["news_line", "event_line", "related_line"] as const;
const lineColumns = (l: string) => [`${l}_text`, `${l}_status`, `${l}_checked_at`, `${l}_source_scope`];
const COLUMNS = [
  "ticker",
  "change_pct",
  "change_status",
  "previous_trading_day",
  "publish_suspended",
  ...LINES.flatMap(lineColumns),
  "news_line_filing_count", // 카드 헤더 N new filing(s)(#63). 웹은 문장의 +N more를 파싱하지 않는다
  "related_line_filing_count", // 무료 잠금 N related update(s) in Plus(#67). 같은 이유로 DB 값 그대로
  "leverage_tag",
  "coverage(name,holdings_ticker)", // holdings_ticker 있음 = ETF(잠긴 자리 없음, #69. backend _earnings_target과 같은 정의)
].join(",");
// 잠긴 자리(#69): 첫 번째 줄 1등 공시의 분류. 그 공시의 모든 종목 행이 오므로 카드 티커 행만 본다.
// 힌트 !news_line_accession 필수: hold_queue가 stock_card↔sec_filing 다른 경로를 만든다. 대시보드만 읽는다(지난 카드에는 잠긴 자리가 없다, U3)
const DASHBOARD_COLUMNS = `${COLUMNS},news_filing:sec_filing!news_line_accession(filing_classification(ticker,kind))`;
// 시장 한눈에(#11): 줄 컬럼 12개만(가격 표시 off면 어제 마감 빼고 8개, #56). market_news_hold_*(검수에 걸린 문장)는 select하지 않는다(화면·props·HTML에 닿지 않게)
const GLANCE_LINES = ["close_line", "indicator_line", "market_news_line"] as const;
const MAX_ROWS = 1000; // supabase/config.toml [api] max_rows. 넘으면 카드가 조용히 잘린다

type Line = (typeof LINES)[number];
type Row = {
  ticker: string;
  change_pct: number | null;
  change_status: LineStatus;
  previous_trading_day: string | null;
  publish_suspended: boolean;
  news_line_filing_count: number | null;
  related_line_filing_count: number | null;
  leverage_tag: string | null;
  coverage: { name: string; holdings_ticker: string | null };
} & Record<`${Line}_status`, LineStatus | null> &
  Record<`${Line}_${"text" | "checked_at" | "source_scope"}`, string | null>;

type GlanceLine = (typeof GLANCE_LINES)[number];
type GlanceRow = Record<`${GlanceLine}_${"text" | "checked_at"}`, string> &
  Record<`${GlanceLine}_status`, LineStatus> &
  Record<`${GlanceLine}_source_scope`, string | null>;

/** 저장된 카드: 세 줄 전부, 줄마다 확인 시각·출처. 서버 안에서만 쓴다. 화면 모델(CardView)은 exposure.ts의 exposeCards만 만든다(#9) */
export type StoredLine = { text: string; status: LineStatus; checked_at: string; source_scope: string | null };
export type StoredCard = {
  ticker: string;
  name: string;
  change: ChangeView;
  lines: (StoredLine | null)[]; // 항상 3개(첫 번째·두 번째·연관 소식). null = 그 줄이 없음(축소판의 첫 번째 줄, #67 전 카드의 세 번째 줄)
  leverageTag: string | null;
  suspended: boolean; // 발행 중단(#16). 읽기에서 거르지 않는다: 노출 판단은 exposeCards 한 곳
  newsFilingCount: number | null; // 첫 번째 줄이 다룬 공시 수(DB 값 그대로, #63). 헤더는 exposeCards가 만든다
  relatedFilingCount: number | null; // 세 번째 줄이 다룬 공시 수(DB 값 그대로, #67, 확인함·있음에만). 무료 잠금 건수는 exposeCards가 만든다
  firstQuietFact: string | null; // 알아두기 1번(#66, 둘러보기·로그인 전). 모든 viewer에게 같은 공용 데이터. 노출은 exposeCards
  lockedSlot: LockedSlot | null; // 잠긴 자리(#69). viewer와 무관한 카드 속성. null = ETF, 지난 카드(getCardHistory는 늘 null)
};
type DashboardRow = Row & { news_filing: { filing_classification: { ticker: string; kind: string | null }[] } | null };

/** 카드가 있는 가장 최근 거래일("2099-12-31") = 대시보드·지난 카드의 오늘. 카드가 없으면 null */
async function latestTradingDay(client: ReturnType<typeof db>): Promise<string | null> {
  const latest = await client
    .from("stock_card")
    .select("trading_day")
    .order("trading_day", { ascending: false })
    .limit(1)
    .maybeSingle<{ trading_day: string }>();
  if (latest.error) throw new Error(`stock_card read failed: ${latest.error.message}`);
  return latest.data?.trading_day ?? null;
}

/** 가장 최근 거래일의 카드 전부(종목순)와 같은 날 시장 한눈에. 카드가 없으면 tradingDay·day·glance null.
 * day = 원래 거래일("2099-12-31"): 알아두기 진도(getMyQuietFacts)의 기준. 컴포넌트로 넘기지 않는다.
 * 카드는 줄 노출 판단 전이다(exposeCards). 시장 한눈에는 모든 플랜·로그인 전에 같아서 여기서 화면 모델로 바꾼다 */
export async function getDashboard(): Promise<{ tradingDay: string | null; day: string | null; glance: GlanceView | null; cards: StoredCard[] }> {
  const client = db();
  const day = await latestTradingDay(client);
  if (!day) return { tradingDay: null, day: null, glance: null, cards: [] };

  // 가격 표시 off(#56): 어제 마감 열은 읽지도 않는다(DB에 옛 값이 있어도 서버 메모리에 올라오지 않는다). 카드의 가격 키는 exposeCards가 뺀다
  const glanceLines = priceDisplayOn() ? GLANCE_LINES : GLANCE_LINES.filter((l) => l !== "close_line");
  const [{ data, error }, glance, quiet, estimates] = await Promise.all([
    client.from("stock_card").select(DASHBOARD_COLUMNS).eq("trading_day", day).order("ticker").overrideTypes<DashboardRow[], { merge: false }>(),
    client.from("market_glance").select(glanceLines.flatMap(lineColumns).join(",")).eq("trading_day", day).maybeSingle<GlanceRow>(),
    // 알아두기 1번(#66)만: 모든 viewer에게 같아 이 공용 캐시 안에서 읽는다. 2번부터는 유저 진도라 캐시 밖(getMyQuietFacts)
    client.from("quiet_fact").select("ticker, text").eq("seq", 1).overrideTypes<{ ticker: string; text: string }[], { merge: false }>(),
    // 잠긴 자리(#69): 그날 거래일의 실적 추정일. 웹은 두 번째 줄 문장(D-N)을 파싱하지 않는다
    client.from("earnings_estimate").select("ticker, estimate_day").eq("trading_day", day).overrideTypes<{ ticker: string; estimate_day: string }[], { merge: false }>(),
  ]);
  if (error) throw new Error(`stock_card read failed: ${error.message}`);
  if (data.length >= MAX_ROWS) throw new Error(`stock_card has ${MAX_ROWS}+ rows for ${day}; paginate the read`);
  if (glance.error) throw new Error(`market_glance read failed: ${glance.error.message}`);
  if (quiet.error) throw new Error(`quiet_fact read failed: ${quiet.error.message}`);
  if (quiet.data.length >= MAX_ROWS) throw new Error(`quiet_fact has ${MAX_ROWS}+ rows for seq 1; paginate the read`);
  if (estimates.error) throw new Error(`earnings_estimate read failed: ${estimates.error.message}`);
  if (estimates.data.length >= MAX_ROWS) throw new Error(`earnings_estimate has ${MAX_ROWS}+ rows for ${day}; paginate the read`);
  const first = new Map(quiet.data.map((f) => [f.ticker, f.text]));
  const estimateDay = new Map(estimates.data.map((e) => [e.ticker, e.estimate_day]));
  const slot = (r: DashboardRow) =>
    lockedSlotOf(
      {
        etf: r.coverage.holdings_ticker !== null,
        topFilingEarnings: r.news_filing?.filing_classification.some((c) => c.ticker === r.ticker && c.kind === "earnings") ?? false,
        estimateDay: estimateDay.get(r.ticker) ?? null,
      },
      day,
    );
  const g = glance.data;
  return {
    tradingDay: formatTradingDay(day),
    day,
    // 행 없음(null) = 줄마다 지연(glanceView)
    glance: glanceView(
      g && glanceLines.map((l) => ({ text: g[`${l}_text`], status: g[`${l}_status`], checked_at: g[`${l}_checked_at`], source_scope: g[`${l}_source_scope`] })),
      glanceLines.length,
    ),
    cards: data.map((r) => toStoredCard(r, first.get(r.ticker) ?? null, slot(r))),
  };
}

/** 한 종목의 지난 카드(#68). today = 최신 거래일(카드가 없으면 null), day = 그 카드의 거래일("2099-12-30") */
export type CardHistory = { today: string | null; cards: { day: string; card: StoredCard }[] };

/** 한 종목의 최근 days일 카드, 최신순. days는 오늘(카드가 있는 최신 거래일) 포함 달력일이고 플랜별 값은 exposure.ts pastCardDays.
 * 이미 쌓인 카드를 읽기만 한다(새 저장 없음). ticker는 부르는 쪽(past-cards.ts)이 그 유저의 내 종목인지 확인한 값이다.
 * 달력일인 이유: 웹에는 휴장일 달력이 없고(#16, 파이프라인 몫), 종목은 활성일 때만 카드가 생겨 "카드 90장"은 90거래일이 아니다 */
export async function getCardHistory(ticker: string, days: number): Promise<CardHistory> {
  const client = db();
  const today = await latestTradingDay(client);
  if (!today) return { today: null, cards: [] };
  const from = new Date(`${today}T00:00:00Z`); // trading_day는 날짜만 있는 값: UTC 자정으로 읽고 날짜만 뺀다(formatTradingDay와 같다)
  from.setUTCDate(from.getUTCDate() - (days - 1));
  const { data, error } = await client
    .from("stock_card")
    .select(`trading_day,${COLUMNS}`)
    .eq("ticker", ticker)
    .gte("trading_day", from.toISOString().slice(0, 10))
    .order("trading_day", { ascending: false })
    .overrideTypes<(Row & { trading_day: string })[], { merge: false }>(); // 90일 = 최대 90행(MAX_ROWS 아래)
  if (error) throw new Error(`stock_card read failed: ${error.message}`);
  return { today, cards: data.map((r) => ({ day: r.trading_day, card: toStoredCard(r, null, null) })) }; // 알아두기(#66)·잠긴 자리(#69)는 지난 카드에 없다
}

/** 커버 범위 전부, 종목순(내 종목 고르기 검색의 후보, #38·#58). 검색어는 이 조회에 넣지 않는다(메모리에서 searchStocks) */
// shortcut: PostgREST 기본 최대 1000행, 커버 범위가 1000을 넘으면 range로 나눠 읽는다
export async function getCoverage(): Promise<Stock[]> {
  const { data, error } = await db().from("coverage").select("ticker, name").order("ticker");
  if (error) throw new Error(`coverage read failed: ${error.message}`);
  return data;
}

function toStoredCard(r: Row, firstQuietFact: string | null, lockedSlot: LockedSlot | null): StoredCard {
  return {
    ticker: r.ticker,
    name: r.coverage.name,
    change: changeView(r.change_pct, r.change_status, r.previous_trading_day),
    lines: LINES.map((l) => {
      const status = r[`${l}_status`];
      // DB 제약(*_line_complete): 상태가 있으면 문구·확인 시각도 있다
      return status && { text: r[`${l}_text`]!, status, checked_at: r[`${l}_checked_at`]!, source_scope: r[`${l}_source_scope`] };
    }),
    leverageTag: r.leverage_tag,
    suspended: r.publish_suspended,
    newsFilingCount: r.news_line_filing_count,
    relatedFilingCount: r.related_line_filing_count,
    firstQuietFact,
    lockedSlot,
  };
}
