import Link from "next/link";

import { Brand } from "@/components/brand";

/** 이용약관·개인정보처리방침 머리(#62): cards/layout.tsx와 같은 브랜드(→ 랜딩). 하단 고지·링크는 루트 레이아웃이 그린다 */
export default function LegalLayout({ children }: { children: React.ReactNode }) {
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
