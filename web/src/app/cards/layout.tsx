import Link from "next/link";

import { Brand } from "@/components/brand";

/** 카드 대시보드 머리: 브랜드(→ 랜딩)만. 랜딩의 메뉴는 아침마다 보는 화면에서 자리만 차지한다 */
export default function CardsLayout({ children }: LayoutProps<"/cards">) {
  return (
    <>
      <header className="border-b border-surface">
        <div className="mx-auto flex min-h-16 max-w-7xl items-center px-8">
          <Link href="/" className="flex min-h-12 items-center gap-3">
            <Brand />
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-8 py-12">{children}</main>
    </>
  );
}
