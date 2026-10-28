import { connection } from "next/server";
import { Suspense } from "react";

import { AuthControl } from "@/components/auth-control";
import { Dashboard, DashboardSkeleton } from "@/components/dashboard";
import { getVerifiedUserId } from "@/server/auth";
import { getDashboard } from "@/server/cards";

export default function CardsPage({ searchParams }: PageProps<"/cards">) {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <Cards searchParams={searchParams} />
    </Suspense>
  );
}

async function Cards({ searchParams }: Pick<PageProps<"/cards">, "searchParams">) {
  await connection(); // 요청 때마다 DB·세션을 읽는다. 빌드 때 읽지 않는다
  const [data, userId, query] = await Promise.all([getDashboard(), getVerifiedUserId(), searchParams]);
  return (
    <>
      <AuthControl signedIn={userId !== null} failed={query.sign_in === "failed"} />
      <Dashboard data={data} />
    </>
  );
}
