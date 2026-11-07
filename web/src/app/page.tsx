/**
 * 랜딩(#27). 사용자 시안 design-system/user-mockup/landing.dc.html을 토큰으로 옮겼다. DB를 읽지 않는 정적 페이지.
 * 시안 문구는 규칙·사실과 어긋나는 곳만 고쳤다(목록: _workspace/issue-27/01_web-dev_report.md 5절, 04_web-dev_report.md).
 * 가격 숫자·가격 사실 설명은 뺐다(#62, 스토리 24: 가격 표시 off). 샘플은 피봇 카드 줄.
 * #70: 웹에 없는 것(요금·체험·결제, 아레나, Apple 로그인, 위젯·아침 알림)을 뺐다. Plus는 판매 전 + 계획 기능 + Notify me만(약관 service 절)
 */
import Link from "next/link";

import { Brand } from "@/components/brand";
import { StockCard } from "@/components/stock-card";
import type { CardView } from "@/lib/card-view";
import { ABOUT_PLUS, CHECKED_PREFIX, NEW_FILINGS, OPEN_CARDS, PLUS_PLANNED, QUIET_DAY } from "@/lib/copy";

const WRAP = "mx-auto max-w-7xl px-8";
const LABEL = "text-label font-semibold tracking-widest uppercase";
const NUM = "text-nav font-semibold tracking-wider text-dim";
const H2 = "text-h2 font-medium";
const PILL = `${LABEL} rounded-full px-3 py-1 whitespace-nowrap`;
const BUTTON = "inline-flex items-center justify-center text-center font-bold tracking-widest uppercase";
const CTA = `${BUTTON} min-h-12 px-8 text-sm`;
const NAV_LINK = "inline-flex min-h-12 items-center text-nav font-semibold tracking-wider uppercase hover:text-hover";

// 샘플 카드: 카드와 같은 컴포넌트·같은 규칙의 문구(card-copy-rules 검사기 통과). 가격 표시 off 카드처럼 change 키 없음(#62).
// 무료로 보이는 그대로(exposeCards): 세 번째 줄은 건수 잠금, 주식엔 잠긴 자리, 조용한 주식엔 알아두기 1번. 잠금은 sample이라 /plus 링크(#70).
// 하단은 실제 카드처럼 확인된 줄의 범위(잠긴 줄 제외, 전부 SEC filings)
const CHECKED = `${CHECKED_PREFIX} 7:30 AM ET · SEC filings`;
const AAPL_NEWS = "Apple named a new CFO +2 more (SEC filing)";
const SAMPLES = [
  {
    ticker: "AAPL",
    name: "Apple",
    header: { text: NEW_FILINGS(3), status: "checked_found" }, // 첫 번째 줄 1등 + 2 more
    lines: [
      { text: AAPL_NEWS, status: "checked_found" },
      { text: "Earnings Thu 10/15 after close (est.) (D-2)", status: "checked_found" },
      { status: "locked", count: 2 },
    ],
    leverageTag: null,
    checked: CHECKED,
    lockedSlot: "earnings_summary", // 추정 실적일까지 2일(7일 이내)
  },
  {
    ticker: "QQQ",
    name: "Nasdaq-100 ETF",
    header: { text: QUIET_DAY, status: "checked_none" }, // 조용한 날 = 첫 번째 줄 확인함·없음
    lines: [
      { text: "No new SEC filings found", status: "checked_none" }, // ETF 첫 번째 줄(상위 편입 종목 소식)은 #10 미정
      { text: "Not covered yet", status: "unsupported" }, // ETF: 실적 없음, 배당 출처 없음
      { text: "Not covered yet", status: "unsupported" }, // ETF는 연관 소식 없음
    ],
    leverageTag: null,
    checked: CHECKED,
  },
  {
    ticker: "KO",
    name: "Coca-Cola",
    header: { text: QUIET_DAY, status: "checked_none" },
    lines: [
      { text: "No new SEC filings found", status: "checked_none" },
      { text: "No confirmed events found", status: "checked_none" },
      { status: "locked" }, // 0건은 건수 없이
    ],
    leverageTag: null,
    checked: CHECKED,
    quietFact: "Coca-Cola makes beverage concentrates and syrups for bottling partners",
    lockedSlot: "big_holders",
  },
] satisfies CardView[];

const STATS = [
  ["30", "Seconds to read every stock"],
  ["3", "Lines per stock, one fact each"],
  ["0", "Settings required"],
  ["7:45", "AM ET — cards ready"],
] as const;

const CARD_LINES = [
  ["01", "What happened", "One fact from the company's SEC filings, in 15 words or fewer."],
  ["02", "What's next", "The next earnings date, estimated from past filings and marked (est.), with a countdown."],
  [
    "03",
    "Related updates",
    "Same-day filings from a competitor, customer, supplier or peer. The relationship and the fact — never what it means for your stock. Free cards don't show the filings themselves.",
  ],
] as const;

export default function Landing() {
  return (
    <>
      <header className="border-b border-surface">
        <nav aria-label="Main" className={`${WRAP} flex min-h-16 flex-wrap items-center justify-between gap-x-8 gap-y-2`}>
          <a href="#top" className="flex min-h-12 items-center gap-3">
            <Brand />
          </a>
          <div className="flex flex-wrap items-center gap-x-8">
            <a href="#card" className={NAV_LINK}>
              The card
            </a>
            <a href="#how" className={NAV_LINK}>
              How it works
            </a>
            <a href="#plus" className={NAV_LINK}>
              Plus
            </a>
          </div>
          {/* 시안 높이 40px → 터치 영역 44px */}
          <Link href="/cards" className={`${BUTTON} min-h-11 border border-foreground px-5 text-nav`}>
            {OPEN_CARDS}
          </Link>
        </nav>
      </header>

      <main>
        <section id="top" aria-label="Hero" className="overflow-hidden bg-linear-180/srgb from-graphite to-black to-64%">
          <div className={`${WRAP} flex flex-wrap items-end gap-16 pt-32 pb-24`}>
            <div className="flex min-w-0 grow-999 basis-130 flex-col gap-6">
              {/* 시안의 dim은 모바일에서 라벨 자리 그라데이션 대비 약 4.3:1이라 muted(약 5.0:1) */}
              <p className={`${LABEL} text-muted`}>Every trading day · ready by 7:45 AM ET</p>
              <h1 className="text-display font-medium">
                Your stocks,
                <br />
                in 30 seconds.
              </h1>
              <p className="max-w-130 text-lg text-dim">
                One card per stock each morning: what happened and what&apos;s next. Facts from SEC filings — no tips, no hype.
              </p>
              <div className="flex flex-wrap gap-4 pt-2">
                <Link href="/cards" className={`${CTA} bg-accent`}>
                  {OPEN_CARDS}
                </Link>
                <a href="#card" className={`${CTA} border border-foreground`}>
                  See a sample card
                </a>
              </div>
            </div>
          </div>
        </section>

        <section aria-label="At a glance" className="border-b border-surface">
          <div className={`${WRAP} flex flex-wrap py-16`}>
            {STATS.map(([value, label], i) => (
              <div
                key={label}
                className={`flex grow basis-60 flex-col gap-2 py-6 pr-8 ${i > 0 ? "border-l border-surface pl-8" : ""}`}
              >
                <p className={`text-stat font-bold ${i === 0 ? "text-accent" : ""}`}>{value}</p>
                <p className={`${LABEL} text-dim`}>{label}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="card" aria-label="The card" className="py-24">
          <div className={`${WRAP} flex flex-wrap gap-16`}>
            <div className="flex min-w-0 grow basis-105 flex-col gap-6">
              <p className={`${LABEL} text-dim`}>The card</p>
              <h2 className={H2}>Three lines. One fact each.</h2>
              <p className="max-w-120 text-base text-dim">
                Each card checks the latest SEC filings for one stock and says up top what it found: new filings or a quiet
                day. Never more than three lines. On a quiet day, it may add one background fact from the company&apos;s
                annual report.
              </p>
              <ol className="mt-2 flex flex-col border-b border-surface">
                {CARD_LINES.map(([num, title, body]) => (
                  <li key={num} className="flex gap-6 border-t border-surface py-6">
                    <span className={`w-12 shrink-0 ${NUM}`}>{num}</span>
                    <div className="flex flex-col gap-1">
                      <h3 className="flex items-center gap-3 text-base font-medium">
                        {title}
                        {num === "03" && <span className={`${PILL} bg-surface`}>Plus</span>}
                      </h3>
                      <p className="text-dim">{body}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
            <div className="flex min-w-0 grow basis-105 flex-col gap-4">
              {SAMPLES.map((card) => (
                <StockCard key={card.ticker} card={card} sample />
              ))}
              <p className="text-xs text-dim">Sample cards. Figures are illustrative.</p>
            </div>
          </div>
        </section>

        <section id="how" aria-label="How it works" className="border-t border-surface py-24">
          <div className={`${WRAP} flex flex-col gap-12`}>
            <div className="flex flex-col gap-4">
              <p className={`${LABEL} text-dim`}>How it works</p>
              <h2 className={H2}>Set up once. Read every morning.</h2>
            </div>
            <div className="flex flex-wrap gap-8">
              <Step
                num="01"
                title="See the latest cards right away"
                body="No account for the first look. Sign in with Google to pick your own stocks."
              >
                <div className="flex h-55 flex-col justify-center gap-3 bg-surface px-8 py-6">
                  <div className="flex items-baseline gap-3">
                    <span className="text-lg font-bold">AAPL</span>
                    <span className="flex-1 text-muted">Apple</span>
                  </div>
                  <div className="h-px bg-border" />
                  <p>{AAPL_NEWS}</p>
                </div>
              </Step>
              <Step num="02" title="Pick up to three stocks" body="From the S&P 500 and popular ETFs, with up to three swaps a day.">
                <div className="flex h-55 flex-wrap items-center justify-center gap-2 bg-surface p-6">
                  {["AAPL", "QQQ", "KO"].map((t) => (
                    <span key={t} className="border border-foreground px-5 py-3 text-base font-bold">
                      {t}
                    </span>
                  ))}
                  {/* 시안의 dim 글자는 surface 위 4.46:1이라 muted. 점선 테두리는 비텍스트 3:1 기준이라 dim 유지 */}
                  <span className="border border-dashed border-dim px-5 py-3 text-base font-bold text-muted">+</span>
                </div>
              </Step>
              <Step
                num="03"
                title="Come back each trading day"
                body="New cards are ready by 7:45 AM ET."
              >
                <div className="flex h-55 flex-col items-center justify-center gap-2 bg-surface">
                  <p className="text-price font-medium tabular-nums">7:45 AM</p>
                  <p className={`${LABEL} text-muted`}>ET · Every trading day</p>
                </div>
              </Step>
            </div>
          </div>
        </section>

        {/* 시안의 흰 요금 섹션 자리. 문장은 약관 service 절·방침 use 절·/plus 설명과 같은 말(가격·체험·결제 없음) */}
        <section id="plus" aria-label="Plus" className="bg-foreground text-background">
          <div className={`${WRAP} flex flex-col items-start gap-6 py-24`}>
            <p className={`${LABEL} text-ink-muted`}>Plus</p>
            <h2 className={H2}>Free to use. No payments.</h2>
            <p className="max-w-160 text-base">{PLUS_PLANNED}</p>
            <p className="max-w-160 text-base text-ink-muted">
              Sign in and tap Notify me on the About Plus page. We&apos;ll email your sign-in address once when Plus launches.
            </p>
            {/* 프리페치 없음: /plus 요청 제한(#62)을 쓰지 않게 */}
            <Link href="/plus" prefetch={false} className={`${CTA} mt-2 bg-background text-foreground focus-visible:outline-background`}>
              {ABOUT_PLUS}
            </Link>
          </div>
        </section>

        <section id="get" aria-label="Open the cards" className="border-b border-surface">
          <div className={`${WRAP} flex flex-col items-center gap-8 py-24 text-center`}>
            <h2 className={`max-w-190 ${H2}`}>The next cards are ready at 7:45 AM ET.</h2>
            <Link href="/cards" className={`${CTA} bg-accent`}>
              {OPEN_CARDS}
            </Link>
          </div>
        </section>
      </main>
    </>
  );
}

function Step({ num, title, body, children }: { num: string; title: string; body: string; children: React.ReactNode }) {
  return (
    <article className="flex min-w-0 grow basis-75 flex-col">
      {children}
      <div className="flex flex-col gap-2 pt-6">
        <p className={NUM}>{num}</p>
        <h3 className="text-lg leading-heading font-bold">{title}</h3>
        <p className="text-dim">{body}</p>
      </div>
    </article>
  );
}
