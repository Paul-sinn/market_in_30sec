import { NextResponse, type NextRequest } from "next/server";

import { signOut } from "@/server/auth";

/** 로그아웃(POST만). 세션 쿠키를 지우고 언제나 /cards로 */
export async function POST(request: NextRequest) {
  await signOut();
  return NextResponse.redirect(new URL("/cards", request.url), 303);
}
