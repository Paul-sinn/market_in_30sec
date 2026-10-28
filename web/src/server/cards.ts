import "server-only";

import { changeView, formatTradingDay, type ChangeView, type LineStatus, type Stock } from "@/lib/card-view";

import { db } from "./db";

// DB는 이 모듈에서만 읽는다(ADR-0003). select만 한다: 카드는 파이프라인만 쓴다
const LINES = ["news_line", "event_line", "price_fact_line"] as const;
const COLUMNS = [
  "ticker",
  "change_pct",
  "change_status",
  ...LINES.flatMap((l) => [`${l}_text`, `${l}_status`, `${l}_checked_at`, `${l}_source_scope`]),
  "leverage_tag",
  "coverage(name)",
].join(",");
const MAX_ROWS = 1000; // supabase/config.toml [api] max_rows. 넘으면 카드가 조용히 잘린다

type Line = (typeof LINES)[number];
type Row = {
  ticker: string;
  change_pct: number | null;
  change_status: LineStatus;
  leverage_tag: string | null;
  coverage: { name: string };
} & Record<`${Line}_status`, LineStatus | null> &
  Record<`${Line}_${"text" | "checked_at" | "source_scope"}`, string | null>;

/** 저장된 카드: 세 줄 전부, 줄마다 확인 시각·출처. 서버 안에서만 쓴다. 화면 모델(CardView)은 exposure.ts의 exposeCards만 만든다(#9) */
export type StoredLine = { text: string; status: LineStatus; checked_at: string; source_scope: string | null };
export type StoredCard = {
  ticker: string;
  name: string;
  change: ChangeView;
  lines: (StoredLine | null)[]; // 항상 3개. null = 그 줄이 없음(축소판의 첫 번째 줄 등)
  leverageTag: string | null;
};

/** 가장 최근 거래일의 카드 전부, 종목순. 카드가 없으면 tradingDay null. 줄 노출 판단 전이다(exposeCards) */
export async function getDashboard(): Promise<{ tradingDay: string | null; cards: StoredCard[] }> {
  const client = db();
  const latest = await client
    .from("stock_card")
    .select("trading_day")
    .order("trading_day", { ascending: false })
    .limit(1)
    .maybeSingle<{ trading_day: string }>();
  if (latest.error) throw new Error(`stock_card read failed: ${latest.error.message}`);
  if (!latest.data) return { tradingDay: null, cards: [] };

  const day = latest.data.trading_day;
  const { data, error } = await client
    .from("stock_card")
    .select(COLUMNS)
    .eq("trading_day", day)
    .order("ticker")
    .overrideTypes<Row[], { merge: false }>();
  if (error) throw new Error(`stock_card read failed: ${error.message}`);
  if (data.length >= MAX_ROWS) throw new Error(`stock_card has ${MAX_ROWS}+ rows for ${day}; paginate the read`);
  return { tradingDay: formatTradingDay(day), cards: data.map(toStoredCard) };
}

/** 커버 범위 전부, 종목순(내 종목 고르기 목록, #38) */
export async function getCoverage(): Promise<Stock[]> {
  const { data, error } = await db().from("coverage").select("ticker, name").order("ticker");
  if (error) throw new Error(`coverage read failed: ${error.message}`);
  return data;
}

function toStoredCard(r: Row): StoredCard {
  return {
    ticker: r.ticker,
    name: r.coverage.name,
    change: changeView(r.change_pct, r.change_status),
    lines: LINES.map((l) => {
      const status = r[`${l}_status`];
      // DB 제약(*_line_complete): 상태가 있으면 문구·확인 시각도 있다
      return status && { text: r[`${l}_text`]!, status, checked_at: r[`${l}_checked_at`]!, source_scope: r[`${l}_source_scope`] };
    }),
    leverageTag: r.leverage_tag,
  };
}
