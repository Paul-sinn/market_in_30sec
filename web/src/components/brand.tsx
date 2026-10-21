import { APP_NAME } from "@/lib/copy";

/** "30s" 빨간 사각 로고 + 작업 이름. 링크 여부는 부르는 쪽이 정한다 */
export function Brand() {
  return (
    <>
      <span aria-hidden="true" className="flex size-8 items-center justify-center bg-accent text-mark font-bold text-foreground">
        30s
      </span>
      <span className="text-nav font-semibold tracking-wider uppercase">{APP_NAME}</span>
    </>
  );
}
