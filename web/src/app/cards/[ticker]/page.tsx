import { redirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { PastCards } from "@/components/past-cards";
import { getVerifiedUserId } from "@/server/auth";
import { getPastCards } from "@/server/past-cards";

/** 지난 카드(#68). 공용 캐시를 쓰지 않는다: 내 종목 확인·플랜이 먼저라 요청마다 읽는다(요청 제한 #62는 /cards/… 그대로) */
export default function PastCardsPage({ params }: PageProps<"/cards/[ticker]">) {
  return (
    <Suspense fallback={<div aria-busy="true" className="h-56 rounded-card bg-surface motion-safe:animate-pulse" />}>
      <Past params={params} />
    </Suspense>
  );
}

async function Past({ params }: Pick<PageProps<"/cards/[ticker]">, "params">) {
  await connection(); // 요청 때마다 DB·세션을 읽는다. 빌드 때 읽지 않는다
  const [{ ticker }, userId] = await Promise.all([params, getVerifiedUserId()]);
  // 로그인 전·내 종목이 아닌 티커는 같은 곳으로(어느 경우인지 알려 주지 않는다). 스트리밍 중이라 브라우저 쪽 이동이 된다
  const view = userId && (await getPastCards(userId, ticker));
  if (!view) redirect("/cards");
  return <PastCards view={view} />;
}
