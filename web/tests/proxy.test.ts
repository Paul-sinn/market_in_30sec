/** 배포 보호(#25): 모든 요청 앞 HTTP Basic Auth + 기기당 1년 기억 쿠키. 비밀번호 미설정이면 전부 거부(닫힌 쪽) */
import { hkdfSync } from "node:crypto";

import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import * as mod from "@/proxy";
import { MAX_TRACKED_IPS } from "@/server/rate-limit";

const USER = "canary-owner";
const PASSWORD = "canary-pw:with-colon-ü"; // 콜론·비ASCII가 들어가도 맞아야 한다
const KEY = "canary-publishable-key";

const basic = (s: string) => `Basic ${Buffer.from(s, "utf8").toString("base64")}`;
const call = async (authorization?: string, cookie?: string) =>
  mod.proxy(
    new NextRequest("https://example.test/", {
      headers: { ...(authorization && { authorization }), ...(cookie !== undefined && { cookie: `m30_auth=${cookie}` }) },
    }),
  );
/** Basic 로그인 성공 응답이 심은 쿠키 값(없으면 실패: 쿠키 테스트가 빈 값으로 헛통과하지 않게) */
async function login() {
  const value = (await call(basic(`${USER}:${PASSWORD}`))).headers.get("set-cookie")?.match(/^m30_auth=([^;]*)/)?.[1] ?? "";
  expect(value).not.toBe("");
  return value;
}

beforeEach(() => {
  vi.stubEnv("DASHBOARD_USER", USER);
  vi.stubEnv("DASHBOARD_PASSWORD", PASSWORD);
  // 로그인 env(#37): 닫힌 포트 + canary 키. 세션 갱신이 Auth에 닿으면 안 되는 테스트가 실제로 나가지 않게
  vi.stubEnv("SUPABASE_URL", "http://127.0.0.1:1");
  vi.stubEnv("SUPABASE_PUBLISHABLE_KEY", KEY);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

/** 401 + Basic 요청 헤더, 응답 어디에도 비밀값·환경 변수 이름이 없다 */
async function expectDenied(pending: Response | Promise<Response>) {
  const res = await pending;
  expect(res.status).toBe(401);
  expect(res.headers.get("www-authenticate")).toMatch(/^Basic realm="[^"]+"/);
  expect(res.headers.get("x-middleware-next")).toBeNull();
  expect(res.headers.get("set-cookie")).toBeNull();
  const all = (await res.text()) + JSON.stringify([...res.headers]);
  for (const secret of [PASSWORD, "canary-pw", USER, "DASHBOARD_"]) expect(all).not.toContain(secret);
}

test("인증 헤더 없음 → 401", async () => {
  await expectDenied(call());
});

test("틀린 아이디·틀린 비밀번호 → 401", async () => {
  await expectDenied(call(basic(`${USER}:wrong`)));
  await expectDenied(call(basic(`intruder:${PASSWORD}`)));
  await expectDenied(call(basic(`${USER}:${PASSWORD}x`))); // 앞부분만 맞음
  await expectDenied(call(basic(`${USER}:canary-pw`))); // 콜론 앞까지만
});

test("맞는 값 → 통과(200, 다음 단계로)", async () => {
  const res = await call(basic(`${USER}:${PASSWORD}`));
  expect(res.status).toBe(200);
  expect(res.headers.get("x-middleware-next")).toBe("1");
  expect((await call(`basic ${Buffer.from(`${USER}:${PASSWORD}`).toString("base64")}`)).status).toBe(200); // 스킴은 대소문자 무관(RFC 7617)
});

test("환경 변수 미설정·빈 값 → 헤더가 있어도 401", async () => {
  for (const [name, value] of [
    ["DASHBOARD_PASSWORD", undefined],
    ["DASHBOARD_PASSWORD", ""],
    ["DASHBOARD_USER", undefined],
    ["DASHBOARD_USER", ""],
  ] as const) {
    vi.stubEnv(name, value);
    await expectDenied(call(basic(`${USER}:${PASSWORD}`)));
    await expectDenied(call(basic(name === "DASHBOARD_USER" ? `:${PASSWORD}` : `${USER}:`))); // 빈 값끼리 맞아도 거부
    vi.stubEnv("DASHBOARD_USER", USER);
    vi.stubEnv("DASHBOARD_PASSWORD", PASSWORD);
  }
});

test("형식이 깨진 헤더 → 401", async () => {
  for (const h of [
    "Basic", // 값 없음
    "Basic ", // 빈 값
    "Basic !!!not-base64!!!",
    `Bearer ${Buffer.from(`${USER}:${PASSWORD}`).toString("base64")}`, // 다른 스킴
    basic("owner-no-colon"), // 콜론 없음
    `Basic${Buffer.from(`${USER}:${PASSWORD}`).toString("base64")}`, // 스킴 뒤 공백 없음
    basic(":"),
  ]) {
    await expectDenied(call(h));
  }
});

test("랜딩(/)과 카드 대시보드(/cards), 로그인 라우트(#37), 내 종목 쓰기(#38), 이용약관·개인정보처리방침(#62) 모두 인증 없으면 401(#27)", async () => {
  for (const path of ["/", "/cards", "/cards/", "/auth/sign-in", "/auth/callback?code=x", "/my-stocks", "/terms", "/privacy"]) {
    await expectDenied(mod.proxy(new NextRequest(`https://example.test${path}`)));
    expect((await mod.proxy(new NextRequest(`https://example.test${path}`, { headers: { authorization: basic(`${USER}:${PASSWORD}`) } }))).status).toBe(200);
  }
});

test("matcher로 빠지는 경로 없음(정적 파일·데이터 경로 포함 모든 요청)", () => {
  const config = (mod as { config?: Parameters<typeof unstable_doesMiddlewareMatch>[0]["config"] }).config ?? {};
  for (const url of ["/", "/cards", "/any/page", "/_next/static/chunks/a.js", "/_next/data/x.json", "/favicon.ico", "/api/x", "/auth/sign-in", "/auth/callback?code=x", "/my-stocks"]) {
    expect(unstable_doesMiddlewareMatch({ config, url }), url).toBe(true);
  }
});

test("Basic 성공 → 기억 쿠키를 모든 속성과 함께 심는다", async () => {
  const setCookie = (await call(basic(`${USER}:${PASSWORD}`))).headers.get("set-cookie") ?? "";
  expect(setCookie).toMatch(/^m30_auth=[^;]+;/);
  for (const attr of [/; HttpOnly(;|$)/i, /; Secure(;|$)/i, /; SameSite=Lax(;|$)/i, /; Path=\/(;|$)/i, /; Max-Age=31536000(;|$)/i]) {
    expect(setCookie).toMatch(attr);
  }
});

test("맞는 쿠키 → 인증 헤더 없이 통과, 쿠키를 다시 심지 않는다(만료는 처음 로그인 + 1년 고정)", async () => {
  const cookie = await login();
  // 로그인 뒤 브라우저는 같은 세션에서 Basic 헤더도 계속 보낸다
  for (const res of [await call(undefined, cookie), await call(basic(`${USER}:${PASSWORD}`), cookie), await call(basic(`${USER}:wrong`), cookie)]) {
    expect(res.status).toBe(200);
    expect(res.headers.get("x-middleware-next")).toBe("1");
    expect(res.headers.get("set-cookie")).toBeNull();
  }
});

test("틀린·깨진 쿠키 → 401", async () => {
  const cookie = await login();
  const flipped = cookie.slice(0, -1) + (cookie.endsWith("A") ? "B" : "A");
  for (const bad of ["", "garbage", cookie.slice(0, -1), flipped, `${cookie}x`, PASSWORD]) {
    await expectDenied(call(undefined, bad));
  }
  // 이름이 다른 쿠키는 무시
  await expectDenied(mod.proxy(new NextRequest("https://example.test/", { headers: { cookie: `other=${cookie}` } })));
});

test("비밀번호·아이디를 바꾸면 이전 쿠키 → 401", async () => {
  const old = await login();
  vi.stubEnv("DASHBOARD_PASSWORD", `${PASSWORD}-rotated`);
  await expectDenied(call(undefined, old));
  const fresh = (await call(basic(`${USER}:${PASSWORD}-rotated`))).headers.get("set-cookie")?.match(/^m30_auth=([^;]*)/)?.[1];
  expect(fresh).toBeTruthy();
  expect(fresh).not.toBe(old);
  vi.stubEnv("DASHBOARD_PASSWORD", PASSWORD);
  vi.stubEnv("DASHBOARD_USER", `${USER}-2`);
  await expectDenied(call(undefined, old));
});

test("환경 변수 미설정·빈 값 → 어떤 쿠키가 있어도 401", async () => {
  const cookie = await login();
  // 빈 키로 위조한 쿠키(proxy.ts와 같은 방식): 쿠키 확인이 환경 변수 검사 밖으로 빠지면 통과해 버린다
  const forged = ["", USER].map((u) => Buffer.from(hkdfSync("sha256", "", u, "m30-dashboard-auth", 32)).toString("base64url"));
  for (const [name, value] of [
    ["DASHBOARD_PASSWORD", undefined],
    ["DASHBOARD_PASSWORD", ""],
    ["DASHBOARD_USER", undefined],
    ["DASHBOARD_USER", ""],
  ] as const) {
    vi.stubEnv(name, value);
    for (const c of [cookie, "", "garbage", ...forged]) await expectDenied(call(undefined, c));
    vi.stubEnv("DASHBOARD_USER", USER);
    vi.stubEnv("DASHBOARD_PASSWORD", PASSWORD);
  }
});

test("쿠키에 비밀번호·아이디가 그대로도, 디코딩해도 없다", async () => {
  const setCookie = (await call(basic(`${USER}:${PASSWORD}`))).headers.get("set-cookie") ?? "";
  const value = await login();
  const forms = [setCookie, value, decodeURIComponent(value), Buffer.from(value, "base64").toString("utf8"), Buffer.from(value, "hex").toString("utf8")];
  for (const form of forms) for (const secret of [PASSWORD, "canary-pw", USER, "canary-owner"]) expect(form).not.toContain(secret);
});

// ---- 세션 갱신(#37): 게이트를 통과한 요청에만, 게이트 판단에는 Supabase가 끼지 않는다 ----

/** 만료된 가짜 Supabase 세션 쿠키(갱신하려면 Auth에 가야 한다) */
const expiredSession = () =>
  `sb-127-auth-token=base64-${Buffer.from(
    JSON.stringify({ access_token: "a.b.c", refresh_token: "r", token_type: "bearer", expires_in: 3600, expires_at: 1, user: { id: "u" } }),
  ).toString("base64url")}`;

test("게이트 거부 + 세션 쿠키 → 401, Auth 요청 0회, 세션 Set-Cookie 없음", async () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  for (const cookie of [expiredSession(), `m30_auth=garbage; ${expiredSession()}`]) {
    const res = await mod.proxy(new NextRequest("https://example.test/cards", { headers: { cookie } }));
    expect(JSON.stringify([...res.headers])).not.toContain(KEY);
    await expectDenied(res);
  }
  expect(fetch).not.toHaveBeenCalled();
});

test("게이트 통과 + 세션 쿠키 없음 → 200, Set-Cookie 없음, Auth 요청 0회", async () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  const res = await call(undefined, await login());
  expect(res.status).toBe(200);
  expect(res.headers.get("x-middleware-next")).toBe("1");
  expect(res.headers.get("set-cookie")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

test("정적 파일(/_next/) + 만료된 세션 → 갱신하지 않는다(Auth 요청 0회)", async () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  const cookie = `m30_auth=${await login()}; ${expiredSession()}`;
  const res = await mod.proxy(new NextRequest("https://example.test/_next/static/chunks/x.js", { headers: { cookie } }));
  expect(res.status).toBe(200);
  expect(res.headers.get("set-cookie")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

// ---- 카드 조회 요청 제한(#62): proxy 맨 앞, IP당 고정 1분 창 60번. IP는 테스트마다 다른 TEST-NET 주소 ----

const TOO_MANY = "Too many requests. Try again in a minute.";
const T0 = Date.UTC(2026, 10, 4, 12, 0, 10); // 창 시작 + 10초
const read = (path: string, headers: Record<string, string> = {}) => mod.proxy(new NextRequest(`https://example.test${path}`, { headers }));
/** 같은 IP로 n번 부르고 상태 코드 목록 */
async function burst(n: number, path: string, headers: Record<string, string>) {
  const codes: number[] = [];
  for (let i = 0; i < n; i++) codes.push((await read(path, headers)).status);
  return codes;
}

describe("카드 조회 요청 제한(#62)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(T0);
  });
  afterEach(() => vi.useRealTimers());

  test("카드 조회는 IP당 1분에 60번까지 다음 단계로, 61번째부터 429 + Too many requests 문구 + Retry-After + no-store", async () => {
    const auth = { authorization: basic(`${USER}:${PASSWORD}`), "x-real-ip": "192.0.2.1" };
    expect(await burst(60, "/cards", auth)).toEqual(Array(60).fill(200));
    for (let i = 0; i < 2; i++) {
      const res = await read("/cards", auth);
      expect(res.status).toBe(429);
      expect(await res.text()).toBe(TOO_MANY);
      expect(res.headers.get("retry-after")).toBe("50"); // 창 끝까지 남은 초
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(res.headers.get("content-type")).toBe("text/plain; charset=utf-8");
    }
    vi.setSystemTime(T0 + 49_500); // 창 끝 0.5초 전: 최소 1초
    expect((await read("/cards", auth)).headers.get("retry-after")).toBe("1");
  });

  test("/cards/… 하위 경로도 같이 센다", async () => {
    const ip = { "x-real-ip": "192.0.2.2" };
    await burst(30, "/cards", ip);
    await burst(30, "/cards/", ip);
    expect((await read("/cards/x", ip)).status).toBe(429);
  });

  test("429에는 Set-Cookie·IP·비밀값이 없고 Supabase를 부르지 않는다(fetch 0회, 게이트 통과 쿠키가 있어도)", async () => {
    const cookie = `m30_auth=${await login()}; ${expiredSession()}`;
    const fetch = vi.spyOn(globalThis, "fetch");
    const headers = { cookie, "x-real-ip": "192.0.2.3", authorization: basic(`${USER}:${PASSWORD}`) };
    for (let i = 0; i < 60; i++) await read("/cards", { "x-real-ip": "192.0.2.3" }); // 쿠키 없이 한도를 채운다(401)
    const res = await read("/cards", headers);
    expect(res.status).toBe(429);
    expect(res.headers.get("set-cookie")).toBeNull();
    const all = (await res.text()) + JSON.stringify([...res.headers]);
    for (const secret of ["192.0.2.3", PASSWORD, "canary-pw", USER, KEY, "DASHBOARD_"]) expect(all).not.toContain(secret);
    expect(fetch).not.toHaveBeenCalled();
  });

  test("다른 IP는 따로 센다(x-real-ip, 없으면 x-forwarded-for 첫 값)", async () => {
    await burst(60, "/cards", { "x-real-ip": "192.0.2.4" });
    expect((await read("/cards", { "x-real-ip": "192.0.2.4" })).status).toBe(429);
    expect((await read("/cards", { "x-real-ip": "192.0.2.5" })).status).toBe(401); // 다른 IP: 게이트로
    // x-real-ip가 없으면 x-forwarded-for의 첫 값. 뒤 값(프록시)이 같아도 첫 값이 다르면 따로
    await burst(60, "/cards", { "x-forwarded-for": "198.51.100.1, 10.0.0.1" });
    expect((await read("/cards", { "x-forwarded-for": "198.51.100.1" })).status).toBe(429);
    expect((await read("/cards", { "x-forwarded-for": "198.51.100.2, 10.0.0.1" })).status).toBe(401);
    // x-real-ip가 있으면 x-forwarded-for는 보지 않는다
    expect((await read("/cards", { "x-real-ip": "192.0.2.6", "x-forwarded-for": "198.51.100.1" })).status).toBe(401);
  });

  test("다음 창(1분 뒤)이면 다시 통과", async () => {
    const ip = { "x-real-ip": "192.0.2.7" };
    await burst(60, "/cards", ip);
    expect((await read("/cards", ip)).status).toBe(429);
    vi.setSystemTime(T0 + 50_000); // 다음 창 시작
    expect(await burst(60, "/cards", ip)).toEqual(Array(60).fill(401));
    expect((await read("/cards", ip)).status).toBe(429);
  });

  test("카드 조회가 아닌 경로(/, /terms, /privacy, /auth/sign-in, /my-stocks, /_next/static/…, /cardsx)는 세지 않는다", async () => {
    const ip = { "x-real-ip": "192.0.2.8" };
    for (const path of ["/", "/terms", "/privacy", "/auth/sign-in", "/my-stocks", "/_next/static/chunks/a.js", "/cardsx"]) {
      expect(await burst(70, path, ip), path).toEqual(Array(70).fill(401));
    }
    expect((await read("/cards", ip)).status).toBe(401); // 위 요청이 카드 조회 한도를 쓰지 않았다
  });

  test("한도 안의 요청은 배포 보호를 그대로 거친다(인증 없으면 401, 맞으면 200)", async () => {
    await expectDenied(read("/cards", { "x-real-ip": "192.0.2.9" }));
    expect((await read("/cards", { "x-real-ip": "192.0.2.9", authorization: basic(`${USER}:${PASSWORD}`) })).status).toBe(200);
  });

  test("추적 IP가 상한에 차면 새 IP는 세지 않고 통과(열린 쪽), 이미 센 IP는 계속 센다", async () => {
    vi.setSystemTime(T0 + 60_000); // 빈 창에서 시작
    const ip = (i: number) => ({ "x-real-ip": `10.${(i >> 16) & 255}.${(i >> 8) & 255}.${i & 255}` });
    await burst(60, "/cards", ip(0)); // 한도를 채운 IP 하나
    for (let i = 1; i < MAX_TRACKED_IPS; i++) await read("/cards", ip(i));
    const fresh = ip(MAX_TRACKED_IPS + 1);
    expect(await burst(61, "/cards", fresh)).toEqual(Array(61).fill(401)); // 세지 않음
    expect((await read("/cards", ip(0))).status).toBe(429);
  });
});
