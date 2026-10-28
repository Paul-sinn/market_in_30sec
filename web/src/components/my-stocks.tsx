import type { MyDashboardView } from "@/lib/card-view";
import { ADD, MY_STOCKS, PICK_STOCKS, REMOVE, SWAPS_LEFT } from "@/lib/copy";

import { PendingCard, StockCard } from "./stock-card";

// 일반 폼 POST(/my-stocks)라 JS 없이 돌고 브라우저에는 Supabase가 없다. 개수·교체 제한은 DB가 정하므로 버튼을 막지 않는다
const BUTTON =
  "inline-flex min-h-11 shrink-0 cursor-pointer items-center justify-center border border-foreground px-4 text-sm font-bold tracking-widest uppercase";

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

/** 대시보드 위 "My stocks": 남은 교체(무료만), 결과 문구, 내 종목 카드 + 빼기, 고르기 목록(0개면 열림) */
export function MyStocksSection({ view, grid }: { view: MyDashboardView; grid: string }) {
  return (
    <section aria-labelledby="my-stocks" className="mb-12">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="my-stocks" className="text-xl font-medium">
          {MY_STOCKS}
        </h2>
        {view.swapsLeft !== null && <p className="text-sm text-muted">{SWAPS_LEFT(view.swapsLeft)}</p>}
      </div>
      {view.notice && (
        <p role="status" className="mb-4 bg-surface px-4 py-3 text-sm">
          {view.notice}
        </p>
      )}
      {view.mine.length > 0 && (
        <ul className={grid}>
          {view.mine.map((s) => (
            <li key={s.ticker} className="flex flex-col gap-2">
              <div className="grow">{s.card ? <StockCard card={s.card} /> : <PendingCard ticker={s.ticker} name={s.name} />}</div>
              <div className="self-end">
                <ChangeForm change="remove" ticker={s.ticker} label={REMOVE} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {view.pickable.length > 0 && (
        <details open={view.mine.length === 0} className="mt-4">
          <summary className="min-h-11 cursor-pointer py-3 text-sm font-bold tracking-widest uppercase">{PICK_STOCKS}</summary>
          <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {view.pickable.map((s) => (
              <li key={s.ticker} className="flex items-center gap-3 bg-surface py-2 pr-2 pl-4">
                <span className="font-bold">{s.ticker}</span>
                <span className="min-w-0 grow wrap-break-word text-muted">{s.name}</span>
                <ChangeForm change="add" ticker={s.ticker} label={ADD} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
