import type { CardView, DashboardView, MyDashboardView } from "@/lib/card-view";
import { BROWSE, NO_CARDS } from "@/lib/copy";

import { MarketGlance } from "./market-glance";
import { MyStocksSection } from "./my-stocks";
import { StockCard } from "./stock-card";

const GRID = "grid gap-4 md:grid-cols-2 xl:grid-cols-3";
const HEADING = "mb-8 text-h2 font-medium";

function Cards({ cards }: { cards: CardView[] }) {
  return (
    cards.length > 0 && (
      <ul className={GRID}>
        {cards.map((card) => (
          <li key={card.ticker}>
            <StockCard card={card} />
          </li>
        ))}
      </ul>
    )
  );
}

/** mine 없음 = 로그인 전(카드 전부). 있음 = 위 내 종목, 아래 둘러보기(#38) */
export function Dashboard({ data, mine }: { data: DashboardView; mine?: MyDashboardView }) {
  return (
    <>
      <h1 className={HEADING}>{data.tradingDay ?? NO_CARDS}</h1>
      {data.glance && <MarketGlance glance={data.glance} />}
      {mine ? (
        <>
          <MyStocksSection view={mine} grid={GRID} />
          {mine.browse.length > 0 && (
            <section aria-labelledby="browse">
              <h2 id="browse" className="mb-4 text-xl font-medium">
                {BROWSE}
              </h2>
              <Cards cards={mine.browse} />
            </section>
          )}
        </>
      ) : (
        <Cards cards={data.cards} />
      )}
    </>
  );
}

/** 카드를 읽는 동안 자리를 잡아 둔다(레이아웃 밀림 방지). 제목 높이는 Dashboard의 h1 한 줄(36px × 1.2)과 같다 */
export function DashboardSkeleton() {
  return (
    <div aria-busy="true">
      <div className={`${HEADING} h-11 w-64 max-w-full bg-surface motion-safe:animate-pulse`} />
      {/* 시장 한눈에: 제목 + 세 줄 + 하단이 한 줄씩일 때 높이(232px) */}
      <div className="mb-12 h-58 bg-surface motion-safe:animate-pulse" />
      <div className={GRID}>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-56 bg-surface motion-safe:animate-pulse" />
        ))}
      </div>
    </div>
  );
}
