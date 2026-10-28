import type { CardView, ChangeView, LineStatus } from "@/lib/card-view";
import { PREV_CLOSE, SUMMARY_TOMORROW } from "@/lib/copy";

// 상태는 표시 방식에만 쓴다(색). 문구는 card.lines의 text 그대로. 모양은 사용자 시안의 샘플 카드(#27)
const CHANGE_TONE: Record<ChangeView["tone"], string> = {
  up: "text-up text-lg font-semibold",
  down: "text-down text-lg font-semibold",
  flat: "text-foreground text-lg font-semibold",
  delayed: "text-muted",
  unsupported: "text-muted",
};
const LINE_TONE: Record<LineStatus, string> = {
  checked_found: "text-foreground",
  checked_none: "text-muted",
  delayed: "text-muted",
  unsupported: "text-muted",
};

export function StockCard({ card }: { card: CardView }) {
  return (
    <article className="flex h-full flex-col bg-surface p-6">
      {/* 한 줄에 안 들어가면(긴 종목명·지연 문구) 등락률 묶음이 다음 줄 오른쪽으로 내려간다 */}
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pb-2">
        <h2 className="text-lg font-bold">{card.ticker}</h2>
        <p className="min-w-0 grow wrap-break-word text-muted">{card.name}</p>
        <p className="ml-auto flex items-baseline gap-3">
          <span data-tone={card.change.tone} className={`tabular-nums ${CHANGE_TONE[card.change.tone]}`}>
            {card.change.text}
          </span>
          <span className="text-xs text-muted">{PREV_CLOSE}</span>
        </p>
      </header>
      {card.leverageTag && (
        <p className="mb-3 self-start rounded-full bg-background px-3 py-1 text-xs text-muted">{card.leverageTag}</p>
      )}
      <ul>
        {card.lines.map((line, i) => (
          <li
            key={i}
            data-status={line.status}
            className={`border-t border-border py-3 wrap-break-word last:pb-0 ${LINE_TONE[line.status]}`}
          >
            {line.text}
          </li>
        ))}
      </ul>
      {card.checked && <p className="mt-auto pt-4 text-xs text-muted">{card.checked}</p>}
    </article>
  );
}

/** 그날 카드가 없는 내 종목 자리(#38). StockCard와 같은 틀에 고정 문구 하나 */
export function PendingCard({ ticker, name }: { ticker: string; name: string }) {
  return (
    <article className="flex h-full flex-col bg-surface p-6">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pb-2">
        <h2 className="text-lg font-bold">{ticker}</h2>
        <p className="min-w-0 grow wrap-break-word text-muted">{name}</p>
      </header>
      <p className="border-t border-border pt-3 text-muted">{SUMMARY_TOMORROW}</p>
    </article>
  );
}
