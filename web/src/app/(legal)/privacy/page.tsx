import type { Metadata } from "next";

import { APP_NAME } from "@/lib/copy";

import { Email, LegalDoc, LIST, OPERATOR, PageLink, Section } from "../legal";

export const metadata: Metadata = { title: `Privacy Policy · ${APP_NAME}` };

/**
 * 개인정보처리방침(#62). 저장 항목은 마이그레이션·코드와 대조했다(auth.users·identities·sessions, user_profile, my_stock,
 * my_stock_history, morning_notice, 대기 등록 #69). 실제보다 적게 쓰지 않는다. 저장 지역은 확인 전이라 제공자 이름만(사용자 결정)
 */
export default function Privacy() {
  return (
    <LegalDoc title="Privacy Policy">
      <p>
        This policy explains what {APP_NAME}, run by {OPERATOR}, stores about you, how it is used, and how to have it deleted.
        Questions: <Email />
      </p>

      <Section id="collect" title="What we store">
        <h3 className="font-bold">When you sign in with Google</h3>
        <ul className={LIST}>
          <li>
            <strong>Your account</strong>, stored by Supabase Auth: your email address, your Google account ID, the name and
            profile photo link that Google shares with us (we store them but do not use or show them), when you signed up and
            last signed in, and the IP address and browser details of your sign-in sessions.
          </li>
          <li>
            <strong>Your profile</strong>: your plan (Free or Plus), the time zone your browser reported when you signed in,
            your morning notification time if you set one, and when you tapped Notify me if you asked to hear about Plus.
          </li>
          <li>
            <strong>Your stocks</strong>: the stocks you pick, and a history of each add and remove with its time and your
            local date. We use this to apply plan limits such as daily swaps and to choose which background fact a card shows.
          </li>
          <li>
            <strong>Morning summary</strong>: a one-line summary of your stocks that we prepare for you each trading day.
          </li>
        </ul>
        <h3 className="font-bold">Even if you don&apos;t sign in</h3>
        <ul className={LIST}>
          <li>
            Our hosting and database providers keep server logs — IP address, browser type and the pages requested — for a
            limited time to run and secure the Service.
          </li>
          <li>To limit request rates, your IP address is kept in server memory for about a minute.</li>
          <li>Taps on locked Plus features are counted only as daily totals and are not linked to you.</li>
        </ul>
      </Section>

      <Section id="not-collect" title="What we don't store">
        <p>
          Payment information (there are no payments), brokerage accounts, your holdings or what you paid for them, your
          contacts, or advertising trackers.
        </p>
      </Section>

      <Section id="use" title="How we use it">
        <p>
          To sign you in, show the cards for your stocks, apply plan limits (number of stocks and swaps), prevent abuse and
          keep the Service secure.
        </p>
        <p>If you tap Notify me, we will email your sign-in address once when Plus launches.</p>
        <p>We do not sell your personal information, and we do not share it for targeted advertising.</p>
      </Section>

      <Section id="share" title="Service providers">
        <p>
          We use these providers to run the Service: Supabase (database and sign-in), Vercel (website hosting), Google
          (sign-in) and GitHub (runs the daily job that builds cards and morning summaries).
        </p>
        <p>The AI that writes card sentences receives only public filings, never your personal information.</p>
        <p>We may disclose information if the law requires it.</p>
      </Section>

      <Section id="cookies" title="Cookies">
        <p>
          We use only the cookies the site needs to work, such as keeping you signed in. No advertising or analytics cookies.
        </p>
        <p>Do Not Track: we do not track you across other sites, so nothing changes when your browser sends this signal.</p>
      </Section>

      <Section id="keep" title="How long we keep it">
        <p>
          We keep your account data while your account exists. Server logs and backups are deleted on each provider&apos;s own
          schedule.
        </p>
        <p>Your data is held by the providers above: Supabase for the database and sign-in, and Vercel for hosting.</p>
      </Section>

      <Section id="delete" title="How to delete your account">
        <p>
          Email <Email /> from the address you sign in with, with the subject &quot;Delete my account&quot;.
        </p>
        <p>
          Within 30 days, we will delete your account and everything linked to it — your profile, your stocks and their
          history, your morning summaries and your Notify me sign-up — and reply to confirm.
        </p>
        <p>
          You can sign out at any time on the <PageLink href="/cards">cards page</PageLink>.
        </p>
      </Section>

      <Section id="rights" title="Your rights">
        <p>
          Depending on where you live (for example, California), you may have the right to access, correct or delete your
          personal information. To make a request, email us at the address under Contact below. We will not discriminate
          against you for using these rights.
        </p>
      </Section>

      <Section id="children" title="Children">
        <p>
          The Service is not directed at children under 13. If we learn that we hold data from a child under 13, we will
          delete it.
        </p>
      </Section>

      <Section id="changes" title="Changes to this policy">
        <p>If we change this policy, we will update the date at the top. We will announce important changes on the site.</p>
      </Section>

      <Section id="contact" title="Contact">
        <p>
          Questions about this policy or your data: <Email />
        </p>
      </Section>
    </LegalDoc>
  );
}
