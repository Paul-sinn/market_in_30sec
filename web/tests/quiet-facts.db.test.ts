/**
 * 알아두기 진도(#66): 웹 서버 카드 조회 입구 getMyQuietFacts(세션 유저 id, 대시보드 거래일) → exposeCards. 로컬 Supabase만, 원격 금지.
 * 테스트 전용 티커(ZZQ*)와 2098년 거래일만 쓰고 끝나면 지운다. 2098이라 cards.db.test(2099-12-31)가 같이 돌아도 대시보드 최신 거래일이 바뀌지 않는다.
 * 테스트 10-K 두 행은 고정 접수번호로 upsert do nothing(service_role에 delete 권한 없음, 의도된 스키마).
 * "다른 날 넣음"은 my_stock_history에 add 행을 직접 넣어 만든다(진도 = 마지막 add 행의 local_date부터). 이력은 유저 삭제 때 cascade로 지워진다.
 * 오늘 카드가 조용한 날인지는 함수가 보지 않는다: 그날 카드 상태로 만든 저장 카드를 exposeCards에 같이 넣어 화면 결과를 본다.
 */
import { afterAll, beforeAll, expect, test } from "vitest";

import type { LineStatus } from "@/lib/card-view";
import type { VerifiedUserId } from "@/server/auth";
import type { StoredCard } from "@/server/cards";
import { exposeCards } from "@/server/exposure";
import { addMyStock, ensureProfile, getMyQuietFacts, getMyStocks } from "@/server/my-stocks";

import { admin, createTestUser, deleteTestUsers } from "./local-supabase";

const [A, B, C, D, E] = ["ZZQA", "ZZQB", "ZZQC", "ZZQD", "ZZQE"]; // E = 풀 없음(ETF 자리)
const TICKERS = [A, B, C, D, E];
const [OLD_10K, NEW_10K] = ["0009999998-98-000066", "0009999998-98-000067"];
const AT = "2098-01-01T12:30:00+00:00";
const day = (n: number) => (n === 0 ? "2097-12-31" : `2098-01-${String(n).padStart(2, "0")}`); // day(1) = 넣은 날
const fact = (t: string, seq: number, pool = "") => `${t} ${pool}fact ${seq}`;
const pool = (ticker: string, size: number, accession = OLD_10K, name = "") =>
  Array.from({ length: size }, (_, i) => ({ ticker, seq: i + 1, text: fact(ticker, i + 1, name), source_accession: accession }));

type Kind = "quiet" | "found" | "delayed" | "unsupported" | "fallback" | "suspended";
const NEWS: Record<Exclude<Kind, "fallback" | "suspended">, [string, LineStatus, string | null]> = {
  quiet: ["No new SEC filings found", "checked_none", "SEC filings"],
  found: ["Test company named a new CFO (Company)", "checked_found", "SEC filings"],
  delayed: ["Update delayed", "delayed", "SEC filings"],
  unsupported: ["Not covered yet", "unsupported", null],
};

/** DB 행. 첫 번째 줄만 다르다(조용한 날 = checked_none) */
function row(ticker: string, trading_day: string, kind: Kind) {
  const news = kind === "fallback" ? null : NEWS[kind === "suspended" ? "quiet" : kind];
  return {
    ticker,
    trading_day,
    status: news ? "normal" : "fallback",
    publish_suspended: kind === "suspended",
    change_pct: null,
    change_status: "delayed",
    news_line_text: news?.[0] ?? null,
    news_line_status: news?.[1] ?? null,
    news_line_checked_at: news ? AT : null,
    news_line_source_scope: news?.[2] ?? null,
    news_line_filing_count: kind === "found" ? 1 : null,
    leverage_tag: null,
  };
}

/** 위 행과 같은 날의 저장 카드(exposeCards 입력). firstQuietFact = 공용 1번(getDashboard가 담는 값) */
function stored(ticker: string, kind: Kind, firstQuietFact: string | null): StoredCard {
  const news = kind === "fallback" ? null : NEWS[kind === "suspended" ? "quiet" : kind];
  return {
    ticker,
    name: `Web Test ${ticker}`,
    change: { text: "Update delayed", tone: "delayed", label: "prev close" },
    lines: [news && { text: news[0], status: news[1], checked_at: AT, source_scope: news[2] }, null, null],
    leverageTag: null,
    suspended: kind === "suspended",
    newsFilingCount: kind === "found" ? 1 : null,
    relatedFilingCount: null, // 세 번째 줄(#67)은 이 테스트 밖
    firstQuietFact,
    lockedSlot: null, // 잠긴 자리(#69)는 이 테스트 밖(cards.db.test)
  };
}

// ZZQA: 넣기 전 조용한 날(0), 1 조용 · 2 공시 · 3 조용 · 4 지연 · 5 미지원 · 6 축소판 · 7 발행 중단(조용) · 8 조용
const A_DAYS: Kind[] = ["quiet", "quiet", "found", "quiet", "delayed", "unsupported", "fallback", "suspended", "quiet"];
// ZZQB(풀 15)·ZZQC(풀 3)·ZZQE(풀 없음): 1~16 전부 조용. ZZQD(풀 교체용, 처음 풀 5): 1~4 조용
const cards = [
  ...A_DAYS.map((k, n) => row(A, day(n), k)),
  ...[B, C, E].flatMap((t) => Array.from({ length: 16 }, (_, i) => row(t, day(i + 1), "quiet"))),
  ...[1, 2, 3, 4].map((n) => row(D, day(n), "quiet")),
];
const kindOf = (ticker: string, n: number): Kind => (ticker === A ? A_DAYS[n] : "quiet");
const firstOf = (ticker: string) => (ticker === E ? null : fact(ticker, 1));

async function cleanup() {
  for (const table of ["quiet_fact", "stock_card", "coverage"] as const) {
    const { error } = await admin.from(table).delete().in("ticker", TICKERS); // quiet_fact·stock_card가 커버 범위 FK라 먼저
    if (error) throw new Error(`${table} cleanup failed: ${error.code}`);
  }
}

beforeAll(async () => {
  await cleanup();
  const steps = [
    () => admin.from("coverage").insert(TICKERS.map((t) => ({ ticker: t, name: `Web Test ${t}` }))),
    () =>
      admin.from("sec_annual_report").upsert(
        [OLD_10K, NEW_10K].map((accession) => ({ accession, cik: "0009999998", accepted_at: AT, body: "Item 1. Business" })),
        { onConflict: "accession", ignoreDuplicates: true },
      ),
    () => admin.from("stock_card").insert(cards),
    () => admin.from("quiet_fact").insert([...pool(A, 15), ...pool(B, 15), ...pool(C, 3), ...pool(D, 5)]),
  ];
  for (const step of steps) {
    const { error } = await step();
    if (error) throw new Error(`seed failed: ${error.code} ${error.message}`);
  }
});

const created: string[] = [];
afterAll(async () => {
  await deleteTestUsers(created); // 내 종목·이력이 먼저 지워져야 커버 범위 행을 지울 수 있다(FK)
  await cleanup();
});

/** 프로필 + 내 종목(트리거 이력은 오늘 날짜) + 넣은 날을 2098로 옮기는 add 행(id가 더 크다 = 마지막으로 넣은 날) */
async function user(plan: "free" | "plus", tickers: string[], addedOn = day(1)) {
  const id = (await createTestUser()).id as VerifiedUserId; // 테스트에서만: 운영에서는 getVerifiedUserId만 만든다
  created.push(id);
  await ensureProfile(id, "America/New_York");
  if (plan === "plus") await setPlan(id, "plus");
  for (const t of tickers) {
    expect(await addMyStock(id, t)).toBe("ok");
    await addedAt(id, t, addedOn);
  }
  return id;
}
async function setPlan(id: string, plan: "free" | "plus") {
  const { error } = await admin.from("user_profile").update({ plan }).eq("user_id", id); // 결제 연결 없음: DB에서 수동 지정
  if (error) throw new Error(`plan update failed: ${error.code}`);
}
async function addedAt(id: string, ticker: string, local_date: string) {
  const { error } = await admin.from("my_stock_history").insert({ user_id: id, change: "add", ticker, local_date });
  if (error) throw new Error(`history insert failed: ${error.code}`);
}

/** /cards 페이지와 같은 순서로 n일째 그 종목 카드에 보이는 알아두기(없으면 undefined) */
async function seen(id: VerifiedUserId, ticker: string, n: number) {
  const [my, progress] = await Promise.all([getMyStocks(id), getMyQuietFacts(id, day(n))]);
  const [view] = exposeCards([stored(ticker, kindOf(ticker, n), firstOf(ticker))], my, progress);
  return view && view.quietFact;
}

test("넣은 날부터 그날까지 조용한 날 수 = 번호. 넣기 전·공시·지연·미지원·축소판·발행 중단 날은 세지 않고, 조용하지 않은 날엔 없다", async () => {
  const id = await user("free", [A]);
  expect(await seen(id, A, 1)).toBe(fact(A, 1)); // 넣기 전 조용한 날(0)은 안 센다
  expect([...(await getMyQuietFacts(id, day(2)))]).toEqual([[A, fact(A, 1)]]); // 함수는 2일째도 1번을 준다
  expect(await seen(id, A, 2)).toBeUndefined(); // 그날 카드에 공시가 있어 화면엔 없다
  expect(await seen(id, A, 3)).toBe(fact(A, 2));
  for (const n of [4, 5, 6]) expect(await seen(id, A, n), day(n)).toBeUndefined(); // 지연·미지원·축소판
  expect((await getMyQuietFacts(id, day(7))).get(A)).toBe(fact(A, 2)); // 발행 중단 날은 세지 않는다
  expect(await seen(id, A, 7)).toBeUndefined(); // 발행 중단 카드는 아무에게도 안 나간다
  expect(await seen(id, A, 8)).toBe(fact(A, 3));
});

test("풀 끝: 조용한 날이 풀보다 많으면 없음, 1번으로 돌아가지 않는다(풀 15·16일째, 풀 3·4일째)", async () => {
  const id = await user("plus", [B, C]);
  expect(await seen(id, B, 15)).toBe(fact(B, 15));
  expect(await seen(id, B, 16)).toBeUndefined();
  expect(await seen(id, C, 3)).toBe(fact(C, 3));
  expect(await seen(id, C, 4)).toBeUndefined();
  expect([...(await getMyQuietFacts(id, day(16)))]).toEqual([]);
});

test("지웠다가 다시 넣으면(더 늦은 add 행) 다시 넣은 날부터 1번. 이미 내 종목을 또 넣으면 이력이 없어 그대로", async () => {
  const id = await user("free", [A]);
  expect(await seen(id, A, 8)).toBe(fact(A, 3));
  expect(await addMyStock(id, A)).toBe("ok"); // 이미 내 종목: DB가 건너뛴다(이력 없음)
  expect(await seen(id, A, 8)).toBe(fact(A, 3));
  await addedAt(id, A, day(3)); // 3일째에 다시 넣음
  expect(await seen(id, A, 3)).toBe(fact(A, 1));
  expect(await seen(id, A, 8)).toBe(fact(A, 2));
});

test("새 10-K로 풀이 바뀌면 보던 번호에서 이어서: 3번째 조용한 날에 교체 → 새 풀 3번, 다음 조용한 날 새 풀 4번", async () => {
  const id = await user("free", [D]);
  expect(await seen(id, D, 3)).toBe(fact(D, 3));
  // 분기 작업처럼 종목 행을 지우고 새 접수번호로 다시 넣는다
  const del = await admin.from("quiet_fact").delete().eq("ticker", D);
  const ins = await admin.from("quiet_fact").insert(pool(D, 5, NEW_10K, "new "));
  if (del.error || ins.error) throw new Error("pool replace failed");
  expect(await seen(id, D, 3)).toBe(fact(D, 3, "new "));
  expect(await seen(id, D, 4)).toBe(fact(D, 4, "new "));
});

test("다른 유저의 이력은 섞이지 않고, 남의 종목·잠긴 내 종목·로그인 전은 조용한 날마다 1번, 풀 없는 종목(ETF)은 없다", async () => {
  const early = await user("free", [A]); // 1일째 넣음
  const late = await user("free", [A, E], day(3)); // 3일째 넣음
  expect(await seen(early, A, 8)).toBe(fact(A, 3));
  expect(await seen(late, A, 8)).toBe(fact(A, 2));
  expect(await seen(late, E, 8)).toBeUndefined(); // 풀 없음: 진도에도 1번에도 없다
  expect((await getMyQuietFacts(late, day(8))).has(E)).toBe(false);

  // 남의 종목(둘러보기): 진도에 없고 화면은 1번
  const other = await user("free", [B]);
  expect((await getMyQuietFacts(other, day(8))).has(A)).toBe(false);
  expect(await seen(other, A, 8)).toBe(fact(A, 1));

  // Plus로 넷 넣고 무료가 되면 넷째(ZZQA)는 잠긴다: 진도에서 빠지고 화면은 1번
  const locked = await user("plus", [B, C, D, A]);
  await setPlan(locked, "free");
  expect((await getMyStocks(locked)).stocks.find((s) => s.ticker === A)?.locked).toBe(true);
  expect((await getMyQuietFacts(locked, day(8))).has(A)).toBe(false);
  expect(await seen(locked, A, 8)).toBe(fact(A, 1));

  // 로그인 전: 진도 없이 1번만
  expect(exposeCards([stored(A, "quiet", fact(A, 1))], null)[0].quietFact).toBe(fact(A, 1));
});
