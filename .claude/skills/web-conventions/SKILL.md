---
name: web-conventions
description: "30초 종목 리포트 웹 SaaS(web/, Next.js App Router)의 구현 규칙. 카드 대시보드·웹 화면·서버 전용 데이터 읽기·Vercel 배포 설정을 작성·수정·리뷰할 때 사용한다. 파이프라인·DB 스키마는 backend-conventions, 문장 내용은 card-copy-rules를 쓴다."
---

# 웹 구현 규칙

스택: Next.js(App Router) + TypeScript + Tailwind CSS, npm. 배포 Vercel. 근거: HANDOFF 3-3, 3-7, 3-10, 7장(2026-10-20 웹 먼저), ADR-0003.

## 1. 꼭 지킬 규칙과 이유

| 규칙 | 이유 |
| --- | --- |
| DB는 서버 전용 모듈(`web/src/server/`, 첫 줄 `import "server-only"`)에서만 읽는다. `@supabase/supabase-js`를 `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`로 만든다. 클라이언트 컴포넌트(`"use client"`)는 이 모듈과 비밀 환경 변수를 import하지 않는다 | ADR-0003: 브라우저에 키가 가면 서버의 노출 판단을 우회한다. `server-only`가 실수를 빌드 에러로 바꾼다 |
| 비밀 환경 변수에 `NEXT_PUBLIC_` 접두사를 붙이지 않는다. `.env*` 파일을 만들거나 읽지 않는다. 로컬 값은 셸 export(`web/README.md`) | `NEXT_PUBLIC_` 값은 브라우저 번들에 그대로 들어간다 |
| 웹은 DB에 쓰지 않는다(select만) | 카드는 파이프라인만 쓴다. 쓰기 경로가 둘이면 검수(#7)를 건너뛴 문장이 생긴다 |
| 줄 문구는 DB의 `*_text`를 그대로 그린다. 웹이 문장을 만들거나 고치지 않는다. `*_status`는 표시 방식(아이콘·색·흐림)에만 쓴다 | 문구 규칙·검수는 서버 한 곳(card-copy-rules). 웹이 만든 문장은 검사를 거치지 않는다 |
| DB에 문구가 없는 화면 상태(등락률 지연·미지원, 축소판, 카드 없음, 휴장일)는 고정 문구표 한 곳(`web/src/lib/copy.ts`)에 둔다. GLOSSARY·HANDOFF 3-3에 있는 문구(`Update delayed`, `Not covered yet`, `Market closed today` 등)를 그대로 쓰고, 없는 문구를 새로 만들면 보고에 적어 copy-reviewer 검수를 받는다 | 같은 상태가 화면마다 다른 말로 나오지 않게 한다 |
| 등락률: DB 값(소수 첫째 자리)을 다시 계산하지 않고 형식만 입힌다. `+1.2%` / 진짜 마이너스 `−1.2%`(U+2212) / 보합 `0.0%`. 상승 초록·하락 빨강·보합 중립색, 색만으로 구분하지 않게 부호를 항상 붙인다 | HANDOFF 3-3, 접근성(색만으로 의미 전달 금지) |
| 카드 하단에 확인 시각·출처 범위: `Checked 7:30 AM ET · SEC filings` (`checked_at`을 America/New_York으로, `source_scope` 그대로). 확인된 줄(checked_found·checked_none)만 넣고 시각은 그중 가장 이른 것, 확인된 줄이 없으면 하단을 그리지 않는다 | HANDOFF 3-3: 확인한 범위를 드러낸다. 실패한 출처가 "Checked"로 읽히면 안 된다(#24) |
| 등락률 옆 라벨은 종가 날짜 `Thu 10/15 close`(DB `stock_card.previous_trading_day`를 포맷, 웹은 달력을 계산하지 않음, #16). 값이 없는 옛 카드와 랜딩 샘플은 `prev close`(사용자 시안, #27). 발행 중단(`publish_suspended`) 카드는 `exposeCards` 한 곳에서 뺀다. DB 읽기 실패는 `src/app/cards/error.tsx`의 `Cards could not be loaded` + `Try again`, 에러 내용은 화면에 그리지 않는다 | 등락률은 직전 거래일 기준이라 카드 날짜와 다르다. 실패를 "카드 없음"으로 보이지 않게(#24) |
| 시장 한눈에(`market_glance`)는 줄 컬럼 12개만 select하고 `market_news_hold_*`·`market_news_item`은 읽지 않는다. 그날 행이 없으면 `Update delayed` 세 줄, 무료·Plus·로그인 전 모두 같다(#11) | 보류 칸은 검수에 걸린 AI 초안이다. 읽지 않으면 화면에 닿을 길이 없다 |
| 줄을 숨기지 않는다. 조용한 날·지연·미지원도 문구를 그린다 | 카드 높이가 날마다 바뀌지 않고, "확인 못 함"이 "없음"으로 보이지 않게 한다 |
| 방향 의견·등급 표현 없음. 아레나 화면은 만들지 않는다(보류) | ADR-0001 |
| 모든 페이지 하단에 `Not investment advice` | HANDOFF 3-3 |
| 1단계는 비공개 대시보드다. 배포 보호 없이 공개 배포하지 않는다. 로그인·무료/Plus 잠금은 2단계(#8, #9) | 실데이터 품질·데이터 표시 권한 확인 전이다 |
| 무료 시세 API 데이터는 화면에 그리지 않는다 | HANDOFF 4장: 구독 전 성능 검사용 |
| 디자인 기준은 사용자 시안 `web/design-system/user-mockup/landing.dc.html`(2026-10-20, #27). 어두운 테마 하나, 색·글꼴(Inter)·간격·라벨 스타일은 시안 값을 Tailwind 테마 토큰으로 옮겨 쓰고 컴포넌트에 hex를 직접 쓰지 않는다. 시안에 없는 화면은 시안의 토큰·패턴으로 만든다. `ui-ux-pro-max` 스킬은 접근성·UX 점검(대비, 포커스, 터치 크기, 모바일 레이아웃)에 쓴다(`--stack nextjs`) | 사용자 지시: 디자인은 사용자 시안, UI/UX 점검은 ui-ux-pro-max. 토큰 한 곳이면 디자인 변경이 한 파일이다 |
| 모바일 우선. 가로 스크롤 없음, 글자 크기는 시안 값(본문 14px·설명 16px·라벨 11px 이상), 대비 4.5:1, 링크·버튼 높이 44px 이상, 보이는 포커스 표시. 테마는 시안의 어두운 테마 하나 | 기준은 "폰에서 30초 안에 읽히는가". 크기는 사용자 시안이 정한다(#27) |

## 2. 디렉터리

```
web/
├── src/app/          # 라우트. `/` 랜딩(정적), `/cards` 카드 대시보드. 서버 컴포넌트가 기본
├── src/server/       # DB 읽기(server-only). 행 → 화면 모델 변환도 여기서만
├── src/lib/          # 순수 함수: 표시 형식(등락률·시각), 고정 문구표
├── src/components/   # 화면 모델(props)만 받는 컴포넌트
└── tests/            # vitest
```

architect 스펙이 다르게 정하면 스펙을 따른다.

## 3. 테스트·빌드

```bash
cd web && npm run lint && npm test && npm run build
```

테스트 입구:
1. 표시 형식 순수 함수(등락률 부호·반올림 표기, ET 시각, 상태 → 고정 문구)
2. 데이터 읽기 모듈: 로컬 Supabase에 카드를 넣고 읽어 화면 모델로 바뀌는지(backend 테스트처럼 로컬만, 원격 금지)
3. 컴포넌트 렌더: 화면 모델 props로 상태별(확인함·없음·지연·미지원·축소판·카드 없음) 그려지는 문구 확인

빌드 뒤 브라우저 번들에 비밀값이 없는지: 가짜 canary 키로 빌드하고 `web/.next/static`에서 canary를 grep해 0건. 같은 곳에서 `supabase-js|postgrest`도 0건이어야 한다. 이유: `server-only`가 빠져 DB 클라이언트가 번들에 들어가도 키는 실행 때 읽혀 canary grep만으로는 못 잡는다(#24 qa).

## 4. 로컬 개발

supabase-js는 PostgREST·API 게이트웨이(kong)를 거치므로 backend README의 `-x` 목록에서 `postgrest,kong,gotrue`를 빼고 띄운다(gotrue가 꺼져 있으면 `supabase status`가 키를 아예 출력하지 않는다). backend pytest는 로컬 `public` 테이블을 전부 비우므로 웹 DB 테스트와 동시에 돌리지 않는다. `supabase start` 뒤 `eval "$(supabase status -o env ...)"`처럼 셸 안에서만 값을 넣는다. 키 값을 출력·파일·채팅에 남기지 않는다. 로컬 주소(`http://127.0.0.1:54321`)만 HTTP 예외다.

## 5. 배포

Vercel 배포·환경 변수 설정은 메인(오케스트레이터)이 Vercel MCP로 한다. 에이전트는 배포하지 않는다. 비밀값(service role 키 등)은 사용자가 Vercel에 직접 넣는다.
