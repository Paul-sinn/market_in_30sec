import "server-only";

import type { PastCardsView } from "@/lib/card-view";

import type { VerifiedUserId } from "./auth";
import { getCardHistory } from "./cards";
import { exposePastCards, pastCardDays } from "./exposure";
import { getMyStocks } from "./my-stocks";

/** 지난 카드 조회 입구(#68). 유저는 Auth에 확인한 id로만, 종목은 그 유저의 잠기지 않은 내 종목만.
 *  다른 유저의 종목·커버 범위 밖·형식이 깨진 티커·잠긴 종목은 모두 null(어느 경우인지 알려 주지 않는다).
 *  요청 티커는 내 종목 목록과 글자가 같을 때만 조회에 들어간다(신뢰 경계: 그 밖의 값은 DB에 닿지 않는다) */
export async function getPastCards(userId: VerifiedUserId, ticker: string): Promise<PastCardsView | null> {
  const my = await getMyStocks(userId);
  const stock = my.stocks.find((s) => !s.locked && s.ticker === ticker);
  if (!stock) return null;
  return exposePastCards(stock, await getCardHistory(stock.ticker, pastCardDays(my.plan)), my);
}
