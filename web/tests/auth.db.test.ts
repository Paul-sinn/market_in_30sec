/**
 * 로그인 세션 확인을 로컬 Supabase Auth의 진짜 세션으로 본다(정상·없음·위조·만료, 프록시 갱신, 로그아웃, 콜백 실패). 원격 금지.
 * Google OAuth 자체는 자동 테스트하지 않는다(로컬 Google 꺼짐, 운영에서 수동 확인).
 */
import { NextRequest } from "next/server";
import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";

import { GET as callback } from "@/app/auth/callback/route";
import { POST as signOutRoute } from "@/app/auth/sign-out/route";
import { proxy } from "@/proxy";
import { getVerifiedUserId } from "@/server/auth";

import { jar, readSession, SESSION, sessionCookies, writeSession, type Jar } from "./cookie-jar";
import { createTestUser, deleteTestUsers, signIn, admin, type TestUser } from "./local-supabase";

// 페이지·라우트 핸들러가 쓰는 next/headers cookies() 자리에 테스트 쿠키 상자
const box = vi.hoisted(() => ({ jar: undefined as unknown }));
vi.mock("next/headers", () => ({ cookies: async () => box.jar }));
const use = (j: Jar) => (box.jar = j);

let a: TestUser;
let b: TestUser;
beforeAll(async () => {
  [a, b] = await Promise.all([createTestUser(), createTestUser()]);
});
afterAll(() => deleteTestUsers([a, b].filter(Boolean).map((u) => u.id)));
afterEach(() => vi.unstubAllEnvs());

async function signedIn(user: TestUser) {
  const j = jar();
  await signIn(j, user);
  expect(sessionCookies(j).length).toBeGreaterThan(0);
  return j;
}
const now = () => Math.floor(Date.now() / 1000);
const location = (res: Response) => {
  const u = new URL(res.headers.get("location")!);
  return u.pathname + u.search;
};

test("정상: 로그인한 세션 → 그 유저 id", async () => {
  use(await signedIn(a));
  expect(await getVerifiedUserId()).toBe(a.id);
});

test("없음: 세션 쿠키 없음 → null", async () => {
  use(jar());
  expect(await getVerifiedUserId()).toBeNull();
});

test("위조: 쓰레기 값 / sub만 바꾼 토큰(서명 그대로) / 먼 미래 만료 + 쓰레기 토큰 → 셋 다 null", async () => {
  const real = await signedIn(a);
  const name = sessionCookies(real)[0].replace(/\.\d+$/, "");
  const s = readSession(real);

  use(jar({ [name]: "garbage" }));
  expect(await getVerifiedUserId()).toBeNull();

  // 쿠키 안 user도 b로 바꾼다: 쿠키의 유저를 그대로 믿으면 b가 나온다
  const [head, payload, sig] = s.access_token.split(".");
  const forged = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(payload, "base64url").toString("utf8")), sub: b.id }), "utf8");
  const swapped = jar();
  writeSession(swapped, { ...s, access_token: `${head}.${forged.toString("base64url")}.${sig}`, user: { ...s.user, id: b.id } }, name);
  use(swapped);
  expect(await getVerifiedUserId()).toBeNull();

  const garbage = jar();
  writeSession(garbage, { ...s, access_token: "garbage", expires_at: now() + 365 * 24 * 3600 }, name);
  use(garbage);
  expect(await getVerifiedUserId()).toBeNull();
});

test("만료: refresh token 폐기 + 저장된 만료 시각이 과거 → null", async () => {
  const j = await signedIn(a);
  const s = readSession(j);
  const { error } = await admin.auth.admin.signOut(s.access_token, "local");
  expect(error).toBeNull();
  writeSession(j, { ...s, expires_at: now() - 60 });
  use(j);
  expect(await getVerifiedUserId()).toBeNull();
});

test("프록시 갱신: 게이트 통과 + 만료된 세션 → 새 세션 쿠키(HttpOnly·Secure·Lax)를 응답과 이번 요청 둘 다에", async () => {
  vi.stubEnv("DASHBOARD_USER", "canary-owner");
  vi.stubEnv("DASHBOARD_PASSWORD", "canary-pw-db");
  const basic = `Basic ${Buffer.from("canary-owner:canary-pw-db").toString("base64")}`;
  const gate = (await proxy(new NextRequest("https://example.test/cards", { headers: { authorization: basic } })))
    .headers.get("set-cookie")
    ?.match(/^m30_auth=([^;]*)/)?.[1];
  expect(gate).toBeTruthy();

  const j = await signedIn(a);
  const s = readSession(j);
  writeSession(j, { ...s, expires_at: now() - 60 });
  const cookie = [`m30_auth=${gate}`, ...j.getAll().map((c) => `${c.name}=${c.value}`)].join("; ");
  const res = await proxy(new NextRequest("https://example.test/cards", { headers: { cookie } }));

  expect(res.status).toBe(200);
  expect(res.headers.get("x-middleware-next")).toBe("1");
  const set = res.headers.getSetCookie().filter((c) => SESSION.test(c.slice(0, c.indexOf("="))) && !/^[^=]+=;/.test(c));
  expect(set.length).toBeGreaterThan(0);
  for (const c of set) for (const attr of [/; HttpOnly(;|$)/i, /; Secure(;|$)/i, /; SameSite=Lax(;|$)/i, /; Path=\/(;|$)/i]) expect(c).toMatch(attr);
  expect(res.headers.get("cache-control")).toMatch(/no-store/);

  const pairs = set.map((c) => c.slice(0, c.indexOf(";")));
  const fresh = jar(Object.fromEntries(pairs.map((p) => [p.slice(0, p.indexOf("=")), p.slice(p.indexOf("=") + 1)])));
  expect(readSession(fresh).access_token).not.toBe(s.access_token);
  // 같은 요청의 페이지도 새 쿠키를 받는다(받지 못하면 페이지가 옛 refresh token을 다시 쓴다)
  const forwarded = res.headers.get("x-middleware-request-cookie") ?? "";
  for (const p of pairs) expect(forwarded).toContain(p);

  use(fresh);
  expect(await getVerifiedUserId()).toBe(a.id);
});

test("로그아웃 → 303 /cards, 세션 쿠키 삭제(빈 값·maxAge 0), Auth 서버에서도 세션 폐기", async () => {
  const j = await signedIn(a);
  const before = Object.fromEntries(j.values);
  const names = sessionCookies(j);
  use(j);

  const res = await signOutRoute(new NextRequest("http://localhost/auth/sign-out", { method: "POST" }));
  expect(res.status).toBe(303);
  expect(location(res)).toBe("/cards");
  for (const n of names) {
    expect(j.values.get(n), n).toBe("");
    expect(j.options.get(n)?.maxAge, n).toBe(0);
  }

  use(jar(before)); // 로그아웃 전 쿠키를 그대로 다시 보내도
  expect(await getVerifiedUserId()).toBeNull();
});

test("콜백 실패: code 없음 · 공급자 오류 · 가짜 code(검증값 없음/있음) → 303 /cards?sign_in=failed, 세션 쿠키 없음", async () => {
  const base = sessionCookies(await signedIn(a))[0].replace(/\.\d+$/, "");
  const verifier = { [`${base}-code-verifier`]: `base64-${Buffer.from(JSON.stringify("v".repeat(56))).toString("base64url")}` };
  for (const [query, cookies] of [
    ["", {}],
    ["?error=access_denied&error_description=denied", {}],
    ["?code=fake", {}],
    ["?code=00000000-0000-4000-8000-000000000000&timezone=Asia%2FSeoul", verifier], // Auth 서버까지 가서 거절된다
  ] as const) {
    const j = use(jar(cookies));
    const res = await callback(new NextRequest(`http://localhost/auth/callback${query}`));
    expect(res.status, query).toBe(303);
    expect(location(res), query).toBe("/cards?sign_in=failed");
    expect(sessionCookies(j), query).toEqual([]);
  }
});
