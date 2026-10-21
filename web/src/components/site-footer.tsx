import { NOT_INVESTMENT_ADVICE } from "@/lib/copy";

import { Brand } from "./brand";

// 없는 페이지(약관 등)는 시안처럼 랜딩 안 앵커로. "/#…"라 /cards에서 눌러도 랜딩으로 간다
const COLUMNS = [
  ["Product", [["The card", "/#card"], ["Morning push", "/#how"], ["Lock screen widget", "/#how"], ["Pricing", "/#pricing"]]],
  ["AI Arena", [["How calls are graded", "/#arena"], ["The agents", "/#arena"], ["Records", "/#arena"]]],
  ["Support", [["Request a stock", "/#top"], ["Contact", "/#top"], ["Delete my account", "/#top"]]],
  ["Legal", [["Terms of service", "/#top"], ["Privacy", "/#top"]]],
] as const;

export function SiteFooter() {
  return (
    <footer className="pt-16 pb-12 text-dim">
      <div className="mx-auto flex max-w-7xl flex-col gap-12 px-8">
        <div className="flex flex-wrap gap-x-8 gap-y-12">
          <div className="flex grow-2 basis-65 flex-col gap-4">
            <div className="flex items-center gap-3 text-foreground">
              <Brand />
            </div>
            <p className="max-w-75 text-nav">A morning report on the stocks you follow, in 30 seconds.</p>
          </div>
          {COLUMNS.map(([title, links]) => (
            <div key={title} className="flex grow basis-40 flex-col text-nav">
              <h2 className="mb-1 text-label font-semibold tracking-widest text-foreground uppercase">{title}</h2>
              {links.map(([label, href]) => (
                // 시안은 줄 간격 12px지만 터치 영역 44px을 위해 링크마다 높이 44px
                <a key={label} href={href} className="flex min-h-11 items-center hover:text-hover">
                  {label}
                </a>
              ))}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap justify-between gap-4 border-t border-surface pt-6 text-xs">
          <p className="max-w-190">
            For informational purposes only. {NOT_INVESTMENT_ADVICE}. Arena trades are simulated with virtual money. Prices
            are daily closes; the S&amp;P 500 and Nasdaq are shown through SPY and QQQ.
          </p>
        </div>
      </div>
    </footer>
  );
}
