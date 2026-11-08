import Link from "next/link";

import type { PastCardsView } from "@/lib/card-view";
import { MY_STOCKS, NO_CARDS, PAST_CARDS, PAST_CARDS_IN_PLUS } from "@/lib/copy";

import { PendingCard, StockCard } from "./stock-card";

/** 지난 카드(#68): 뒤로(내 종목), 종목 머리, 날짜마다 카드(최신순). 무료는 오늘 카드 아래 잠금 안내 글자뿐(결제 연결 없음) */
export function PastCards({ view }: { view: PastCardsView }) {
  return (
    <>
      <Link href="/cards#my-stocks" className="mb-6 inline-flex min-h-11 items-center text-sm font-bold underline underline-offset-4">
        {MY_STOCKS}
      </Link>
      <p className="text-sm font-bold text-muted">{PAST_CARDS}</p>
      {/* 회사 이름 먼저 크게, 티커는 칩(#93, 카드 머리와 같다) */}
      <h1 className="text-h2 font-extrabold wrap-break-word">{view.name}</h1>
      <p className="mt-2 mb-8 w-fit rounded-full bg-tint px-2.5 py-0.5 text-xs font-bold text-muted">{view.ticker}</p>
      {view.days.length === 0 ? (
        <p>{NO_CARDS}</p>
      ) : (
        <ol className="grid gap-x-4 gap-y-8 md:grid-cols-2 xl:grid-cols-3">
          {view.days.map(({ day, card }) => (
            <li key={day} className="flex flex-col">
              <h2 className="mb-2 text-sm font-bold text-muted">{day}</h2>
              <div className="grow">{card ? <StockCard card={card} /> : <PendingCard ticker={view.ticker} name={view.name} />}</div>
            </li>
          ))}
        </ol>
      )}
      {view.locked && <p className="mt-8 rounded-card border border-dashed border-muted p-6 font-bold text-muted">{PAST_CARDS_IN_PLUS}</p>}
    </>
  );
}
