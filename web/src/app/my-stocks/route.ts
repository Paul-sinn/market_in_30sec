import { NextResponse, type NextRequest } from "next/server";

import { getVerifiedUserId } from "@/server/auth";
import { addMyStock, removeMyStock } from "@/server/my-stocks";

/** 내 종목 넣기·빼기(POST만, #38). 유저는 세션으로만 안다(본문의 유저 id는 읽지 않는다). 교차 사이트 POST에는
 *  SameSite=Lax 세션 쿠키가 붙지 않아 로그인 전과 같다. 규칙은 DB가 지키고 결과 코드만 고정 경로 /cards로 넘긴다 */
export async function POST(request: NextRequest) {
  const back = (result: string) => NextResponse.redirect(new URL(result === "ok" ? "/cards" : `/cards?my_stock=${result}`, request.url), 303);
  const userId = await getVerifiedUserId();
  if (!userId) return back("ok"); // 세션 없음·만료 → 로그인 전 화면
  const form = await request.formData().catch(() => null);
  const change = form?.get("change");
  const write = change === "add" ? addMyStock : change === "remove" ? removeMyStock : null;
  if (!write) return back("failed");
  try {
    return back(await write(userId, String(form?.get("ticker") ?? "")));
  } catch (e) {
    // 고정 이유 + DB 코드만(티커·유저 값 없음)
    console.warn(`my_stock: reason=write_failed code=${e instanceof Error && typeof e.cause === "string" ? e.cause : "unknown"}`);
    return back("failed");
  }
}
