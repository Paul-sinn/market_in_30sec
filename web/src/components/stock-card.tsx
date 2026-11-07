import type { CardView, ChangeView, LineView, TapSlot } from "@/lib/card-view";
import { LOCKED_SLOT, QUIET_FACT, RELATED_IN_PLUS, SUMMARY_TOMORROW } from "@/lib/copy";

// 상태는 표시 방식에만 쓴다(색). 문구는 card.lines의 text 그대로. 모양은 사용자 시안의 샘플 카드(#27)
const CHANGE_TONE: Record<ChangeView["tone"], string> = {
  up: "text-up text-lg font-semibold",
  down: "text-down text-lg font-semibold",
  flat: "text-foreground text-lg font-semibold",
  delayed: "text-muted",
  unsupported: "text-muted",
};
export const LINE_TONE: Record<LineView["status"], string> = {
  checked_found: "text-foreground",
  checked_none: "text-muted",
  delayed: "text-muted",
  unsupported: "text-muted",
  locked: "text-muted", // 무료 범위의 세 번째 줄(#9·#67). 문구가 잠금·건수를 말한다
};

/** 잠긴 자리·세 번째 줄 잠금 누르기(#69): POST /waitlist가 그날 그 자리 합계를 1 올리고 /plus 설명으로 보낸다.
 *  일반 폼이라 JS 없이 돌고, 유저 값을 싣지 않는다(카드는 모든 viewer에게 같다). 터치 영역 44px, 누를 수 있다는 표시는 테두리·밑줄(hover 없는 폰) */
function TapForm({ slot, className, children }: { slot: TapSlot; className: string; children: React.ReactNode }) {
  return (
    <form method="post" action="/waitlist">
      <input type="hidden" name="intent" value="tap" />
      <input type="hidden" name="slot" value={slot} />
      <button type="submit" className={`flex min-h-11 w-full cursor-pointer items-center text-left hover:text-foreground ${className}`}>
        {children}
      </button>
    </form>
  );
}

export function StockCard({ card }: { card: CardView }) {
  return (
    <article className="flex h-full flex-col bg-surface p-6">
      {/* 한 줄에 안 들어가면(긴 종목명·지연 문구) 등락률 묶음이 다음 줄 오른쪽으로 내려간다 */}
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pb-2">
        <h2 className="text-lg font-bold">{card.ticker}</h2>
        <p className="min-w-0 grow wrap-break-word text-muted">{card.name}</p>
        {/* 카드 헤더(#63): 고정 문구 그대로, 상태는 색에만. null = #63 전 카드(건수 없음) */}
        {card.header && (
          <p data-header-status={card.header.status} className={`whitespace-nowrap ${LINE_TONE[card.header.status]}`}>
            {card.header.text}
          </p>
        )}
        {/* 가격 표시 off(#56)면 change 키가 없다 */}
        {card.change && (
          <p className="ml-auto flex items-baseline gap-3">
            <span data-tone={card.change.tone} className={`tabular-nums ${CHANGE_TONE[card.change.tone]}`}>
              {card.change.text}
            </span>
            <span className="text-xs whitespace-nowrap text-muted">{card.change.label}</span>
          </p>
        )}
      </header>
      {card.leverageTag && (
        <p className="mb-3 self-start rounded-full bg-background px-3 py-1 text-xs text-muted">{card.leverageTag}</p>
      )}
      <ul>
        {card.lines.map((line, i) => (
          <li
            key={i}
            data-status={line.status}
            // 잠긴 줄은 버튼(44px)이 줄 높이를 채운다
            className={`border-t border-border wrap-break-word ${line.status === "locked" ? "" : "py-3 last:pb-0"} ${LINE_TONE[line.status]}`}
          >
            {line.status === "locked" ? (
              <TapForm slot="related_lock" className="py-1 underline underline-offset-4">
                {RELATED_IN_PLUS(line.count)}
              </TapForm>
            ) : (
              line.text
            )}
            {/* 알아두기(#66): 조용한 날 첫 번째 줄 아래 보조 문장. 줄 수에 세지 않는다 */}
            {i === 0 && card.quietFact && (
              <p data-quiet-fact className="mt-1 text-sm text-muted">
                {QUIET_FACT(card.quietFact)}
              </p>
            )}
          </li>
        ))}
      </ul>
      {/* 잠긴 자리(#69): 줄 수에 세지 않는다. ETF·지난 카드에는 없다 */}
      {card.lockedSlot && (
        <div className="mt-4">
          <TapForm slot={card.lockedSlot} className="border border-muted px-4 py-2 text-muted">
            {LOCKED_SLOT[card.lockedSlot]}
          </TapForm>
        </div>
      )}
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
