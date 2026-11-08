import Link from "next/link";

import type { CardView, ChangeView, LineView, TapSlot } from "@/lib/card-view";
import { LINE_LABELS, LOCKED_SLOT, QUIET_FACT, RELATED_IN_PLUS, SUMMARY_TOMORROW } from "@/lib/copy";

// 상태는 표시 방식에만 쓴다(색). 문구는 card.lines의 text 그대로. 모양은 #93(밝고 둥근 초보 친화)
const CHANGE_TONE: Record<ChangeView["tone"], string> = {
  up: "text-up text-lg font-bold",
  down: "text-down text-lg font-bold",
  flat: "text-foreground text-lg font-bold",
  delayed: "text-muted text-sm",
  unsupported: "text-muted text-sm",
};
export const LINE_TONE: Record<LineView["status"], string> = {
  checked_found: "text-foreground",
  checked_none: "text-muted",
  delayed: "text-muted",
  unsupported: "text-muted",
  locked: "text-muted", // 무료 범위의 세 번째 줄(#9·#67). 문구가 잠금·건수를 말한다
};
const CHIP = "rounded-full bg-tint px-2.5 py-0.5 text-xs font-bold text-muted";
/** 카드 안 칸(줄·카드 없음 자리): 크림 바탕 둥근 칸 */
const CELL = "rounded-cell bg-background px-4 py-3 wrap-break-word";

/** 잠긴 자리·세 번째 줄 잠금 누르기(#69): POST /waitlist가 그날 그 자리 합계를 1 올리고 /plus 설명으로 보낸다.
 *  일반 폼이라 JS 없이 돌고, 유저 값을 싣지 않는다(카드는 모든 viewer에게 같다). 터치 영역 44px, 누를 수 있다는 표시는 점선 알약(hover 없는 폰).
 *  sample = 랜딩 샘플 카드(#70): 같은 모양의 /plus 링크. 랜딩 방문이 탭 합계에 섞이지 않게 세지 않는다(프리페치도 없음: /plus 요청 제한) */
function TapForm({ slot, sample, children }: { slot: TapSlot; sample: boolean; children: React.ReactNode }) {
  const look =
    "flex min-h-11 w-full cursor-pointer items-center rounded-full border border-dashed border-muted px-4 py-2 text-left font-bold text-muted transition-colors hover:bg-tint hover:text-foreground";
  if (sample)
    return (
      <Link href="/plus" prefetch={false} className={look}>
        {children}
      </Link>
    );
  return (
    <form method="post" action="/waitlist">
      <input type="hidden" name="intent" value="tap" />
      <input type="hidden" name="slot" value={slot} />
      <button type="submit" className={look}>
        {children}
      </button>
    </form>
  );
}

/** 카드 머리: 회사 이름 먼저 크게(초보는 티커보다 이름을 안다), 그 아래 티커 칩·헤더 알약 */
function CardHead({ card }: { card: Pick<CardView, "ticker" | "name"> & Partial<CardView> }) {
  return (
    <header className="flex flex-col gap-2 pb-4">
      <h2 className="text-xl leading-heading font-extrabold wrap-break-word">{card.name}</h2>
      {/* 안 들어가면(긴 지연 문구) 등락률 묶음이 다음 줄로 내려간다 */}
      <div className="flex flex-wrap items-center gap-2">
        <p className={CHIP}>{card.ticker}</p>
        {card.leverageTag && <p className={CHIP}>{card.leverageTag}</p>}
        {/* 카드 헤더(#63): 고정 문구 그대로, 상태는 색에만(새 공시 = 강조 틴트, 그 밖 = 회색). null = #63 전 카드(건수 없음) */}
        {card.header && (
          <p
            data-header-status={card.header.status}
            className={`rounded-full px-3 py-0.5 text-sm font-bold whitespace-nowrap ${card.header.status === "checked_found" ? "bg-accent-soft" : "bg-tint"} ${LINE_TONE[card.header.status]}`}
          >
            {card.header.text}
          </p>
        )}
        {/* 가격 표시 off(#56)면 change 키가 없다 */}
        {card.change && (
          <p className="ml-auto flex items-baseline gap-2">
            <span data-tone={card.change.tone} className={`tabular-nums ${CHANGE_TONE[card.change.tone]}`}>
              {card.change.text}
            </span>
            <span className="text-xs whitespace-nowrap text-muted">{card.change.label}</span>
          </p>
        )}
      </div>
    </header>
  );
}

const ARTICLE = "flex h-full flex-col rounded-card bg-surface p-5 shadow-card sm:p-6";

export function StockCard({ card, sample = false }: { card: CardView; sample?: boolean }) {
  return (
    <article className={ARTICLE}>
      <CardHead card={card} />
      <ul className="flex flex-col gap-2">
        {card.lines.map((line, i) => (
          <li key={i} data-status={line.status} className={`${CELL} ${LINE_TONE[line.status]}`}>
            {/* 줄 라벨(#93): 웹 고정 문구. 줄 문구(DB)는 아래 그대로 */}
            <p data-line-label className="mb-1 text-xs font-bold text-muted">
              {LINE_LABELS[i]}
            </p>
            {line.status === "locked" ? (
              <TapForm slot="related_lock" sample={sample}>
                {RELATED_IN_PLUS(line.count)}
              </TapForm>
            ) : (
              line.text
            )}
            {/* 알아두기(#66): 조용한 날 첫 번째 줄 아래 보조 문장. 줄 수에 세지 않는다 */}
            {i === 0 && card.quietFact && (
              <p data-quiet-fact className="mt-2 text-sm text-muted">
                {QUIET_FACT(card.quietFact)}
              </p>
            )}
          </li>
        ))}
      </ul>
      {/* 잠긴 자리(#69): 줄 수에 세지 않는다. ETF·지난 카드에는 없다 */}
      {card.lockedSlot && (
        <div className="mt-3">
          <TapForm slot={card.lockedSlot} sample={sample}>
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
    <article className={ARTICLE}>
      <CardHead card={{ ticker, name }} />
      <p className={`${CELL} text-muted`}>{SUMMARY_TOMORROW}</p>
    </article>
  );
}
