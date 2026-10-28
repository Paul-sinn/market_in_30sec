import { NextResponse, type NextRequest } from "next/server";

import { startGoogleSignIn } from "@/server/auth";

/** 로그인 시작(POST만: GET은 405라 프리페치·크롤러가 건드려도 아무 일 없다). 돌아갈 곳은 고정 경로뿐(열린 리디렉션 없음) */
export async function POST(request: NextRequest) {
  const form = await request.formData().catch(() => null);
  // 검증은 DB(pg_timezone_names)가 한다. 여기서는 길이만 자른다
  const timezone = String(form?.get("timezone") ?? "").slice(0, 64);
  const url = await startGoogleSignIn(request.nextUrl.origin, timezone);
  return NextResponse.redirect(url ?? new URL("/cards?sign_in=failed", request.url), 303);
}
