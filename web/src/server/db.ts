import "server-only";

import { createClient } from "@supabase/supabase-js";

/** 서비스 역할 클라이언트(ADR-0003: DB는 웹 서버만). 카드 읽기는 cards.ts, 쓰기는 my-stocks.ts(내 종목)·waitlist.ts(탭 합계·대기 등록, #69)만 */
export function db() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see web/README.md)");
  return createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
}
