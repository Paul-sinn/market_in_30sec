"use client"; // 에러 경계는 클라이언트 컴포넌트여야 한다

import { LOAD_FAILED, TRY_AGAIN } from "@/lib/copy";

/** DB 읽기 실패 등 /cards 에러. error는 그리지 않는다(내용·키·URL이 화면에 나가지 않게). 머리·하단 고지는 레이아웃에 남는다 */
export default function ErrorPage({ retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-6">
      <h1 className="text-h2 font-medium">{LOAD_FAILED}</h1>
      <button
        type="button"
        onClick={() => retry()}
        className="inline-flex min-h-12 cursor-pointer items-center border border-foreground px-8 text-sm font-bold tracking-widest uppercase"
      >
        {TRY_AGAIN}
      </button>
    </div>
  );
}
