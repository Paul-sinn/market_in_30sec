import { connection } from "next/server";
import { Suspense } from "react";

import { Dashboard, DashboardSkeleton } from "@/components/dashboard";
import { getDashboard } from "@/server/cards";

export default function CardsPage() {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <Cards />
    </Suspense>
  );
}

async function Cards() {
  await connection(); // 요청 때마다 DB를 읽는다. 빌드 때 읽지 않는다
  return <Dashboard data={await getDashboard()} />;
}
