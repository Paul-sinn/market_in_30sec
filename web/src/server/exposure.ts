import "server-only";

import { cardHeaderView, checkedFooter, formatTradingDay, lineView, QUIET_DAY_STATUS, type CardView, type PastCardsView, type Stock } from "@/lib/card-view";

import type { CardHistory, StoredCard } from "./cards";
import type { Plan } from "./my-stocks";
import { priceDisplayOn } from "./price-display";

/**
 * 줄 노출 판단은 여기 한 곳(#9, HANDOFF 3-2). 카드에는 세 줄이 다 저장돼 있고, 컴포넌트로 넘기기 전에 이 함수를 거친다.
 * 세 줄 전부 = Plus 유저의 잠기지 않은 내 종목 카드뿐. 나머지(로그인 전 viewer null, 무료 유저, 모든 플랜의 둘러보기)는 무료 범위:
 * 등락률·첫·두 번째 줄은 저장된 그대로, 세 번째 줄은 사실·지연과 관계없이 잠금 상태만(글자·상태·확인 시각·출처 없음).
 * 발행 중단 카드(#16)는 어느 viewer에게도 내보내지 않는다. 내 종목이면 그 자리는 카드 없음과 같다(myDashboardView).
 * 가격 표시 플래그 off(#56)면 모든 viewer에게 change 키 없음, 두 줄(세 번째 줄 = 가격 사실은 원문도 잠금도 없다).
 * 카드 헤더(#63)는 모든 viewer·플래그에 같다: 첫 번째 줄은 늘 무료 범위라 새로 열리는 정보가 없다.
 * 알아두기(#66)는 조용한 날(첫 번째 줄 checked_none)에만: 잠기지 않은 내 종목은 myQuietFacts(그 유저 진도, 없으면 없음 — 1번으로 돌아가지 않는다),
 * 그 밖(로그인 전, 모든 플랜의 둘러보기, 잠긴 내 종목)은 공용 1번. 무료·Plus 같고 가격 플래그와 무관. 줄(lines)에 넣지 않는 보조 문장이다.
 * 잠긴 자리(#69)는 읽기(getDashboard)가 고른 공용 카드 속성: 모든 viewer·플래그에 같다(Plus도 기능이 아직 없어 잠김). ETF·지난 카드는 키 없음.
 * 화면 모델은 허용한 키만 하나씩 옮긴다(펼치기 금지, tests/exposure.test.tsx 화이트리스트).
 */
type Viewer = { plan: Plan; stocks: { ticker: string; locked: boolean }[] };

export function exposeCards(
  cards: StoredCard[],
  viewer: Viewer | null,
  myQuietFacts: ReadonlyMap<string, string> = new Map(), // getMyQuietFacts 결과. 로그인 전·지난 카드는 빈 값
): CardView[] {
  const own = new Set((viewer?.stocks ?? []).filter((s) => !s.locked).map((s) => s.ticker));
  const plus = viewer?.plan === "plus";
  const prices = priceDisplayOn();
  return cards.filter((c) => !c.suspended).map((c) => {
    const open = plus && own.has(c.ticker);
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
    if (c.lines[0]?.status === QUIET_DAY_STATUS) {
      const fact = own.has(c.ticker) ? myQuietFacts.get(c.ticker) : c.firstQuietFact;
      if (fact) view.quietFact = fact; // 없으면 키 자체를 만들지 않는다
    }
    if (c.lockedSlot) view.lockedSlot = c.lockedSlot; // null(ETF·지난 카드)이면 키 자체를 만들지 않는다
    return view;
  });
}

/** 지난 카드 범위(#68, HANDOFF 3-8): Plus 최근 90일, 무료 오늘만. 오늘(카드가 있는 최신 거래일) 포함 달력일. 읽기(getCardHistory)가 이 값만큼만 읽는다 */
export const pastCardDays = (plan: Plan) => (plan === "plus" ? 90 : 1);

/**
 * 지난 카드 화면 모델(#68). stock = 그 유저의 잠기지 않은 내 종목(past-cards.ts가 확인), history = 최신순 카드.
 * 카드마다 exposeCards를 그대로 거친다: 가격 표시 플래그, 세 번째 줄 플랜별, 발행 중단 제외, 허용한 키만.
 * 첫 칸은 늘 오늘(카드가 없거나 발행 중단이면 card null = 카드 없음 자리). 그 앞날은 내보낼 카드가 있는 날만.
 * 무료는 받은 카드가 더 있어도 오늘만 + locked. 알아두기는 지난 카드에 없다(#66이 붙어도 여기서는 유저 진도를 넘기지 않는다, 키 화이트리스트는 tests/exposure.test.tsx)
 */
export function exposePastCards(stock: Stock, { today, cards }: CardHistory, viewer: Viewer): PastCardsView {
  const plus = viewer.plan === "plus";
  const view = (card?: StoredCard) => (card && exposeCards([card], viewer)[0]) ?? null;
  const earlier = plus ? cards.filter((c) => c.day !== today).map((c) => ({ day: c.day, card: view(c.card) })).filter((d) => d.card) : [];
  const days = today === null ? [] : [{ day: today, card: view(cards.find((c) => c.day === today)?.card) }, ...earlier];
  return { ticker: stock.ticker, name: stock.name, days: days.map((d) => ({ day: formatTradingDay(d.day), card: d.card })), locked: !plus };
}
