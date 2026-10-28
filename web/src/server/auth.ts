import "server-only";

import { createServerClient, type CookieMethodsServer } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

// Supabase Auth는 이 모듈에서만(ADR-0003, #37). 브라우저에는 클라이언트·키가 없고 세션은 HttpOnly 쿠키에만 있다

/** getVerifiedUserId·exchangeCode만 만든다. my-stocks 함수는 이 타입만 받는다(요청에서 온 문자열은 tsc가 막는다) */
export type VerifiedUserId = string & { readonly __brand: "VerifiedUserId" };

// ssr 기본값은 httpOnly: false라 반드시 덮어쓴다(tests/auth.test.ts·auth.db.test.ts). maxAge는 ssr이 400일로 고정
const COOKIE_OPTIONS = { httpOnly: true, secure: true, sameSite: "lax", path: "/" } as const;

/** 고정 이유 코드만 남긴다. 코드·토큰·쿠키·이메일·쿼리 붙은 URL은 로그에 넣지 않는다 */
function fail(reason: string): null {
  console.warn(`auth: reason=${reason}`);
  return null;
}

/** 로그인 설정. 둘 중 하나라도 없으면 null(로그인 미설정 → 로그인 전 화면, 카드는 그대로). 서비스 역할 키는 읽지 않는다 */
function loginEnv() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_PUBLISHABLE_KEY;
  return url && key ? { url, key } : null;
}

const client = (env: { url: string; key: string }, cookieMethods: CookieMethodsServer) =>
  createServerClient(env.url, env.key, { cookies: cookieMethods, cookieOptions: COOKIE_OPTIONS });

/** 페이지·라우트 핸들러·서버 액션용(next/headers). 로그인 미설정이면 null */
async function fromRequestCookies() {
  const env = loginEnv();
  if (!env) return null;
  const store = await cookies();
  return client(env, {
    getAll: () => store.getAll(),
    setAll(list) {
      try {
        for (const { name, value, options } of list) store.set(name, value, options);
      } catch {
        // 서버 컴포넌트는 쿠키를 쓸 수 없다. 갱신은 proxy(refreshSession)가 이미 했다
      }
    },
  });
}

/** Auth 서버에 확인한 현재 유저. 쿠키 없음·위조·만료·로그인 미설정·Auth 오류 → null. throw하지 않는다 */
export async function getVerifiedUserId(): Promise<VerifiedUserId | null> {
  try {
    const supabase = await fromRequestCookies();
    if (!supabase) return null;
    // getSession().user는 쿠키 그대로라 믿지 않는다. getUser()는 Auth 서버 /user에 묻는다(쿠키가 없으면 요청 없이 오류)
    const { data, error } = await supabase.auth.getUser();
    return error ? null : (data.user.id as VerifiedUserId);
  } catch {
    return null;
  }
}

/** Google 로그인 시작. PKCE 검증값 쿠키를 심고 Supabase /authorize URL을 돌려준다.
 *  로그인 미설정 / Google 꺼짐 / Auth 응답 없음 / URL 생성 실패 → null */
export async function startGoogleSignIn(origin: string, timezone: string): Promise<string | null> {
  const env = loginEnv();
  if (!env) return fail("not_configured");
  // Google이 꺼진 채 /authorize로 보내면 Supabase의 JSON 400이 화면에 그대로 나온다. 먼저 설정을 묻는다
  let google: unknown;
  try {
    const res = await fetch(`${env.url}/auth/v1/settings`, { headers: { apikey: env.key } });
    if (!res.ok) return fail("auth_unreachable");
    google = (await res.json())?.external?.google;
  } catch {
    return fail("auth_unreachable");
  }
  if (google !== true) return fail("provider_off");

  const redirectTo = new URL("/auth/callback", origin);
  redirectTo.searchParams.set("timezone", timezone); // Supabase가 콜백 때 그대로 돌려준다
  const { data, error } = await (await fromRequestCookies())!.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: redirectTo.href },
  });
  return error || !data.url ? fail("oauth_url") : data.url;
}

/** 콜백 코드 교환. 세션 쿠키를 심고 Auth 서버가 돌려준 user id를 준다. 실패(검증값 쿠키 없음 포함) → null */
export async function exchangeCode(code: string): Promise<VerifiedUserId | null> {
  try {
    const supabase = await fromRequestCookies();
    if (!supabase) return fail("not_configured");
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);
    return error ? fail(`exchange_failed code=${error.code ?? "unknown"}`) : (data.user.id as VerifiedUserId);
  } catch {
    return fail("exchange_failed code=unknown");
  }
}

/** 이 기기 세션만(scope local). Auth 호출이 실패해도 auth-js가 세션 쿠키를 지운다. 로그인 미설정이면 아무것도 안 한다 */
export async function signOut(): Promise<void> {
  try {
    await (await fromRequestCookies())?.auth.signOut({ scope: "local" });
  } catch {
    // 로그아웃은 언제나 /cards로 보낸다
  }
}

/** proxy 전용. 게이트를 통과한 요청에만 부른다. 만료 직전이면 refresh하고, 새 쿠키를 응답(Set-Cookie)과
 *  이번 요청의 페이지(request cookies) 둘 다에 넘긴다. 페이지(서버 컴포넌트)는 쿠키를 쓸 수 없어서다. throw하지 않는다 */
export async function refreshSession(request: NextRequest): Promise<NextResponse> {
  const env = loginEnv();
  if (!env || request.nextUrl.pathname.startsWith("/_next/")) return NextResponse.next(); // 정적 파일은 동시 refresh를 만들지 않게
  try {
    const written: Parameters<NonNullable<CookieMethodsServer["setAll"]>>[0] = [];
    const cache: Record<string, string> = {};
    // shortcut: Auth 장애 중 만료 세션은 auth-js refresh 재시도(최대 약 30초)만큼 느려진다(스펙 R1). 실제로 보이면 fetch 타임아웃을 넣는다
    await client(env, {
      getAll: () => request.cookies.getAll(),
      // 한 번의 getSession에서 여러 번 불릴 수 있고 캐시 금지 헤더는 첫 번째에만 온다. 모아서 끝에 한 번에 넘긴다
      setAll(list, headers) {
        written.push(...list);
        Object.assign(cache, headers);
      },
    }).auth.getSession(); // 만료 90초 전이 아니면 쿠키만 읽는다. .user는 읽지 않는다(권한 판단은 getVerifiedUserId)
    if (written.length === 0) return NextResponse.next();

    for (const { name, value } of written) request.cookies.set(name, value);
    const res = NextResponse.next({ request: { headers: request.headers } });
    for (const { name, value, options } of written) res.cookies.set(name, value, options);
    for (const [k, v] of Object.entries(cache)) res.headers.set(k, v);
    return res;
  } catch {
    return NextResponse.next();
  }
}
