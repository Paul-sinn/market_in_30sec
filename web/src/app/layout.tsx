import type { Metadata } from "next";
import { Fira_Code, Fira_Sans } from "next/font/google";

import { SiteFooter } from "@/components/site-footer";
import { APP_NAME } from "@/lib/copy";

import "./globals.css";

const sans = Fira_Sans({ variable: "--font-fira-sans", subsets: ["latin"], weight: ["400", "500", "600"] });
const mono = Fira_Code({ variable: "--font-fira-code", subsets: ["latin"], weight: ["500", "600"] });

export const metadata: Metadata = {
  title: APP_NAME,
  robots: { index: false, follow: false }, // 1단계는 비공개 대시보드
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="flex min-h-dvh flex-col bg-background font-sans text-foreground antialiased">
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
