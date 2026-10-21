/**
 * 배포 보호(#25): 모든 요청 앞의 HTTP Basic Auth. matcher가 없어 정적 파일까지 전부 거친다.
 * DASHBOARD_USER·DASHBOARD_PASSWORD 중 하나라도 비면 전부 거부한다(닫힌 쪽).
 */
import { hash, timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";

import { APP_NAME, AUTH_REQUIRED } from "@/lib/copy";

// 해시로 길이를 맞춰야 timingSafeEqual을 쓸 수 있고, 길이 차이로 새는 정보도 없앤다
const same = (a: string, b: string) => timingSafeEqual(hash("sha256", a, "buffer"), hash("sha256", b, "buffer"));

export function proxy(request: NextRequest) {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  const [, encoded] = request.headers.get("authorization")?.match(/^Basic (\S+)$/i) ?? [];
  const decoded = encoded ? Buffer.from(encoded, "base64").toString("utf8") : "";
  const colon = decoded.indexOf(":"); // 아이디에는 콜론이 없고 비밀번호에는 있을 수 있다(RFC 7617)

  if (user && password && colon >= 0) {
    // 비트 AND: 아이디가 틀려도 비밀번호 비교를 건너뛰지 않는다
    if (+same(decoded.slice(0, colon), user) & +same(decoded.slice(colon + 1), password)) return NextResponse.next();
  }
  return new Response(AUTH_REQUIRED, {
    status: 401,
    headers: { "WWW-Authenticate": `Basic realm="${APP_NAME}", charset="UTF-8"`, "Cache-Control": "no-store" },
  });
}
