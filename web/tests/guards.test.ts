/** 소스 규칙 검사(web-conventions 1절): 비밀값 접두사, 쓰기는 my-stocks·waitlist만, server-only, 테마 토큰만 */
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

test("DB 쓰기 호출은 src/server/my-stocks.ts(내 종목, #37)와 src/server/waitlist.ts(탭 합계·대기 등록, #69) 두 곳", () => {
  const write = /\.(insert|update|upsert|delete|rpc)\(/;
  expect(files.filter((f) => write.test(f.code)).map((f) => f.path).sort()).toEqual([join("server", "my-stocks.ts"), join("server", "waitlist.ts")].sort());
});

test("PostgREST 글자 필터(ilike·like·textSearch·or) 호출 없음: 고르기 검색어는 서버 메모리에서만 비교한다(#58 D10)", () => {
  expect(files.filter((f) => /\.(i?like|textSearch|or)\(/.test(f.code)).map((f) => f.path)).toEqual([]);
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

test("키보드 포커스 링: 모든 링크·버튼·펼침(summary, #38)·입력칸(input, #58)에 2px 외곽선, 지우는 클래스 없음(#27 qa N4)", () => {
  const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");
  expect(css).toMatch(/:where\(a, button, summary, input\):focus-visible \{\s*outline: 2px solid var\(--color-foreground\);\s*outline-offset: 2px;\s*\}/);
  expect(files.filter((f) => /\boutline-(none|hidden|0)\b/.test(f.code)).map((f) => f.path)).toEqual([]);
});

test("랜딩(/)과 법률 페이지(/terms, /privacy)는 DB를 읽지 않는다(정적 페이지, 카드 읽기는 /cards만, #62)", () => {
  const legal = join("app", "(legal)");
  const pages = files.filter((f) => f.path === join("app", "page.tsx") || f.path.startsWith(legal));
  expect(pages.map((f) => f.path)).toEqual(expect.arrayContaining([join("app", "page.tsx"), join(legal, "terms", "page.tsx"), join(legal, "privacy", "page.tsx")]));
  for (const f of pages) expect(f.code, f.path).not.toMatch(/@\/server|connection\(/);
});

test("<html>을 그리는 레이아웃은 app/layout.tsx 하나(모든 페이지가 하단 고지를 받는다, #62)", () => {
  expect(files.filter((f) => /<html\b/.test(f.code)).map((f) => f.path)).toEqual([join("app", "layout.tsx")]);
});

// ---- 카드 조회 캐시(#62): 로그인 유저 데이터가 공용 캐시에 섞이지 않게 ----

test('"use cache"는 src/server/card-cache.ts 한 곳, 인자 없는 getDashboardCached()만, 그 파일은 유저·요청 값을 읽지 않는다', () => {
  expect(files.filter((f) => /["']use cache/.test(f.code)).map((f) => f.path)).toEqual([join("server", "card-cache.ts")]);
  const cache = files.find((f) => f.path === join("server", "card-cache.ts"))!.code;
  expect(cache.match(/["']use cache/g)).toHaveLength(1);
  expect(cache).toMatch(/export async function getDashboardCached\(\)[^{]*\{\s*["']use cache: remote["'];/);
  expect(cache.match(/\bfunction\b/g)).toHaveLength(1); // 캐시 함수 하나
  expect(cache).not.toMatch(/next\/headers|cookies\(|headers\(|searchParams|from ["'](\.\/|@\/server\/)(auth|my-stocks|exposure)["']/);
});

test("/cards 페이지는 getDashboardCached를 부르고 getDashboard를 직접 부르지 않는다", () => {
  const page = files.find((f) => f.path === join("app", "cards", "page.tsx"))!.code;
  expect(page).toMatch(/getDashboardCached\(\)/);
  expect(page).not.toMatch(/\bgetDashboard\(/);
  // 캐시 래퍼를 부르는 곳은 /cards 페이지뿐
  expect(files.filter((f) => /getDashboardCached\(\)/.test(f.code) && !f.path.startsWith("server")).map((f) => f.path)).toEqual([join("app", "cards", "page.tsx")]);
});

test("공유 캐시 헤더(s-maxage, Cache-Control public) 없음: /cards는 로그인 유저마다 다르다", () => {
  const config = readFileSync(join(SRC, "..", "next.config.ts"), "utf8");
  const shared = /s-maxage|stale-while-revalidate|\bpublic\s*,\s*max-age|["']public["']/i;
  expect([...files, { path: "next.config.ts", code: config }].filter((f) => shared.test(f.code)).map((f) => f.path)).toEqual([]);
});

// ---- 이용약관·개인정보처리방침(#62) ----

test("자리표시(PAUL_TODO) 0건", () => {
  expect(files.filter((f) => f.code.includes("PAUL_TODO")).map((f) => f.path)).toEqual([]);
});

test("연락 이메일은 법률 페이지(app/(legal)/) 밖에 쓰지 않는다(사용자 결정 2026-11-04)", () => {
  const email = /[\w.+-]+@(?!example\.test)[\w-]+\.[\w.]+/; // 테스트 유저 도메인 example.test 제외
  expect(files.filter((f) => email.test(f.code) && !f.path.startsWith(join("app", "(legal)"))).map((f) => f.path)).toEqual([]);
});

// ---- 잠긴 자리·대기 등록(#69) ----

test("/plus 페이지는 공용 카드 캐시를 쓰지 않는다(등록 여부는 유저 값이라 요청마다)", () => {
  const plus = files.filter((f) => f.path.startsWith(join("app", "plus")));
  expect(plus.map((f) => f.path)).toContain(join("app", "plus", "page.tsx"));
  for (const f of plus) expect(f.code, f.path).not.toMatch(/getDashboard|card-cache|["']use cache/);
});

test("대기 등록에 이메일 입력칸이 없다(로그인 계정 이메일만 쓴다, #69)", () => {
  expect(files.filter((f) => /type=["']email["']|name=["']email["']/.test(f.code)).map((f) => f.path)).toEqual([]);
});
