/**
 * 로그인 라우트·세션 확인의 실패 경로와 연결(DB·Auth 없이). fetch를 흉내 내 Google 켜짐/꺼짐/응답 없음을 본다.
 * 진짜 세션은 auth.db.test.ts가 로컬 Auth로 본다.
 */
import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { GET as callback } from "@/app/auth/callback/route";
import { POST as signInRoute } from "@/app/auth/sign-in/route";
import { exchangeCode, getVerifiedUserId, type VerifiedUserId } from "@/server/auth";
import { ensureProfile } from "@/server/my-stocks";

import { jar, sessionCookies, writeSession, type Jar } from "./cookie-jar";

const box = vi.hoisted(() => ({ jar: undefined as unknown }));
vi.mock("next/headers", () => ({ cookies: async () => box.jar }));
vi.mock("@/server/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/server/auth")>()),
  exchangeCode: vi.fn(),
}));
vi.mock("@/server/my-stocks", () => ({ ensureProfile: vi.fn() }));

const URL_ = "http://127.0.0.1:54321";
const KEY = "canary-publishable-key";
const fetchMock = vi.fn<typeof fetch>();
const use = (j: Jar) => (box.jar = j);

/** 만료 안 된 가짜 세션(서명 없음): Auth에 물어보기 전에는 진짜처럼 보인다 */
const withFakeSession = () => {
  const j = jar();
  const exp = Math.floor(Date.now() / 1000) + 3600;
  writeSession(j, { access_token: "a.b.c", refresh_token: "r", token_type: "bearer", expires_in: 3600, expires_at: exp, user: { id: "u" } }, "sb-127-auth-token");
  return j;
};
const signInForm = (timezone: string) =>
  signInRoute(new NextRequest("http://localhost/auth/sign-in", { method: "POST", body: new URLSearchParams({ timezone }) }));
const settings = (body: object) => fetchMock.mockImplementation(async () => Response.json(body));
const location = (res: Response) => res.headers.get("location") ?? "";
function expectFailed(res: Response) {
  expect(res.status).toBe(303);
  const u = new URL(location(res));
  expect(u.origin + u.pathname + u.search).toBe("http://localhost/cards?sign_in=failed");
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv("SUPABASE_URL", URL_);
  vi.stubEnv("SUPABASE_PUBLISHABLE_KEY", KEY);
  fetchMock.mockRejectedValue(new TypeError("fetch failed"));
  vi.stubGlobal("fetch", fetchMock);
  use(jar());
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

test("로그인 미설정(URL 또는 키 없음): 확인된 유저 null(throw·Auth 요청 없음), 로그인 시도는 실패 문구로, 쿠키 없음", async () => {
  for (const [name, value] of [
    ["SUPABASE_PUBLISHABLE_KEY", undefined], // 지금 Vercel 상태(URL만 있음)
    ["SUPABASE_PUBLISHABLE_KEY", ""],
    ["SUPABASE_URL", undefined],
  ] as const) {
    vi.stubEnv(name, value);
    use(withFakeSession());
    expect(await getVerifiedUserId()).toBeNull();

    const j = use(jar());
    expectFailed(await signInForm("Asia/Seoul"));
    expect(j.values.size).toBe(0);
    vi.stubEnv("SUPABASE_URL", URL_);
    vi.stubEnv("SUPABASE_PUBLISHABLE_KEY", KEY);
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

test("Google 꺼짐·설정 응답 실패 → 실패 문구로, 검증값 쿠키 없음", async () => {
  for (const respond of [
    async () => Response.json({ external: { google: false } }),
    async () => Response.json({}),
    async () => new Response("bad gateway", { status: 502 }),
    async () => new Response("not json"),
    async () => {
      throw new TypeError("fetch failed");
    },
  ]) {
    fetchMock.mockImplementation(respond);
    const j = use(jar());
    expectFailed(await signInForm("Asia/Seoul"));
    expect(j.values.size).toBe(0);
  }
  expect(fetchMock).toHaveBeenCalledWith(`${URL_}/auth/v1/settings`, expect.objectContaining({ headers: { apikey: KEY } }));
});

test("Google 켜짐 → 303 Supabase authorize(PKCE), 돌아올 주소에 타임존, 검증값 쿠키는 HttpOnly·Secure·Lax, 키 없음", async () => {
  settings({ external: { google: true } });
  const j = use(jar());
  const res = await signInForm("Asia/Seoul");

  expect(res.status).toBe(303);
  const u = new URL(location(res));
  expect(u.origin + u.pathname).toBe(`${URL_}/auth/v1/authorize`);
  expect(u.searchParams.get("provider")).toBe("google");
  expect(u.searchParams.get("code_challenge")).toBeTruthy();
  expect(u.searchParams.get("code_challenge_method")).toBeTruthy();
  expect(u.searchParams.get("redirect_to")).toBe("http://localhost/auth/callback?timezone=Asia%2FSeoul");
  expect(location(res)).not.toContain(KEY);

  const verifiers = [...j.options].filter(([n]) => n.endsWith("-code-verifier"));
  expect(verifiers.length).toBeGreaterThan(0);
  for (const [n, o] of verifiers) expect(o, n).toMatchObject({ httpOnly: true, secure: true, sameSite: "lax", path: "/" });
  expect(sessionCookies(j)).toEqual([]);
});

test("타임존 입력: 64자로 자르고, 없거나 깨진 본문이면 빈 값(→ 콜백에서 America/New_York)", async () => {
  settings({ external: { google: true } });
  const tz = async (res: Response) => new URL(new URL(location(res)).searchParams.get("redirect_to")!).searchParams.get("timezone");
  expect(await tz(await signInForm("x".repeat(100)))).toBe("x".repeat(64));
  expect(await tz(await signInRoute(new NextRequest("http://localhost/auth/sign-in", { method: "POST" })))).toBe("");
  const broken = new NextRequest("http://localhost/auth/sign-in", {
    method: "POST",
    headers: { "content-type": "multipart/form-data; boundary=x" },
    body: "garbage",
  });
  expect(await tz(await signInRoute(broken))).toBe("");
});

test("Auth에 닿지 않음(만료 안 된 세션 쿠키) → null, throw 없음", async () => {
  vi.unstubAllGlobals(); // 진짜 fetch로 닫힌 포트에
  vi.stubEnv("SUPABASE_URL", "http://127.0.0.1:1");
  use(withFakeSession());
  expect(await getVerifiedUserId()).toBeNull();
});

test("콜백 연결: 교환 성공 → 프로필 보장(브라우저 타임존) → 303 /cards. 교환 실패 → 프로필을 부르지 않는다", async () => {
  vi.mocked(exchangeCode).mockResolvedValue("user-1" as VerifiedUserId);
  const ok = await callback(new NextRequest("http://localhost/auth/callback?code=c1&timezone=Asia%2FSeoul"));
  expect(exchangeCode).toHaveBeenCalledWith("c1");
  expect(ensureProfile).toHaveBeenCalledWith("user-1", "Asia/Seoul");
  expect(ok.status).toBe(303);
  expect(location(ok)).toBe("http://localhost/cards");

  await callback(new NextRequest("http://localhost/auth/callback?code=c2"));
  expect(ensureProfile).toHaveBeenLastCalledWith("user-1", "");

  vi.mocked(ensureProfile).mockClear();
  vi.mocked(exchangeCode).mockResolvedValue(null);
  expectFailed(await callback(new NextRequest("http://localhost/auth/callback?code=c3&timezone=Asia%2FSeoul")));
  expect(ensureProfile).not.toHaveBeenCalled();
});

test("프로필 보장 실패 → 세션 쿠키를 지우고(닫힌 쪽) 실패 문구로", async () => {
  vi.mocked(exchangeCode).mockResolvedValue("user-1" as VerifiedUserId);
  vi.mocked(ensureProfile).mockRejectedValue(new Error("user_profile write failed: 08000"));
  const j = use(withFakeSession()); // 교환이 심은 세션 쿠키 자리
  expectFailed(await callback(new NextRequest("http://localhost/auth/callback?code=c&timezone=Asia%2FSeoul")));
  expect(sessionCookies(j)).toEqual([]);
});
