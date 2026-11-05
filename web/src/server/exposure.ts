import "server-only";

import { cardHeaderView, checkedFooter, lineView, type CardView } from "@/lib/card-view";

import type { StoredCard } from "./cards";
import type { Plan } from "./my-stocks";
import { priceDisplayOn } from "./price-display";

/**
 * 줄 노출 판단은 여기 한 곳(#9, HANDOFF 3-2). 카드에는 세 줄이 다 저장돼 있고, 컴포넌트로 넘기기 전에 이 함수를 거친다.
 * 세 줄 전부 = Plus 유저의 잠기지 않은 내 종목 카드뿐. 나머지(로그인 전 viewer null, 무료 유저, 모든 플랜의 둘러보기)는 무료 범위:
 * 등락률·첫·두 번째 줄은 저장된 그대로, 세 번째 줄은 사실·지연과 관계없이 잠금 상태만(글자·상태·확인 시각·출처 없음).
 * 발행 중단 카드(#16)는 어느 viewer에게도 내보내지 않는다. 내 종목이면 그 자리는 카드 없음과 같다(myDashboardView).
 * 가격 표시 플래그 off(#56)면 모든 viewer에게 change 키 없음, 두 줄(세 번째 줄 = 가격 사실은 원문도 잠금도 없다).
 * 카드 헤더(#63)는 모든 viewer·플래그에 같다: 첫 번째 줄은 늘 무료 범위라 새로 열리는 정보가 없다.
 * 화면 모델은 허용한 키만 하나씩 옮긴다(펼치기 금지, tests/exposure.test.tsx 화이트리스트).
 */
export function exposeCards(cards: StoredCard[], viewer: { plan: Plan; stocks: { ticker: string; locked: boolean }[] } | null): CardView[] {
  const full = new Set(viewer?.plan === "plus" ? viewer.stocks.filter((s) => !s.locked).map((s) => s.ticker) : []);
  const prices = priceDisplayOn();
  return cards.filter((c) => !c.suspended).map((c) => {
    const open = full.has(c.ticker);
    const kept = prices ? c.lines : c.lines.slice(0, 2);
    const shown = open ? kept : kept.slice(0, 2);
    const lines = shown.map((l) => lineView(l && { text: l.text, status: l.status }));
    const view: CardView = {
      ticker: c.ticker,
      name: c.name,
      header: cardHeaderView(c.lines[0]?.status ?? null, c.newsFilingCount), // 새 객체: 허용한 키(text·status)만
      lines: open || !prices ? lines : [...lines, { status: "locked" }],
      leverageTag: c.leverageTag,
      checked: checkedFooter(shown.filter((l) => l !== null)), // 잠긴 줄·빠진 가격 줄의 확인 시각·출처도 하단에 넣지 않는다
    };
    // off면 키 자체를 만들지 않는다(undefined도 아니다): 등락률·종가 날짜 라벨이 이 안에 있다
    if (prices) view.change = { text: c.change.text, tone: c.change.tone, label: c.change.label };
    return view;
  });
}
