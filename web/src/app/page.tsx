/**
 * 랜딩(#27). 사용자 시안 design-system/user-mockup/landing.dc.html을 토큰으로 옮겼다. DB를 읽지 않는 정적 페이지.
 * 시안 문구는 규칙·사실과 어긋나는 곳만 고쳤다(목록: _workspace/issue-27/01_web-dev_report.md 5절, 04_web-dev_report.md).
 */
import Link from "next/link";

import { Brand } from "@/components/brand";
import { StockCard } from "@/components/stock-card";
import type { CardView } from "@/lib/card-view";
import { APP_NAME, OPEN_CARDS } from "@/lib/copy";

const WRAP = "mx-auto max-w-7xl px-8";
const LABEL = "text-label font-semibold tracking-widest uppercase";
const NUM = "text-nav font-semibold tracking-wider text-dim";
const H2 = "text-h2 font-medium";
const PILL = `${LABEL} rounded-full px-3 py-1 whitespace-nowrap`;
const BUTTON = "inline-flex items-center justify-center text-center font-bold tracking-widest uppercase";
const CTA = `${BUTTON} min-h-12 px-8 text-sm`;
const NAV_LINK = "inline-flex min-h-12 items-center text-nav font-semibold tracking-wider uppercase hover:text-hover";

// 샘플 카드: 카드와 같은 컴포넌트·같은 규칙의 문구(card-copy-rules 검사기 통과). 수치는 예시
const SAMPLES = [
  {
    ticker: "AAPL",
    name: "Apple",
    change: { text: "−1.2%", tone: "down" },
    lines: [
      { text: "Apple named a new CFO +2 more (Company)", status: "checked_found" },
      { text: "Earnings Thu 10/15 after close (D-2)", status: "checked_found" },
      { text: "8.0% below 52-week high", status: "checked_found" },
    ],
    leverageTag: null,
    checked: null,
  },
  {
    ticker: "QQQ",
    name: "Nasdaq-100 ETF",
    change: { text: "+0.8%", tone: "up" },
    lines: [
      { text: "No new SEC filings found", status: "checked_none" }, // ETF 첫 번째 줄(상위 편입 종목 소식)은 #10 미정
      { text: "Ex-dividend 12/21 · $0.70/share", status: "checked_found" },
      { text: "Up 5 days in a row", status: "checked_found" },
    ],
    leverageTag: null,
    checked: null,
  },
  {
    ticker: "KO",
    name: "Coca-Cola",
    change: { text: "+0.1%", tone: "up" },
    lines: [
      { text: "No new SEC filings found", status: "checked_none" },
      { text: "No confirmed events found", status: "checked_none" },
      { text: "No additional price highlights", status: "checked_none" },
    ],
    leverageTag: null,
    checked: null,
  },
] satisfies CardView[];

const STATS = [
  ["30", "Seconds to read every stock"],
  ["3", "Lines per stock, one fact each"],
  ["0", "Settings required"],
  ["7:45", "AM ET — cards ready"],
] as const;

const CARD_LINES = [
  ["01", "What happened", "One fact in 15 words or fewer, ending with its source — the company or an SEC filing."],
  ["02", "What's next", "The nearest earnings date or dividend. Earnings show a countdown; unconfirmed dates are marked (est.)."],
  ["03", "Price fact", "The most notable thing in recent closing prices — a streak, or the distance from a 52-week high."],
] as const;

const ARENA_DAY = [
  ["Before the open", "Each agent publishes its calls — new trades and every position it holds."],
  ["At the close", "Calls are graded against the day's open — new trades and held positions alike. Flat days don't count."],
  ["Next morning", "Yesterday's verdicts arrive alongside today's calls. Misses can't be deleted."],
] as const;

const AGENTS = [
  ["A", "Aggressive", "Rides trends. Blunt. Owns the misses.", "12–9", "bg-agent-a text-agent-a-ink"],
  ["S", "Steady", "Value and risk first. One reason at a time.", "11–10", "bg-agent-s text-agent-s-ink"],
] as const;

const PLANS = [
  {
    label: "Free",
    price: "$0",
    note: "No card needed. No ads.",
    features: [
      "Up to 3 stocks, 3 swaps a day",
      "What happened and what's next, on every card",
      "Market at a glance and the morning push",
      "Arena verdicts and records",
      "Monthly report headline",
    ],
    cta: [OPEN_CARDS, "/cards", "border border-background text-background"],
    border: "border-hover",
  },
  {
    label: "Plus · billed yearly",
    badge: "3-day free trial",
    price: "$79.99",
    per: " / year",
    note: "About $0.22 a day · or $9.99 monthly",
    features: [
      "Every stock in coverage, unlimited swaps",
      "The price-fact line on every card",
      "Today's Arena calls and agent talk",
      "Monthly report by stock vs. S&P 500 (SPY)",
      "Everything in Free",
    ],
    cta: [OPEN_CARDS, "/cards", "bg-accent text-foreground"],
    border: "border-background",
  },
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
            <a href="#arena" className={NAV_LINK}>
              AI Arena
            </a>
            <a href="#pricing" className={NAV_LINK}>
              Pricing
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
                One card per stock each morning: what happened, what&apos;s scheduled, one price fact. Facts from filings
                and closing prices — no tips, no hype.
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
            <div className="flex grow basis-80 justify-center">
              <div
                role="img"
                aria-label="Lock screen showing the morning push"
                className="flex h-140 w-75 flex-col items-center overflow-hidden rounded-phone border-10 border-black bg-linear-172/srgb from-dusk-1 via-dusk-2 via-58% to-dusk-3 px-3.5 pt-14"
              >
                <p className="text-md font-medium">Tuesday, October 13</p>
                <p className="text-clock font-semibold tabular-nums">8:00</p>
                <div className="mt-10 w-full rounded-push bg-foreground/82 px-3.5 py-3 text-background">
                  <div className="flex items-center gap-2 text-xs text-push-meta">
                    <span className="flex size-5 items-center justify-center rounded-icon bg-accent text-micro font-bold text-foreground">
                      30s
                    </span>
                    <span>{APP_NAME}</span>
                    <span className="ml-auto">now</span>
                  </div>
                  <p className="mt-1.5 leading-snug font-medium">
                    Today: Apple named a new CFO. No new SEC filings for QQQ or KO.
                  </p>
                </div>
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
                The day&apos;s change sits on top, measured from the previous close. Below it, never more than three lines —
                and on a quiet day, the card says so instead of filling space.
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
                <StockCard key={card.ticker} card={card} />
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
              <Step num="01" title="Pick up to three stocks" body="Anything in the S&P 500 plus about 50 popular ETFs. Plus removes the limit.">
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
                num="02"
                title="See today's card right away"
                body="No account for the first look. Sign in with Apple or Google to keep the list."
              >
                <div className="flex h-55 flex-col justify-center gap-3 bg-surface px-8 py-6">
                  <div className="flex items-baseline gap-3">
                    <span className="text-lg font-bold">AAPL</span>
                    <span className="flex-1 text-muted">Apple</span>
                    <span className="text-lg font-semibold text-down tabular-nums">−1.2%</span>
                  </div>
                  <div className="h-px bg-border" />
                  <p>{SAMPLES[0].lines[0].text}</p>
                </div>
              </Step>
              <Step
                num="03"
                title="Choose a morning time"
                body="One sentence arrives on the lock screen. Skip it and it lands 30 minutes before the open."
              >
                <div className="flex h-55 flex-col items-center justify-center gap-2 bg-surface">
                  <p className="text-price font-medium tabular-nums">8:00 AM</p>
                  <p className={`${LABEL} text-muted`}>Local time · after 7:45 AM ET</p>
                </div>
              </Step>
            </div>
          </div>
        </section>

        <section id="arena" aria-label="AI Arena" className="bg-accent">
          <div className={`${WRAP} flex flex-col gap-6 py-24`}>
            <p className={LABEL}>AI Arena · mock trading</p>
            <h2 className={`max-w-220 ${H2}`}>
              Two AI agents trade play money. Every call is graded at the close — and stays on the record.
            </h2>
            <p className="max-w-160 text-base">
              $10,000 of virtual cash each, long only, daily prices only. Their calls and talk live inside the Arena tab —
              never on the cards.
            </p>
          </div>
        </section>

        <section aria-label="Agents" className="py-24">
          <div className={`${WRAP} flex flex-col gap-16`}>
            <div className="flex flex-wrap gap-8">
              {AGENTS.map(([initial, name, style, record, avatar]) => (
                <article key={name} className="flex min-w-0 grow basis-105 flex-col gap-6 bg-surface p-6">
                  {/* 한 줄에 안 들어가면(좁은 폭) Sample 알약이 다음 줄 오른쪽으로. 묶음 기본 폭 192px이 아바타·간격·이름(약 173px)보다 커서 같은 줄일 때 이름과 닿지 않는다 */}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
                    <div className="flex min-w-0 grow basis-48 items-center gap-4">
                      <span
                        aria-hidden="true"
                        className={`flex size-14 shrink-0 items-center justify-center rounded-full text-xl font-bold ${avatar}`}
                      >
                        {initial}
                      </span>
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <h3 className="text-lg leading-heading font-bold">{name}</h3>
                        <p className="text-muted">{style}</p>
                      </div>
                    </div>
                    <span className={`${PILL} ml-auto bg-background`}>Sample</span>
                  </div>
                  <div className="flex flex-col gap-1 border-t border-border pt-6">
                    <p className="text-stat font-bold tabular-nums">{record}</p>
                    <p className={`${LABEL} text-muted`}>Hits – misses</p>
                  </div>
                </article>
              ))}
            </div>
            <dl className="flex flex-col border-b border-surface">
              {ARENA_DAY.map(([when, what]) => (
                <div key={when} className="flex flex-wrap gap-x-8 gap-y-2 border-t border-surface py-6">
                  <dt className={`shrink-0 basis-50 ${NUM} uppercase`}>{when}</dt>
                  <dd className="grow basis-100 text-base">{what}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section id="pricing" aria-label="Pricing" className="bg-foreground text-background">
          <div className={`${WRAP} flex flex-col gap-12 py-24`}>
            <div className="flex flex-col gap-4">
              <p className={`${LABEL} text-ink-muted`}>Pricing</p>
              <h2 className={H2}>Free to start. Plus when three isn&apos;t enough.</h2>
            </div>
            <div className="flex flex-wrap gap-8">
              {PLANS.map((plan) => (
                <article key={plan.label} className={`flex min-w-0 grow basis-95 flex-col gap-6 border p-8 ${plan.border}`}>
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                      <h3 className={`${LABEL} text-ink-muted`}>{plan.label}</h3>
                      {"badge" in plan && <span className={`${PILL} bg-ink-line`}>{plan.badge}</span>}
                    </div>
                    <p className="text-price font-medium">
                      {plan.price}
                      {"per" in plan && <span className="text-lg tracking-normal text-ink-muted">{plan.per}</span>}
                    </p>
                    <p className="text-ink-muted">{plan.note}</p>
                  </div>
                  <ul className="flex flex-col border-t border-hover">
                    {plan.features.map((f) => (
                      <li key={f} className="border-b border-ink-line py-3">
                        {f}
                      </li>
                    ))}
                  </ul>
                  <a href={plan.cta[1]} className={`mt-auto ${CTA} focus-visible:outline-background ${plan.cta[2]}`}>
                    {plan.cta[0]}
                  </a>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="get" aria-label="Open the cards" className="border-b border-surface">
          <div className={`${WRAP} flex flex-col items-center gap-8 py-24 text-center`}>
            <h2 className={`max-w-190 ${H2}`}>The next cards are ready at 7:45 AM ET.</h2>
            <Link href="/cards" className={`${CTA} bg-accent`}>
              {OPEN_CARDS}
            </Link>
            <p className="text-xs text-dim">Private web preview for now.</p>
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
