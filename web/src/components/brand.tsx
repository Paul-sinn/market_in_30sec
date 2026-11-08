import { APP_NAME } from "@/lib/copy";

/** 둥근 피치 "30s" 로고 + 작업 이름(#93). 링크 여부는 부르는 쪽이 정한다 */
export function Brand() {
  return (
    <>
      <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent text-mark font-extrabold text-foreground">
        30s
      </span>
      <span className="font-extrabold">{APP_NAME}</span>
    </>
  );
}
