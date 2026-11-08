import type { CardView, DashboardView, MyDashboardView } from "@/lib/card-view";
import { BROWSE, DASHBOARD_INTRO, NO_CARDS } from "@/lib/copy";

import { MarketGlance } from "./market-glance";
import { MyStocksSection } from "./my-stocks";
import { StockCard } from "./stock-card";

const GRID = "grid gap-4 md:grid-cols-2 xl:grid-cols-3";
const HEADING = "text-h2 font-extrabold";
const INTRO = "mt-2 mb-6 max-w-prose text-muted sm:mb-8";

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
      {/* 초보용 한 줄 설명(#93): SEC 공시가 뭔지 */}
      <p className={INTRO}>{DASHBOARD_INTRO}</p>
      {data.glance && <MarketGlance glance={data.glance} />}
      {mine ? (
        <>
          <MyStocksSection view={mine} grid={GRID} />
          {mine.browse.length > 0 && (
            <section aria-labelledby="browse">
              <h2 id="browse" className="mb-4 text-2xl font-extrabold">
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

/** 카드를 읽는 동안 자리를 잡아 둔다(레이아웃 밀림 방지). 제목 + 설명 높이는 Dashboard의 h1·설명과 비슷하게 */
export function DashboardSkeleton() {
  return (
    <div aria-busy="true">
      <div className="h-10 w-64 max-w-full rounded-cell bg-surface motion-safe:animate-pulse" />
      <div className={`${INTRO} h-12`} />
      {/* 시장 한눈에: 제목 + 두세 줄 + 하단 */}
      <div className="mb-10 h-58 rounded-card bg-surface motion-safe:animate-pulse" />
      <div className={GRID}>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-64 rounded-card bg-surface motion-safe:animate-pulse" />
        ))}
      </div>
    </div>
  );
}
