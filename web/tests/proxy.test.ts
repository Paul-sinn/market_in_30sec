/** 배포 보호(#25): 모든 요청 앞 HTTP Basic Auth. 비밀번호 미설정이면 전부 거부(닫힌 쪽) */
import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import * as mod from "@/proxy";

const USER = "owner";
const PASSWORD = "canary-pw:with-colon-ü"; // 콜론·비ASCII가 들어가도 맞아야 한다

const basic = (s: string) => `Basic ${Buffer.from(s, "utf8").toString("base64")}`;
const call = (authorization?: string) =>
  mod.proxy(new NextRequest("https://example.test/", { headers: authorization ? { authorization } : {} }));

beforeEach(() => {
  vi.stubEnv("DASHBOARD_USER", USER);
  vi.stubEnv("DASHBOARD_PASSWORD", PASSWORD);
});
afterEach(() => vi.unstubAllEnvs());

/** 401 + Basic 요청 헤더, 응답 어디에도 비밀값·환경 변수 이름이 없다 */
async function expectDenied(res: Response) {
  expect(res.status).toBe(401);
  expect(res.headers.get("www-authenticate")).toMatch(/^Basic realm="[^"]+"/);
  expect(res.headers.get("x-middleware-next")).toBeNull();
  const all = (await res.text()) + JSON.stringify([...res.headers]);
  for (const secret of [PASSWORD, "canary-pw", "DASHBOARD_"]) expect(all).not.toContain(secret);
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

test("맞는 값 → 통과(200, 다음 단계로)", () => {
  const res = call(basic(`${USER}:${PASSWORD}`));
  expect(res.status).toBe(200);
  expect(res.headers.get("x-middleware-next")).toBe("1");
  expect(call(`basic ${Buffer.from(`${USER}:${PASSWORD}`).toString("base64")}`).status).toBe(200); // 스킴은 대소문자 무관(RFC 7617)
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

test("matcher로 빠지는 경로 없음(정적 파일·데이터 경로 포함 모든 요청)", () => {
  const config = (mod as { config?: Parameters<typeof unstable_doesMiddlewareMatch>[0]["config"] }).config ?? {};
  for (const url of ["/", "/any/page", "/_next/static/chunks/a.js", "/_next/data/x.json", "/favicon.ico", "/api/x"]) {
    expect(unstable_doesMiddlewareMatch({ config, url }), url).toBe(true);
  }
});
