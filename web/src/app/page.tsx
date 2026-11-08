/**
 * 랜딩. 섹션 구조·문구는 #27 사용자 시안에서 왔고, 모양은 #93(밝고 둥근 초보 친화, 사용자 결정 2026-11-07)으로 바꿨다. DB를 읽지 않는 정적 페이지.
 * 시안 문구는 규칙·사실과 어긋나는 곳만 고쳤다(목록: _workspace/issue-27/01_web-dev_report.md 5절, 04_web-dev_report.md, issue-93/01_web-dev_report.md).
 * 가격 숫자·가격 사실 설명은 뺐다(#62, 스토리 24: 가격 표시 off). 샘플은 2026-11-06 실제 카드(#93, lib/samples.ts).
 * #70: 웹에 없는 것(요금·체험·결제, 아레나, Apple 로그인, 위젯·아침 알림)을 뺐다. Plus는 판매 전 + 계획 기능 + Notify me만(약관 service 절)
 */
import Link from "next/link";

import { Brand } from "@/components/brand";
import { StockCard } from "@/components/stock-card";
import { formatTradingDay } from "@/lib/card-view";
import { ABOUT_PLUS, OPEN_CARDS, PLUS_PLANNED, REAL_CARDS_FROM } from "@/lib/copy";
import { SAMPLE_DAY, SAMPLES } from "@/lib/samples";

const WRAP = "mx-auto w-full max-w-7xl px-5 sm:px-8";
const EYEBROW = "self-start rounded-full bg-surface px-3 py-1 text-sm font-bold text-accent-ink shadow-card";
const H2 = "text-h2 font-extrabold";
const BADGE = "flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-soft font-extrabold text-accent-ink";
const CHIP = "rounded-full bg-tint px-2.5 py-0.5 text-xs font-bold text-muted";
const PILL = "items-center justify-center rounded-full text-center font-bold transition hover:brightness-95";
const CTA = `inline-flex min-h-12 px-7 ${PILL}`;
const PRIMARY = `${CTA} bg-accent shadow-card`;
const NAV_LINK = "inline-flex min-h-12 items-center rounded-full px-3 font-bold hover:bg-tint";

// 첫 번째 줄 샘플(MSFT 실제 카드). How it works 01 미니 카드도 같은 줄
const [MSFT] = SAMPLES;
const MSFT_NEWS = MSFT.lines[0].text;

const STATS = [
  ["30", "Seconds to read every stock"],
  ["3", "Lines per stock, one fact each"],
  ["0", "Settings required"],
  ["7:45", "AM ET — cards ready"],
] as const;

const CARD_LINES = [
  ["1", "What happened", "One fact from the company's SEC filings, in 15 words or fewer."],
  ["2", "What's next", "The next earnings date, estimated from past filings and marked (est.), with a countdown."],
  [
    "3",
    "Related updates",
    "Same-day filings from a competitor, customer, supplier or peer. The relationship and the fact — never what it means for your stock. Free cards don't show the filings themselves.",
  ],
] as const;

export default function Landing() {
  return (
    <>
      <header>
        <nav aria-label="Main" className={`${WRAP} flex min-h-16 items-center justify-between gap-x-6 pt-2`}>
          <a href="#top" className="flex min-h-12 items-center gap-2">
            <Brand />
          </a>
          {/* 폰에서는 메뉴를 숨긴다(첫 화면 바로 아래 같은 버튼이 있고, 하단 Product에 같은 링크) */}
          <div className="hidden items-center gap-x-1 md:flex">
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
          <Link href="/cards" className={`hidden min-h-11 border border-muted bg-surface px-5 text-sm sm:inline-flex ${PILL}`}>
            {OPEN_CARDS}
          </Link>
        </nav>
      </header>

      <main>
        <section id="top" aria-label="Hero" className="bg-linear-to-b from-background via-accent-soft to-background">
          <div className={`${WRAP} flex flex-col items-start gap-6 pt-12 pb-16 sm:pt-20 sm:pb-24`}>
            <p className={EYEBROW}>Every trading day · ready by 7:45 AM ET</p>
            <h1 className="text-display font-extrabold">
              Your stocks,
              <br />
              in 30 seconds.
            </h1>
            <p className="max-w-130 text-lg text-muted">
              One card per stock each morning: what happened and what&apos;s next. Facts from SEC filings — no tips, no hype.
            </p>
            <div className="flex flex-wrap gap-3 pt-2">
              <Link href="/cards" className={PRIMARY}>
                {OPEN_CARDS}
              </Link>
              <a href="#card" className={`${CTA} border border-muted bg-surface`}>
                See a sample card
              </a>
            </div>
          </div>
        </section>

        <section aria-label="At a glance">
          <div className={`${WRAP} grid grid-cols-2 gap-3 lg:grid-cols-4`}>
            {STATS.map(([value, label], i) => (
              <div key={label} className="flex flex-col gap-2 rounded-card bg-surface p-5 shadow-card">
                <p className={`text-stat font-extrabold ${i === 0 ? "text-accent-ink" : ""}`}>{value}</p>
                <p className="text-sm font-bold text-muted">{label}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="card" aria-label="The card" className="py-16 sm:py-24">
          <div className={`${WRAP} flex flex-wrap gap-12`}>
            <div className="flex min-w-0 grow basis-105 flex-col gap-5">
              <p className={EYEBROW}>The card</p>
              <h2 className={H2}>Three lines. One fact each.</h2>
              <p className="max-w-120 text-lg text-muted">
                Each card checks the latest SEC filings for one stock and says up top what it found: new filings or a quiet
                day. Never more than three lines. On a quiet day, it may add one background fact from the company&apos;s
                annual report.
              </p>
              <ol className="mt-2 flex flex-col gap-3">
                {CARD_LINES.map(([num, title, body]) => (
                  <li key={num} className="flex gap-4 rounded-card bg-surface p-5 shadow-card">
                    <span aria-hidden="true" className={BADGE}>
                      {num}
                    </span>
                    <div className="flex flex-col gap-1">
                      <h3 className="flex flex-wrap items-center gap-2 text-lg font-extrabold">
                        {title}
                        {num === "3" && <span className={CHIP}>Plus</span>}
                      </h3>
                      <p className="text-muted">{body}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
            <div className="flex min-w-0 grow basis-105 flex-col gap-4">
              {SAMPLES.map((card) => (
                <StockCard key={card.ticker} card={card} sample />
              ))}
              <p className="text-sm text-muted">{REAL_CARDS_FROM(formatTradingDay(SAMPLE_DAY))}</p>
            </div>
          </div>
        </section>

        <section id="how" aria-label="How it works" className="pb-16 sm:pb-24">
          <div className={`${WRAP} flex flex-col gap-10`}>
            <div className="flex flex-col gap-4">
              <p className={EYEBROW}>How it works</p>
              <h2 className={H2}>Set up once. Read every morning.</h2>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <Step
                num="1"
                title="See the latest cards right away"
                body="No account for the first look. Sign in with Google to pick your own stocks."
              >
                <div className="flex min-h-40 grow flex-col justify-center gap-3 rounded-cell bg-background p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-lg font-extrabold">{MSFT.name}</span>
                    <span className={CHIP}>{MSFT.ticker}</span>
                  </div>
                  <p>{MSFT_NEWS}</p>
                </div>
              </Step>
              <Step num="2" title="Pick up to three stocks" body="From the S&P 500 and popular ETFs, with up to three swaps a day.">
                <div className="flex min-h-40 grow flex-wrap content-center items-center justify-center gap-2 rounded-cell bg-background p-5">
                  {SAMPLES.map((c) => (
                    <span key={c.ticker} className="rounded-full bg-surface px-4 py-2 font-extrabold shadow-card">
                      {c.ticker}
                    </span>
                  ))}
                  {/* 점선 테두리는 비텍스트 3:1 기준: muted(크림 위 6.0:1) */}
                  <span className="rounded-full border border-dashed border-muted px-4 py-2 font-extrabold text-muted">+</span>
                </div>
              </Step>
              <Step num="3" title="Come back each trading day" body="New cards are ready by 7:45 AM ET.">
                <div className="flex min-h-40 grow flex-col items-center justify-center gap-2 rounded-cell bg-background">
                  <p className="text-stat font-extrabold tabular-nums">7:45 AM</p>
                  <p className="text-sm font-bold text-muted">ET · Every trading day</p>
                </div>
              </Step>
            </div>
          </div>
        </section>

        {/* Plus 칸(시안의 요금 섹션 자리). 문장은 약관 service 절·방침 use 절·/plus 설명과 같은 말(가격·체험·결제 없음) */}
        <section id="plus" aria-label="Plus">
          <div className={WRAP}>
            <div className="flex flex-col items-start gap-5 rounded-card bg-accent-soft p-6 sm:p-12">
              <p className={EYEBROW}>Plus</p>
              <h2 className={H2}>Free to use. No payments.</h2>
              <p className="max-w-160 text-lg">{PLUS_PLANNED}</p>
              <p className="max-w-160 text-muted">
                Sign in and tap Notify me on the About Plus page. We&apos;ll email your sign-in address once when Plus launches.
              </p>
              {/* 프리페치 없음: /plus 요청 제한(#62)을 쓰지 않게 */}
              <Link href="/plus" prefetch={false} className={`${CTA} mt-2 bg-surface shadow-card`}>
                {ABOUT_PLUS}
              </Link>
            </div>
          </div>
        </section>

        <section id="get" aria-label="Open the cards">
          <div className={`${WRAP} flex flex-col items-center gap-6 py-16 text-center sm:py-24`}>
            <h2 className={`max-w-190 ${H2}`}>The next cards are ready at 7:45 AM ET.</h2>
            <Link href="/cards" className={PRIMARY}>
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
    <article className="flex min-w-0 flex-col gap-5 rounded-card bg-surface p-5 shadow-card">
      {children}
      <div className="flex gap-4">
        <span aria-hidden="true" className={BADGE}>
          {num}
        </span>
        <div className="flex flex-col gap-1">
          <h3 className="text-lg leading-heading font-extrabold">{title}</h3>
          <p className="text-muted">{body}</p>
        </div>
      </div>
    </article>
  );
}
