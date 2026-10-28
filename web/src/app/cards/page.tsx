import { connection } from "next/server";
import { Suspense } from "react";

import { AuthControl } from "@/components/auth-control";
import { Dashboard, DashboardSkeleton } from "@/components/dashboard";
import { myDashboardView } from "@/lib/card-view";
import { getVerifiedUserId } from "@/server/auth";
import { getCoverage, getDashboard } from "@/server/cards";
import { exposeCards } from "@/server/exposure";
import { getMyStocks } from "@/server/my-stocks";

export default function CardsPage({ searchParams }: PageProps<"/cards">) {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <Cards searchParams={searchParams} />
    </Suspense>
  );
}

async function Cards({ searchParams }: Pick<PageProps<"/cards">, "searchParams">) {
  await connection(); // 요청 때마다 DB·세션을 읽는다. 빌드 때 읽지 않는다
  const [stored, userId, query] = await Promise.all([getDashboard(), getVerifiedUserId(), searchParams]);
  // 내 종목·플랜은 Auth에 확인한 유저 id로만 읽는다(#38, #9)
  const mine = userId && (await Promise.all([getCoverage(), getMyStocks(userId)]));
  // 줄 노출 판단(#9)은 컴포넌트로 넘기기 전에. 아래로는 exposeCards가 만든 화면 모델만 내려간다(잠긴 줄은 props·HTML에 없다)
  const data = { tradingDay: stored.tradingDay, cards: exposeCards(stored.cards, mine ? mine[1] : null) };
  return (
    <>
      <AuthControl signedIn={userId !== null} failed={query.sign_in === "failed"} />
      <Dashboard data={data} mine={mine ? myDashboardView(data.cards, mine[0], mine[1], query.my_stock) : undefined} />
    </>
  );
}
