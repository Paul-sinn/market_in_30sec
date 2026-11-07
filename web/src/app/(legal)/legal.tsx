/**
 * 이용약관·개인정보처리방침이 같이 쓰는 값과 틀(#62). 본문은 각 page.tsx(정적, DB를 읽지 않는다).
 * 연락 이메일은 사용자 결정(2026-11-04)으로 이 폴더(법률 페이지) 밖에 쓰지 않는다(tests/guards.test.ts).
 */
export const CONTACT_EMAIL = "pauldevapps@gmail.com"; // 연락·삭제 요청 주소(공개 사이트와 공개 레포에 남는다)
export const OPERATOR = "Paul Sin"; // 운영자 표기: 개인(LLC 설립 전, HANDOFF 3-9)
export const LEGAL_UPDATED = "November 7, 2026"; // 두 페이지 본문을 바꾸면 같이 바꾼다

// 본문 링크: 밑줄(색만으로 구분하지 않게) + 터치 영역 44px
const LINK = "inline-flex min-h-11 items-center underline underline-offset-4 hover:text-hover";

export const Email = () => (
  <a href={`mailto:${CONTACT_EMAIL}`} className={LINK}>
    {CONTACT_EMAIL}
  </a>
);

/** 사이트 안 링크. 일반 <a>: /cards를 미리 받지 않는다(요청 제한을 쓰지 않게) */
export const PageLink = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <a href={href} className={LINK}>
    {children}
  </a>
);

/** 제목(h1) + 마지막 수정일 + 본문. 본문 폭은 읽기 좋은 65자 */
export function LegalDoc({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <article className="flex max-w-prose flex-col gap-10 text-base">
      <div className="flex flex-col gap-3">
        <h1 className="text-h2 font-medium">{title}</h1>
        <p className="text-dim">Last updated: {LEGAL_UPDATED}</p>
      </div>
      {children}
    </article>
  );
}

/** 절 하나: id는 하단 링크(/terms#contact, /privacy#delete)가 가리키므로 바꾸지 않는다 */
export function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="flex flex-col gap-3">
      <h2 className="text-xl leading-heading font-bold">{title}</h2>
      {children}
    </section>
  );
}

export const LIST = "flex list-disc flex-col gap-2 pl-6";
