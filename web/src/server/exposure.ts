import "server-only";

import { checkedFooter, lineView, type CardView } from "@/lib/card-view";

import type { StoredCard } from "./cards";
import type { Plan } from "./my-stocks";

/**
 * 줄 노출 판단은 여기 한 곳(#9, HANDOFF 3-2). 카드에는 세 줄이 다 저장돼 있고, 컴포넌트로 넘기기 전에 이 함수를 거친다.
 * 세 줄 전부 = Plus 유저의 잠기지 않은 내 종목 카드뿐. 나머지(로그인 전 viewer null, 무료 유저, 모든 플랜의 둘러보기)는 무료 범위:
 * 등락률·첫·두 번째 줄은 저장된 그대로, 세 번째 줄은 사실·지연과 관계없이 잠금 상태만(글자·상태·확인 시각·출처 없음).
 * 화면 모델은 허용한 키만 하나씩 옮긴다(펼치기 금지, tests/exposure.test.tsx 화이트리스트).
 */
export function exposeCards(cards: StoredCard[], viewer: { plan: Plan; stocks: { ticker: string; locked: boolean }[] } | null): CardView[] {
  const full = new Set(viewer?.plan === "plus" ? viewer.stocks.filter((s) => !s.locked).map((s) => s.ticker) : []);
  return cards.map((c) => {
    const open = full.has(c.ticker);
    const shown = open ? c.lines : c.lines.slice(0, 2);
    const lines = shown.map((l) => lineView(l && { text: l.text, status: l.status }));
    return {
      ticker: c.ticker,
      name: c.name,
      change: { text: c.change.text, tone: c.change.tone },
      lines: open ? lines : [...lines, { status: "locked" }],
      leverageTag: c.leverageTag,
      checked: checkedFooter(shown.filter((l) => l !== null)), // 잠긴 줄의 확인 시각·출처도 하단에 넣지 않는다
    };
  });
}
