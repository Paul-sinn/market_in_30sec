import "server-only";

import type { NextRequest } from "next/server";

import { TOO_MANY_REQUESTS } from "@/lib/copy";

// shortcut: 인스턴스 메모리라 Vercel 인스턴스마다 따로 센다(실제 한도 = 인스턴스 수 × CARD_READ_LIMIT, 새 인스턴스는 0부터). IPv6는 주소마다 따로(/64 묶음 없음). 남용이 보이면 Vercel 방화벽 요청 제한 규칙을 더한다(코드 변경 없음)
export const CARD_READ_LIMIT = 60; // IP당 창 하나
export const CARD_READ_WINDOW_MS = 60_000; // 모두 같은 고정 창
export const MAX_TRACKED_IPS = 10_000; // 차면 새 IP는 세지 않고 통과(가용성은 열린 쪽, HANDOFF 3-10)

const counts = new Map<string, number>();
let windowIndex = -1; // 지금 세는 창 번호

/** 카드 조회(/cards, /cards/…)와 잠긴 자리 설명 화면·탭·대기 등록(/plus, /waitlist, #69: 로그인 없는 쓰기)만 같은 창에서 센다. 한도 안이면 null, 넘으면 429(TOO_MANY_REQUESTS, Retry-After, no-store).
 *  IP = x-real-ip → x-forwarded-for 첫 값 → "unknown"(로컬). 두 헤더는 Vercel이 덮어쓴다(배포처는 Vercel 하나).
 *  창이 바뀌면 표를 비운다. IP는 응답·로그에 남기지 않는다(초과 로그도 없음: 몰릴 때 넘친다) */
export function limitCardRead(request: NextRequest): Response | null {
  const path = request.nextUrl.pathname; // proxy는 RSC·프리페치 요청도 페이지 경로로 받는다(.rsc 정규화)
  if (path !== "/cards" && !path.startsWith("/cards/") && path !== "/plus" && path !== "/waitlist") return null;

  const now = Date.now();
  const current = Math.floor(now / CARD_READ_WINDOW_MS);
  if (current !== windowIndex) {
    counts.clear();
    windowIndex = current;
  }
  const ip = request.headers.get("x-real-ip") || request.headers.get("x-forwarded-for")?.split(",")[0].trim() || "unknown";
  const seen = counts.get(ip);
  if (seen === undefined && counts.size >= MAX_TRACKED_IPS) return null;
  counts.set(ip, (seen ?? 0) + 1);
  if ((seen ?? 0) < CARD_READ_LIMIT) return null;

  const retryAfter = Math.max(1, Math.ceil(((current + 1) * CARD_READ_WINDOW_MS - now) / 1000));
  return new Response(TOO_MANY_REQUESTS, {
    status: 429,
    headers: { "Retry-After": String(retryAfter), "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" },
  });
}
