/**
 * 로컬 Supabase DB·Auth 테스트 공용 준비. *.test.* 가 아니라 테스트로 실행되지 않는다. 원격 금지.
 * 이메일·비밀번호 로그인은 이 테스트 도우미에만 있다(운영 코드는 guards.test가 막는다).
 */
import { randomUUID } from "node:crypto";

import { createServerClient } from "@supabase/ssr";
import { createClient } from "@supabase/supabase-js";

import type { Jar } from "./cookie-jar";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);
const url = process.env.SUPABASE_URL ?? "";
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";
const publishableKey = process.env.SUPABASE_PUBLISHABLE_KEY ?? "";
if (!url || !serviceKey || !publishableKey) {
  throw new Error("SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and SUPABASE_PUBLISHABLE_KEY must be set (see web/README.md)");
}
if (!LOCAL_HOSTS.has(new URL(url).hostname)) {
  throw new Error("SUPABASE_URL is not local. DB tests run against local Supabase only");
}

export const admin = createClient(url, serviceKey, { auth: { persistSession: false, autoRefreshToken: false } });

export type TestUser = { id: string; email: string; password: string };

export async function createTestUser(): Promise<TestUser> {
  const email = `${randomUUID()}@example.test`;
  const password = randomUUID();
  const { data, error } = await admin.auth.admin.createUser({ email, password, email_confirm: true });
  if (error) throw new Error(`createUser failed: ${error.code}`);
  return { id: data.user.id, email, password };
}

/** 프로필·내 종목은 FK cascade로 같이 지워진다 */
export async function deleteTestUsers(ids: string[]) {
  for (const id of ids) {
    const { error } = await admin.auth.admin.deleteUser(id);
    if (error) throw new Error(`deleteUser failed: ${error.code}`);
  }
}

/** 운영과 같은 ssr 클라이언트로 비밀번호 로그인해 같은 형식의 세션 쿠키를 jar에 넣는다 */
export async function signIn(j: Jar, user: TestUser) {
  const client = createServerClient(url, publishableKey, {
    cookies: { getAll: j.getAll, setAll: (list) => list.forEach((c) => j.set(c.name, c.value, c.options)) },
  });
  const { error } = await client.auth.signInWithPassword({ email: user.email, password: user.password });
  if (error) throw new Error(`signIn failed: ${error.code}`);
}
