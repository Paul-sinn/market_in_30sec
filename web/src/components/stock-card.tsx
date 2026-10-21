import type { CardView, ChangeView, LineStatus } from "@/lib/card-view";
import { LAST_CLOSE } from "@/lib/copy";

// 상태는 표시 방식에만 쓴다(색·아이콘). 문구는 card.lines의 text 그대로
const CHANGE_TONE: Record<ChangeView["tone"], string> = {
  up: "text-up text-xl font-semibold",
  down: "text-down text-xl font-semibold",
  flat: "text-foreground text-xl font-semibold",
  delayed: "text-muted text-sm",
  unsupported: "text-muted text-sm",
};
const LINE_TONE: Record<LineStatus, string> = {
  checked_found: "text-foreground",
  checked_none: "text-muted",
  delayed: "text-muted",
  unsupported: "text-muted",
};
// 문구가 상태를 말하므로 아이콘은 장식(aria-hidden). 확인함·있음 ● / 확인함·없음 ○ / 지연 시계 / 미지원 −
const ICON: Record<LineStatus, React.ReactNode> = {
  checked_found: <circle cx="8" cy="8" r="3" fill="currentColor" />,
  checked_none: <circle cx="8" cy="8" r="3" />,
  delayed: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 5v3l2 1.5" />
    </>
  ),
  unsupported: <path d="M4.5 8h7" />,
};

export function StockCard({ card }: { card: CardView }) {
  return (
    <article className="flex h-full flex-col gap-3 rounded-xl border border-border bg-surface p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-mono text-lg font-semibold">{card.ticker}</h2>
          <p className="text-sm break-words text-muted">{card.name}</p>
        </div>
        <div className="shrink-0 text-right">
          <p data-tone={card.change.tone} className={`font-mono tabular-nums ${CHANGE_TONE[card.change.tone]}`}>
            {card.change.text}
          </p>
          <p className="text-sm text-muted">{LAST_CLOSE}</p>
        </div>
      </header>
      {card.leverageTag && (
        <p className="self-start rounded-md border border-border px-2 py-0.5 text-sm text-muted">{card.leverageTag}</p>
      )}
      <ul className="flex flex-col gap-2">
        {card.lines.map((line, i) => (
          <li key={i} data-status={line.status} className={`flex gap-2 ${LINE_TONE[line.status]}`}>
            <svg
              aria-hidden="true"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              className={`mt-1 size-4 shrink-0 ${line.status === "delayed" ? "text-warning" : ""}`}
            >
              {ICON[line.status]}
            </svg>
            <span className="min-w-0 break-words">{line.text}</span>
          </li>
        ))}
      </ul>
      {card.checked && <p className="mt-auto pt-1 text-sm text-muted">{card.checked}</p>}
    </article>
  );
}
