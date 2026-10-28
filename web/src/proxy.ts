/**
 * 배포 보호(#25): 모든 요청 앞의 HTTP Basic Auth. matcher가 없어 정적 파일까지 전부 거친다.
 * Basic 성공 때 1년짜리 쿠키를 심어 기기당 한 번만 로그인한다(사용자 결정 2026-10-28).
 * DASHBOARD_USER·DASHBOARD_PASSWORD 중 하나라도 비면 쿠키가 있어도 전부 거부한다(닫힌 쪽).
 * 통과한 요청만 로그인 세션을 갱신한다(#37). 게이트 판단에는 Supabase가 끼지 않고, 401 경로는 Supabase를 부르지 않는다.
 */
import { hash, hkdfSync, timingSafeEqual } from "node:crypto";
import type { NextRequest } from "next/server";

import { APP_NAME, AUTH_REQUIRED } from "@/lib/copy";
import { refreshSession } from "@/server/auth";

// 해시로 길이를 맞춰야 timingSafeEqual을 쓸 수 있고, 길이 차이로 새는 정보도 없앤다
const same = (a: string, b: string) => timingSafeEqual(hash("sha256", a, "buffer"), hash("sha256", b, "buffer"));

const COOKIE = "m30_auth";
// 새 비밀값 없이 비밀번호에서 만든다(HKDF = HMAC-SHA256 두 번): 비밀번호를 바꾸면 모든 쿠키가 무효, 쿠키에서 아이디·비밀번호를 되돌릴 수 없다.
// 아이디는 salt 자리(info는 1024바이트 제한). createHmac 체이닝은 DB 쓰기 검사(guards.test의 update 호출)에 걸려 한 번에 계산한다
const token = (user: string, password: string) => Buffer.from(hkdfSync("sha256", password, user, "m30-dashboard-auth", 32)).toString("base64url");

export async function proxy(request: NextRequest): Promise<Response> {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  const [, encoded] = request.headers.get("authorization")?.match(/^Basic (\S+)$/i) ?? [];
  const decoded = encoded ? Buffer.from(encoded, "base64").toString("utf8") : "";
  const colon = decoded.indexOf(":"); // 아이디에는 콜론이 없고 비밀번호에는 있을 수 있다(RFC 7617)

  if (user && password) {
    // 쿠키를 먼저 본다: 로그인 뒤 브라우저가 Basic 헤더를 계속 보내도 쿠키를 다시 심지 않는다(만료는 처음 로그인 + 1년)
    if (same(request.cookies.get(COOKIE)?.value ?? "", token(user, password))) return refreshSession(request);
    // 비트 AND: 아이디가 틀려도 비밀번호 비교를 건너뛰지 않는다
    if (colon >= 0 && (+same(decoded.slice(0, colon), user) & +same(decoded.slice(colon + 1), password))) {
      const res = await refreshSession(request);
      res.cookies.set(COOKIE, token(user, password), { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 31536000 });
      return res;
    }
  }
  return new Response(AUTH_REQUIRED, {
    status: 401,
    headers: { "WWW-Authenticate": `Basic realm="${APP_NAME}", charset="UTF-8"`, "Cache-Control": "no-store" },
  });
}
