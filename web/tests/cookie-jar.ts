/**
 * 쿠키 상자(테스트 공용, DB 없음). next/headers의 cookies() 자리에 넣고, ssr이 쓴 마지막 options를 기록한다.
 * local-supabase.ts는 import 때 로컬 env를 요구하므로 DB 없이 도는 auth.test가 쓸 수 있게 따로 둔다.
 */
import type { CookieOptions } from "@supabase/ssr";

export function jar(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  const options = new Map<string, CookieOptions>();
  return {
    values,
    options,
    getAll: () => [...values].map(([name, value]) => ({ name, value })),
    get: (name: string) => (values.has(name) ? { name, value: values.get(name)! } : undefined),
    set(name: string, value: string, opts: CookieOptions = {}) {
      values.set(name, value);
      options.set(name, opts);
    },
  };
}
export type Jar = ReturnType<typeof jar>;

/** ssr 세션 쿠키 이름: sb-<ref>-auth-token, 크면 .0 .1 … 조각 */
export const SESSION = /^sb-[^.]+-auth-token(\.\d+)?$/;

/** 값이 있는 세션 쿠키 조각 이름 */
export const sessionCookies = (j: Jar) => [...j.values].filter(([n, v]) => SESSION.test(n) && v !== "").map(([n]) => n);

type Session = { access_token: string; refresh_token: string; expires_at: number; user: { id: string } } & Record<string, unknown>;

/** 조각을 이어 붙여 ssr 형식(base64-<base64url JSON>)을 푼다 */
export function readSession(j: Jar): Session {
  const raw = sessionCookies(j)
    .sort()
    .map((n) => j.values.get(n))
    .join("");
  return JSON.parse(Buffer.from(raw.slice("base64-".length), "base64url").toString("utf8"));
}

/** 세션을 한 쿠키(조각 없음)로 다시 쓴다. 이름은 기존 조각에서 가져오거나 base로 */
export function writeSession(j: Jar, session: object, base = sessionCookies(j)[0]?.replace(/\.\d+$/, "")) {
  for (const n of sessionCookies(j)) j.values.delete(n);
  j.values.set(base!, `base64-${Buffer.from(JSON.stringify(session), "utf8").toString("base64url")}`);
}
