import type { GlanceView } from "@/lib/card-view";
import { MARKET_AT_A_GLANCE } from "@/lib/copy";

import { LINE_TONE } from "./stock-card";

/** 대시보드 맨 위 세 줄(#11): 어제 마감, 오늘 지표 일정, 시장 전체 소식. 카드와 같은 틀·줄 모양. 문구는 DB 그대로, 상태는 색에만 */
export function MarketGlance({ glance }: { glance: GlanceView }) {
  return (
    <section aria-labelledby="market-glance" className="mb-12 bg-surface p-6">
      <h2 id="market-glance" className="pb-2 text-label font-semibold tracking-widest uppercase">
        {MARKET_AT_A_GLANCE}
      </h2>
      <ul>
        {glance.lines.map((line, i) => (
          <li
            key={i}
            data-status={line.status}
            className={`border-t border-border py-3 wrap-break-word last:pb-0 ${LINE_TONE[line.status]}`}
          >
            {line.text}
          </li>
        ))}
      </ul>
      {glance.checked && <p className="pt-4 text-xs text-muted">{glance.checked}</p>}
    </section>
  );
}
