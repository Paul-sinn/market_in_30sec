import Link from "next/link";

import { QUERY_MAX, type MyDashboardView } from "@/lib/card-view";
import { ADD, MORE_MATCHES, MY_STOCKS, NO_MATCHES, PAST_CARDS, PICK_STOCKS, REMOVE, SEARCH, SEARCH_STOCKS, SWAPS_LEFT } from "@/lib/copy";

import { PendingCard, StockCard } from "./stock-card";

// 일반 폼 POST(/my-stocks)라 JS 없이 돌고 브라우저에는 Supabase가 없다. 개수·교체 제한은 DB가 정하므로 버튼을 막지 않는다
const BUTTON =
  "inline-flex min-h-11 shrink-0 cursor-pointer items-center justify-center rounded-full bg-tint px-4 text-sm font-bold transition-colors hover:bg-accent-soft";

function ChangeForm({ change, ticker, label }: { change: "add" | "remove"; ticker: string; label: string }) {
  return (
    <form method="post" action="/my-stocks">
      <input type="hidden" name="change" value={change} />
      <input type="hidden" name="ticker" value={ticker} />
      <button type="submit" className={BUTTON}>
        {label}
        <span className="sr-only"> {ticker}</span>
      </button>
    </form>
  );
}

/** 대시보드 위 "My stocks": 남은 교체(무료만), 결과 문구, 내 종목 카드 + 빼기, 고르기 검색(내 종목 0개거나 검색어가 있으면 열림) */
export function MyStocksSection({ view, grid }: { view: MyDashboardView; grid: string }) {
  const note = !view.query ? null : view.pickable.length === 0 ? NO_MATCHES : view.more ? MORE_MATCHES : null;
  return (
    <section aria-labelledby="my-stocks" className="mb-12">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="my-stocks" className="text-2xl font-extrabold">
          {MY_STOCKS}
        </h2>
        {view.swapsLeft !== null && <p className="text-sm text-muted">{SWAPS_LEFT(view.swapsLeft)}</p>}
      </div>
      {view.notice && (
        <p role="status" className="mb-4 rounded-cell bg-surface px-4 py-3 text-sm shadow-card">
          {view.notice}
        </p>
      )}
      {view.mine.length > 0 && (
        <ul className={grid}>
          {view.mine.map((s) => (
            <li key={s.ticker} className="flex flex-col gap-2">
              <div className="grow">{s.card ? <StockCard card={s.card} /> : <PendingCard ticker={s.ticker} name={s.name} />}</div>
              <div className="flex flex-wrap justify-end gap-2">
                {/* 프리페치 없음: 프리페치도 /cards/… 요청 제한(#62)에 세어져 내 종목이 많으면 한도를 먹는다 */}
                <Link href={`/cards/${s.ticker}`} prefetch={false} className="inline-flex min-h-11 items-center rounded-full px-4 text-sm font-bold underline underline-offset-4 hover:bg-tint">
                  {PAST_CARDS}
                  <span className="sr-only"> {s.ticker}</span>
                </Link>
                <ChangeForm change="remove" ticker={s.ticker} label={REMOVE} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {/* id = 검색 폼 주소의 #pick: 검색 뒤 새 페이지가 이 칸으로 간다. 검색은 GET이라 JS 없이 돌고 서버가 거른다(#58) */}
      <details id="pick" open={view.mine.length === 0 || view.query !== ""} className="mt-4">
        <summary className="inline-flex min-h-11 cursor-pointer items-center rounded-full bg-accent px-5 font-bold">{PICK_STOCKS}</summary>
        <form method="get" action="/cards#pick" role="search" className="mt-4 mb-4">
          <label htmlFor="pick-q" className="mb-2 block text-sm text-muted">
            {SEARCH_STOCKS}
          </label>
          <div className="flex gap-2">
            {/* 자동 수정이 티커를 바꾸지 않게. 글자 16px(text-base): iOS가 확대하지 않는다 */}
            <input
              id="pick-q"
              type="search"
              name="q"
              defaultValue={view.query}
              maxLength={QUERY_MAX}
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="search"
              aria-describedby={note ? "pick-note" : undefined}
              className="min-h-11 min-w-0 grow rounded-full border border-muted bg-surface px-4 text-base"
            />
            <button type="submit" className={BUTTON}>
              {SEARCH}
            </button>
          </div>
        </form>
        {note && (
          <p id="pick-note" className="mb-4 text-sm text-muted">
            {note}
          </p>
        )}
        {view.pickable.length > 0 && (
          <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {view.pickable.map((s) => (
              <li key={s.ticker} className="flex items-center gap-3 rounded-cell bg-surface py-2 pr-2 pl-4 shadow-card">
                <span className="font-bold">{s.ticker}</span>
                <span className="min-w-0 grow wrap-break-word text-muted">{s.name}</span>
                <ChangeForm change="add" ticker={s.ticker} label={ADD} />
              </li>
            ))}
          </ul>
        )}
      </details>
    </section>
  );
}
