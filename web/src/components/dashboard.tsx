import type { DashboardView } from "@/lib/card-view";
import { NO_CARDS } from "@/lib/copy";

import { StockCard } from "./stock-card";

const GRID = "grid gap-4 md:grid-cols-2 xl:grid-cols-3";
const HEADING = "mb-8 text-h2 font-medium";

export function Dashboard({ data }: { data: DashboardView }) {
  return (
    <>
      <h1 className={HEADING}>{data.tradingDay ?? NO_CARDS}</h1>
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

/** 카드를 읽는 동안 자리를 잡아 둔다(레이아웃 밀림 방지). 제목 높이는 Dashboard의 h1 한 줄(36px × 1.2)과 같다 */
export function DashboardSkeleton() {
  return (
    <div aria-busy="true">
      <div className={`${HEADING} h-11 w-64 max-w-full bg-surface motion-safe:animate-pulse`} />
      <div className={GRID}>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-56 bg-surface motion-safe:animate-pulse" />
        ))}
      </div>
    </div>
  );
}
