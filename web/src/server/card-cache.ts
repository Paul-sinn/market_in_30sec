import "server-only";

import { cacheLife } from "next/cache";

import { getDashboard } from "./cards";

/** 카드 조회 캐시(HANDOFF 3-7, #62). 공용 데이터만: 인자·쿠키·헤더·유저 읽기 없음(캐시 키에 유저 값이 들어갈 길이 없다).
 *  노출 판단(exposeCards)·내 종목은 캐시 밖에서 요청마다. 테스트는 getDashboard를 직접 부른다(cacheLife는 Next 밖에서 throw) */
export async function getDashboardCached(): ReturnType<typeof getDashboard> {
  "use cache: remote";
  cacheLife("minutes"); // 1분 뒤 다시 읽기, 최대 1시간. 발행·재발행·발행 중단이 약 1분 안에 보인다. 재배포하면 키가 바뀐다
  return getDashboard();
}
