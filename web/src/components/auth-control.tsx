import { SIGN_IN, SIGN_IN_FAILED, SIGN_OUT } from "@/lib/copy";

import { TimezoneField } from "./timezone-field";

const BUTTON = "inline-flex min-h-12 cursor-pointer items-center justify-center rounded-full px-6 py-3 text-center font-bold transition hover:brightness-95";

/** /cards 위 로그인·로그아웃. 서버 라우트로 보내는 일반 폼이라 브라우저에는 Supabase가 없다(#37) */
export function AuthControl({ signedIn, failed }: { signedIn: boolean; failed: boolean }) {
  if (signedIn) {
    return (
      <form method="post" action="/auth/sign-out" className="mb-6 flex justify-end">
        <button type="submit" className={`${BUTTON} border border-muted bg-surface`}>
          {SIGN_OUT}
        </button>
      </form>
    );
  }
  return (
    <div className="mb-6 flex flex-wrap items-center gap-4">
      <form method="post" action="/auth/sign-in">
        <TimezoneField />
        <button type="submit" className={`${BUTTON} bg-accent text-foreground shadow-card`}>
          {SIGN_IN}
        </button>
      </form>
      {failed && (
        <p role="status" className="rounded-cell bg-surface px-4 py-3 text-sm">
          {SIGN_IN_FAILED}
        </p>
      )}
    </div>
  );
}
