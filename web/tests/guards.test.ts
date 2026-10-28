/** 소스 규칙 검사(web-conventions 1절): 비밀값 접두사, 쓰기는 my-stocks만, server-only, 테마 토큰만 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

const SRC = join(__dirname, "..", "src");
const files = (readdirSync(SRC, { recursive: true }) as string[])
  .filter((f) => /\.(ts|tsx)$/.test(f))
  .map((f) => ({ path: f, code: readFileSync(join(SRC, f), "utf8") }));

test("NEXT_PUBLIC_ 환경 변수 없음", () => {
  expect(files.filter((f) => f.code.includes("NEXT_PUBLIC_")).map((f) => f.path)).toEqual([]);
});

test("DB 쓰기 호출은 src/server/my-stocks.ts 한 곳(#37)", () => {
  const write = /\.(insert|update|upsert|delete|rpc)\(/;
  expect(files.filter((f) => write.test(f.code)).map((f) => f.path)).toEqual([join("server", "my-stocks.ts")]);
});

test("이메일·비밀번호·OTP 로그인 호출 없음(HANDOFF 3-7, 테스트 도우미에만 있다)", () => {
  const email = /\b(signInWithPassword|signInWithOtp|signUp|verifyOtp|signInAnonymously|resetPasswordForEmail)\b/;
  expect(files.filter((f) => email.test(f.code)).map((f) => f.path)).toEqual([]);
});

test("Supabase 패키지는 src/server/에서만 import, 브라우저 클라이언트 없음(ADR-0003, #37)", () => {
  const supabase = /from ["']@supabase\//;
  expect(files.filter((f) => supabase.test(f.code) && !f.path.startsWith("server")).map((f) => f.path)).toEqual([]);
  expect(files.filter((f) => f.code.includes("createBrowserClient")).map((f) => f.path)).toEqual([]);
});

test("src/server/ 모듈은 첫 줄이 server-only", () => {
  const server = files.filter((f) => f.path.startsWith("server"));
  expect(server.length).toBeGreaterThan(0);
  for (const f of server) expect(f.code.startsWith('import "server-only";'), f.path).toBe(true);
});

test("컴포넌트·라우트에 hex 색·임의 값 클래스 없음(테마 토큰만)", () => {
  const ui = files.filter((f) => f.path.endsWith(".tsx"));
  const raw = /#[0-9a-fA-F]{3,8}\b|\b[\w:-]+-\[[^\]]+\]/;
  expect(ui.filter((f) => raw.test(f.code)).map((f) => f.path)).toEqual([]);
});

test('"use client" 파일은 서버 모듈을 import하지 않는다', () => {
  const client = files.filter((f) => /^["']use client["']/.test(f.code));
  expect(client.filter((f) => /from ["']@\/server/.test(f.code)).map((f) => f.path)).toEqual([]);
});

test("등락률 토큰: up은 초록, down은 빨강(어두운 테마 하나, #27)", () => {
  const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");
  const rgb = (name: string) =>
    [...css.matchAll(new RegExp(`--color-${name}: #([0-9a-f]{6});`, "gi"))].map((m) => m[1].match(/../g)!.map((h) => parseInt(h, 16)));
  expect(rgb("up")).toHaveLength(1);
  expect(rgb("down")).toHaveLength(1);
  for (const [r, g, b] of rgb("up")) expect(g > r && g > b).toBe(true);
  for (const [r, g, b] of rgb("down")) expect(r > g && r > b).toBe(true);
});

test("키보드 포커스 링: 모든 링크·버튼에 2px 외곽선, 지우는 클래스 없음(#27 qa N4)", () => {
  const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");
  expect(css).toMatch(/:where\(a, button\):focus-visible \{\s*outline: 2px solid var\(--color-foreground\);\s*outline-offset: 2px;\s*\}/);
  expect(files.filter((f) => /\boutline-(none|hidden|0)\b/.test(f.code)).map((f) => f.path)).toEqual([]);
});

test("랜딩(/)은 DB를 읽지 않는다(정적 페이지, 카드 읽기는 /cards만)", () => {
  const landing = files.find((f) => f.path === join("app", "page.tsx"));
  expect(landing).toBeDefined();
  expect(landing!.code).not.toMatch(/@\/server|connection\(/);
});
