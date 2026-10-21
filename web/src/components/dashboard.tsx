import type { DashboardView } from "@/lib/card-view";
import { APP_NAME, NO_CARDS } from "@/lib/copy";

import { StockCard } from "./stock-card";

const GRID = "grid gap-4 md:grid-cols-2 xl:grid-cols-3";

export function Dashboard({ data }: { data: DashboardView }) {
  return (
    <>
      <header className="mb-6">
        <p className="font-mono text-sm text-muted">{APP_NAME}</p>
        <h1 className="text-2xl font-semibold">{data.tradingDay ?? NO_CARDS}</h1>
      </header>
      {data.cards.length > 0 && (
        <ul className={GRID}>
          {data.cards.map((card) => (
            <li key={card.ticker}>
              <StockCard card={card} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** 카드를 읽는 동안 자리를 잡아 둔다(레이아웃 밀림 방지). 머리 높이는 Dashboard와 같다 */
export function DashboardSkeleton() {
  return (
    <div aria-busy="true">
      <header className="mb-6">
        <p className="font-mono text-sm text-muted">{APP_NAME}</p>
        <div className="h-8 w-48 rounded-md bg-surface motion-safe:animate-pulse" />
      </header>
      <div className={GRID}>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-56 rounded-xl border border-border bg-surface motion-safe:animate-pulse" />
        ))}
      </div>
    </div>
  );
}
