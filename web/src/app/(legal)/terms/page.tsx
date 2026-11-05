import type { Metadata } from "next";

import { APP_NAME, NOT_INVESTMENT_ADVICE } from "@/lib/copy";

import { Email, LegalDoc, LIST, OPERATOR, PageLink, Section } from "../legal";

export const metadata: Metadata = { title: `Terms of Service · ${APP_NAME}` };

/** 이용약관(#62). 본문 초안 Claude, Paul 확인. 법률 검토는 결제 전(HANDOFF 3-9). 중재 조항은 그때 */
export default function Terms() {
  return (
    <LegalDoc title="Terms of Service">
      <p>
        These terms cover your use of {APP_NAME} (the Service), run by {OPERATOR}. By using the Service, you agree to these
        terms. If you do not agree, please do not use the Service.
      </p>

      <Section id="service" title="The Service">
        <p>
          Every trading day, the Service shows a morning card for each stock in its coverage — a selection of U.S.-listed
          stocks and ETFs — and a short market overview.
        </p>
        <p>
          The Service is free. Plus is not for sale, and we do not take any payments. The Service may show Plus features as
          locked, with an option to hear when Plus launches.
        </p>
        <p>
          The Service does not provide stock prices or real-time quotes. We may change, pause or stop any part of the Service
          at any time.
        </p>
      </Section>

      <Section id="not-advice" title="Not investment advice">
        <p>The Service is for informational purposes only. {NOT_INVESTMENT_ADVICE}.</p>
        <p>
          We are not a broker-dealer or an investment adviser. The content of the Service is not a recommendation to buy, sell
          or hold any security. Investment decisions are yours; if you need advice, talk to a qualified professional.
        </p>
        <p>
          Some sentences are written by AI from public filings and checked by automated rules before they appear. They can
          still contain mistakes. Dates marked (est.) are estimates based on past filings. Background facts marked &quot;Did
          you know&quot; come from a company&apos;s latest annual report and may no longer be current.
        </p>
      </Section>

      <Section id="sources" title="Data sources">
        <p>
          Cards and the market overview are built only from public sources: SEC EDGAR filings (such as 8-K, 10-K and N-PORT
          reports) and public releases from U.S. government agencies (BLS, BEA, Census Bureau and Federal Reserve).
        </p>
        <p>
          We are not affiliated with or endorsed by the SEC or any of these agencies. Company names and tickers are used only
          to identify companies; trademarks belong to their owners.
        </p>
      </Section>

      <Section id="accounts" title="Accounts">
        <p>
          You can sign in with Google only. Use only your own account. You need to be at least 18 years old to use the
          Service.
        </p>
        <p>We may suspend or end access for anyone who abuses the Service or breaks these terms.</p>
      </Section>

      <Section id="use" title="Acceptable use">
        <p>The Service is for personal, non-commercial use. Please do not:</p>
        <ul className={LIST}>
          <li>scrape or bulk-download the Service with automated tools</li>
          <li>get around rate limits or other protections</li>
          <li>disrupt or overload the Service</li>
          <li>redistribute card content for commercial purposes</li>
        </ul>
      </Section>

      <Section id="disclaimers" title="Disclaimers and limitation of liability">
        <p>
          The Service is provided &quot;as is&quot; and &quot;as available&quot;. We make no warranty that it is accurate,
          complete or up to date.
        </p>
        <p>
          To the fullest extent the law allows, we are not liable for any loss or damage that comes from using or relying on
          the Service.
        </p>
        <p>These terms are governed by the laws of the State of California.</p>
      </Section>

      <Section id="changes" title="Changes to these terms">
        <p>
          If we change these terms, we will update the date at the top. If you keep using the Service after a change, you
          accept the new terms.
        </p>
        <p>
          You can stop using the Service at any time. To delete your account, see{" "}
          <PageLink href="/privacy#delete">How to delete your account</PageLink>.
        </p>
      </Section>

      <Section id="contact" title="Contact">
        <p>
          For questions, stock requests or data requests, email <Email />.
        </p>
      </Section>
    </LegalDoc>
  );
}
