import { NOT_INVESTMENT_ADVICE } from "@/lib/copy";

import { Brand } from "./brand";

// 절대 경로만: 어느 경로에서 눌러도 같은 곳. Product는 랜딩 안 앵커. 연락·삭제는 법률 페이지의 절(#62, id 고정).
// 웹에 없는 기능(아침 알림·위젯·아레나·요금)은 칸을 두지 않는다(#70)
const COLUMNS = [
  ["Product", [["The card", "/#card"], ["How it works", "/#how"], ["Plus", "/#plus"]]],
  ["Support", [["Request a stock", "/terms#contact"], ["Contact", "/terms#contact"], ["Delete my account", "/privacy#delete"]]],
  ["Legal", [["Terms of service", "/terms"], ["Privacy", "/privacy"]]],
] as const;

export function SiteFooter() {
  return (
    <footer className="pt-16 pb-12 text-muted">
      <div className="mx-auto flex max-w-7xl flex-col gap-12 px-5 sm:px-8">
        <div className="flex flex-wrap gap-x-8 gap-y-12">
          <div className="flex grow-2 basis-65 flex-col gap-4">
            <div className="flex items-center gap-3 text-foreground">
              <Brand />
            </div>
            <p className="max-w-75 text-sm">A morning report on the stocks you follow, in 30 seconds.</p>
          </div>
          {COLUMNS.map(([title, links]) => (
            <div key={title} className="flex grow basis-40 flex-col text-sm">
              <h2 className="mb-1 font-extrabold text-foreground">{title}</h2>
              {links.map(([label, href]) => (
                // 시안은 줄 간격 12px지만 터치 영역 44px을 위해 링크마다 높이 44px
                <a key={label} href={href} className="flex min-h-11 items-center hover:text-foreground hover:underline">
                  {label}
                </a>
              ))}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap justify-between gap-4 border-t border-border pt-6 text-xs">
          <p className="max-w-190">
            {/* 가격 문장은 가격 표시가 꺼져 있어 뺐다(#62). 아레나 문장은 아레나가 웹에 없어 뺐다(#70). 다시 켜면 되살린다 */}
            For informational purposes only. {NOT_INVESTMENT_ADVICE}.
          </p>
        </div>
      </div>
    </footer>
  );
}
