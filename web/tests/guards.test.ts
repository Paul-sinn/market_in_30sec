/** 소스 규칙 검사(web-conventions 1절): 비밀값 접두사, 읽기 전용, server-only, 테마 토큰만 */
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

test("DB 쓰기 호출 없음(select만)", () => {
  const write = /\.(insert|update|upsert|delete|rpc)\(/;
  expect(files.filter((f) => write.test(f.code)).map((f) => f.path)).toEqual([]);
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

test("등락률 토큰: up은 초록, down은 빨강(라이트·다크 모두)", () => {
  const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");
  const rgb = (name: string) =>
    [...css.matchAll(new RegExp(`--${name}: #([0-9a-f]{6});`, "gi"))].map((m) => m[1].match(/../g)!.map((h) => parseInt(h, 16)));
  expect(css).toContain("--color-up: var(--up);");
  expect(css).toContain("--color-down: var(--down);");
  expect(rgb("up")).toHaveLength(2);
  expect(rgb("down")).toHaveLength(2);
  for (const [r, g, b] of rgb("up")) expect(g > r && g > b).toBe(true);
  for (const [r, g, b] of rgb("down")) expect(r > g && r > b).toBe(true);
});
