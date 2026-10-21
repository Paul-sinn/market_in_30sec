// 브라우저 번들 노출 검사(web-conventions 3절): 가짜 canary 키로 빌드하고 .next/static에서
// canary와 DB 클라이언트 흔적(supabase-js|postgrest)을 찾는다. 0건이 아니면 exit 1. 값·내용은 출력하지 않는다.
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const canary = `canary-${randomUUID()}`;
const build = spawnSync("npx", ["next", "build"], {
  stdio: "inherit",
  env: { ...process.env, SUPABASE_URL: "http://127.0.0.1:54321", SUPABASE_SERVICE_ROLE_KEY: canary },
});
if (build.status !== 0) process.exit(build.status ?? 1);

const dir = join(import.meta.dirname, "..", ".next", "static");
const files = readdirSync(dir, { recursive: true, withFileTypes: true })
  .filter((d) => d.isFile())
  .map((d) => readFileSync(join(d.parentPath, d.name), "utf8"));
const hits = {
  canary: files.filter((f) => f.includes(canary)).length,
  "supabase-js|postgrest": files.filter((f) => /supabase-js|postgrest/.test(f)).length,
};
console.log(`bundle check: ${files.length} files in .next/static,`, Object.entries(hits).map(([k, v]) => `${k}=${v}`).join(", "));
process.exit(Object.values(hits).some((n) => n > 0) ? 1 : 0);
