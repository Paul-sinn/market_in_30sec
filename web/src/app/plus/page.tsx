import { connection } from "next/server";
import { Suspense } from "react";

import { NotifyMe } from "@/components/notify-me";
import { getVerifiedUserId } from "@/server/auth";
import { isWaitlisted } from "@/server/waitlist";

/** 잠긴 자리·세 번째 줄 잠금 설명 + Notify me(#69). 등록 여부는 유저 값이라 공용 카드 캐시 밖에서 요청마다 읽는다(카드에는 유저 상태가 없다) */
export default function PlusPage({ searchParams }: PageProps<"/plus">) {
  return (
    <Suspense fallback={<div aria-busy="true" className="h-56 rounded-card bg-surface motion-safe:animate-pulse" />}>
      <Plus searchParams={searchParams} />
    </Suspense>
  );
}

async function Plus({ searchParams }: Pick<PageProps<"/plus">, "searchParams">) {
  await connection(); // 요청 때마다 세션·DB를 읽는다. 빌드 때 읽지 않는다
  const [userId, query] = await Promise.all([getVerifiedUserId(), searchParams]);
  // 읽기 실패는 미등록으로 그린다(버튼이 보이고, 다시 눌러도 처음 시각 그대로). 로그는 고정 이유 + 코드만
  const waitlisted =
    userId !== null &&
    (await isWaitlisted(userId).catch((e) => {
      console.warn(`waitlist: reason=read_failed code=${e instanceof Error && typeof e.cause === "string" ? e.cause : "unknown"}`);
      return false;
    }));
  return <NotifyMe view={{ signedIn: userId !== null, waitlisted, failed: query.notify === "failed" }} />;
}
