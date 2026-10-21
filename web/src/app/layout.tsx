import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { SiteFooter } from "@/components/site-footer";
import { APP_NAME } from "@/lib/copy";

import "./globals.css";

// 빌드 때 받아 자체 제공한다(요청 때 Google에 가지 않는다)
const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });

export const metadata: Metadata = {
  title: APP_NAME,
  robots: { index: false, follow: false }, // 1단계는 비공개(Basic Auth 뒤)
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="flex min-h-dvh flex-col bg-background font-sans text-sm leading-normal text-foreground antialiased">
        <div className="flex flex-1 flex-col">{children}</div>
        <SiteFooter />
      </body>
    </html>
  );
}
