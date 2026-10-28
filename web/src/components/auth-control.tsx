import { SIGN_IN, SIGN_IN_FAILED, SIGN_OUT } from "@/lib/copy";

import { TimezoneField } from "./timezone-field";

const BUTTON = "inline-flex min-h-12 cursor-pointer items-center justify-center px-8 py-3 text-center text-sm font-bold tracking-widest uppercase";

/** /cards 위 로그인·로그아웃. 서버 라우트로 보내는 일반 폼이라 브라우저에는 Supabase가 없다(#37) */
export function AuthControl({ signedIn, failed }: { signedIn: boolean; failed: boolean }) {
  if (signedIn) {
    return (
      <form method="post" action="/auth/sign-out" className="mb-8 flex justify-end">
        <button type="submit" className={`${BUTTON} border border-foreground`}>
          {SIGN_OUT}
        </button>
      </form>
    );
  }
  return (
    <div className="mb-8 flex flex-wrap items-center gap-4">
      <form method="post" action="/auth/sign-in">
        <TimezoneField />
        <button type="submit" className={`${BUTTON} bg-accent text-foreground`}>
          {SIGN_IN}
        </button>
      </form>
      {failed && (
        <p role="status" className="text-sm">
          {SIGN_IN_FAILED}
        </p>
      )}
    </div>
  );
}
