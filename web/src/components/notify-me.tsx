import Link from "next/link";

import { ABOUT_PLUS, NOTIFY_FAILED, NOTIFY_ME, NOTIFY_ME_NOTE, ON_THE_LIST, OPEN_CARDS, PLUS_PLANNED, SIGN_IN_TO_NOTIFY } from "@/lib/copy";

import { TimezoneField } from "./timezone-field";

/** /plus 화면 모델(#69). failed = POST /waitlist의 등록 저장 실패(/plus?notify=failed) */
export type NotifyMeView = { signedIn: boolean; waitlisted: boolean; failed: boolean };

const BUTTON = "inline-flex min-h-12 cursor-pointer items-center justify-center rounded-full bg-accent px-6 py-3 text-center font-bold text-foreground shadow-card transition hover:brightness-95";
const STATUS = "rounded-cell bg-accent-soft px-4 py-3";

/** 잠긴 자리·세 번째 줄 잠금이 모두 오는 하나의 설명 + Notify me(#69). 일반 폼 POST라 브라우저에 Supabase가 없고, 이메일 입력칸이 없다.
 *  로그인 전 = 로그인 버튼만, 미등록 = Notify me, 등록됨 = 상태 문구만, 저장 실패 = 실패 문구 + Notify me 다시 */
export function NotifyMe({ view }: { view: NotifyMeView }) {
  return (
    <article className="flex max-w-prose flex-col gap-6 rounded-card bg-surface p-6 shadow-card sm:p-10">
      {/* 프리페치 없음: /cards 요청 제한(#62)을 쓰지 않게 */}
      <Link href="/cards" prefetch={false} className="inline-flex min-h-11 items-center self-start text-sm font-bold underline underline-offset-4">
        {OPEN_CARDS}
      </Link>
      <h1 className="text-h2 font-extrabold">{ABOUT_PLUS}</h1>
      <p className="text-muted">{PLUS_PLANNED}</p>
      {view.signedIn && view.waitlisted ? (
        <p role="status" className={STATUS}>
          {ON_THE_LIST}
        </p>
      ) : (
        <>
          <p>{NOTIFY_ME_NOTE}</p>
          {view.signedIn && view.failed && (
            <p role="status" className={STATUS}>
              {NOTIFY_FAILED}
            </p>
          )}
          {view.signedIn ? (
            <form method="post" action="/waitlist">
              <input type="hidden" name="intent" value="notify" />
              <button type="submit" className={BUTTON}>
                {NOTIFY_ME}
              </button>
            </form>
          ) : (
            // 로그인 폼은 /cards의 AuthControl과 같다(돌아오는 곳은 /cards 고정)
            <form method="post" action="/auth/sign-in">
              <TimezoneField />
              <button type="submit" className={BUTTON}>
                {SIGN_IN_TO_NOTIFY}
              </button>
            </form>
          )}
        </>
      )}
    </article>
  );
}
