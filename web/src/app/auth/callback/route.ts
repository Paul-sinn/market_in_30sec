import { NextResponse, type NextRequest } from "next/server";

import { exchangeCode, signOut } from "@/server/auth";
import { ensureProfile } from "@/server/my-stocks";

/** Google → Supabase → 여기(최상위 GET이라 m30_auth·검증값 쿠키가 따라온다). 돌아갈 곳은 고정 경로뿐 */
export async function GET(request: NextRequest) {
  const back = (path: string) => NextResponse.redirect(new URL(path, request.url), 303);
  const query = request.nextUrl.searchParams;
  const code = query.get("code");
  if (!code) {
    console.warn("auth: reason=no_code"); // 공급자 오류(?error=…)·취소 포함
    return back("/cards?sign_in=failed");
  }
  const userId = await exchangeCode(code);
  if (!userId) return back("/cards?sign_in=failed");
  try {
    await ensureProfile(userId, (query.get("timezone") ?? "").slice(0, 64));
  } catch {
    // 닫힌 쪽: "로그인됨이면 프로필이 있다"가 늘 성립하게 세션을 지운다
    console.warn("auth: reason=profile_failed");
    await signOut();
    return back("/cards?sign_in=failed");
  }
  return back("/cards");
}
