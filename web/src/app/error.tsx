"use client"; // 에러 경계는 클라이언트 컴포넌트여야 한다

import { LOAD_FAILED, TRY_AGAIN } from "@/lib/copy";

/** DB 읽기 실패 등 페이지 에러. error는 그리지 않는다(내용·키·URL이 화면에 나가지 않게). 하단 고지는 레이아웃에 남는다 */
export default function ErrorPage({ retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-2xl font-semibold">{LOAD_FAILED}</h1>
      <button
        type="button"
        onClick={() => retry()}
        className="min-h-11 cursor-pointer rounded-md border border-border bg-surface px-4 text-base font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground"
      >
        {TRY_AGAIN}
      </button>
    </div>
  );
}
