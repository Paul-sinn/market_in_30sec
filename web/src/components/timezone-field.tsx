"use client";

import { useSyncExternalStore } from "react";

const noSubscribe = () => () => {};

/** 로그인 폼의 숨은 타임존 칸. 서버 렌더는 반드시 ""(서버 타임존이 박히면 하이드레이션이 고치지 않는다), 브라우저가 채운다.
 *  JS가 없으면 빈 값 → 프로필은 America/New_York */
export function TimezoneField() {
  const tz = useSyncExternalStore(noSubscribe, () => Intl.DateTimeFormat().resolvedOptions().timeZone, () => "");
  return <input type="hidden" name="timezone" value={tz} />;
}
