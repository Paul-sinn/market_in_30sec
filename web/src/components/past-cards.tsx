import Link from "next/link";

import type { PastCardsView } from "@/lib/card-view";
import { MY_STOCKS, NO_CARDS, PAST_CARDS, PAST_CARDS_IN_PLUS } from "@/lib/copy";

import { PendingCard, StockCard } from "./stock-card";

/** 지난 카드(#68): 뒤로(내 종목), 종목 머리, 날짜마다 카드(최신순). 무료는 오늘 카드 아래 잠금 안내 글자뿐(결제 연결 없음) */
export function PastCards({ view }: { view: PastCardsView }) {
  return (
    <>
      <Link href="/cards#my-stocks" className="mb-6 inline-flex min-h-11 items-center text-sm font-bold tracking-widest uppercase">
        {MY_STOCKS}
      </Link>
      <p className="text-label font-semibold tracking-widest text-muted uppercase">{PAST_CARDS}</p>
      <h1 className="text-h2 font-medium">{view.ticker}</h1>
      <p className="mb-8 wrap-break-word text-muted">{view.name}</p>
      {view.days.length === 0 ? (
        <p>{NO_CARDS}</p>
      ) : (
        <ol className="grid gap-x-4 gap-y-8 md:grid-cols-2 xl:grid-cols-3">
          {view.days.map(({ day, card }) => (
            <li key={day} className="flex flex-col">
              <h2 className="mb-2 text-sm text-muted">{day}</h2>
              <div className="grow">{card ? <StockCard card={card} /> : <PendingCard ticker={view.ticker} name={view.name} />}</div>
            </li>
          ))}
        </ol>
      )}
      {view.locked && <p className="mt-8 border border-border p-6 text-muted">{PAST_CARDS_IN_PLUS}</p>}
    </>
  );
}
