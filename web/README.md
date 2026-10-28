# m30 웹 (랜딩 + 카드 대시보드)

- `/` 랜딩(#27, 정적 페이지, DB를 읽지 않는다)
- `/cards` 가장 최근 거래일의 카드 전부를 종목순으로 보여주는 비공개 대시보드(#24)

Next.js App Router + TypeScript + Tailwind. 규칙은 `.claude/skills/web-conventions/SKILL.md`. 디자인 기준은 사용자 시안 `design-system/user-mockup/landing.dc.html`, 그 값을 옮긴 토큰은 `src/app/globals.css` 한 곳(카드 화면 메모: `design-system/market_in_30sec/pages/dashboard.md`). 글꼴 Inter는 `next/font`가 빌드 때 받아 자체 제공한다.

DB는 `src/server/cards.ts`(서버 전용)만 읽는다. 브라우저 번들에는 Supabase 클라이언트도 키도 없다(ADR-0003).

## 로컬에서 띄우기

```bash
# 준비: Docker Desktop 실행. supabase CLI, uv, node는 설치돼 있음
cd /Users/singyeongha/get_money_pj        # supabase/ 가 있는 레포 루트

# 웹은 supabase-js(HTTP)로 읽으므로 API 게이트웨이(kong)·PostgREST가 필요하고,
# gotrue를 빼면 supabase status가 키를 내주지 않는다. 그래서 백엔드 README의 -x 목록에서 gotrue·kong·postgrest를 뺀다
supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset                         # (선택) 로컬 DB를 비우고 마이그레이션을 처음부터 적용

# 셸에만 넣는다. 키 값을 화면·파일·채팅에 남기지 않는다(.env 파일을 만들지 않는다). zsh·bash 둘 다 된다
eval "$(supabase status -o env \
  --override-name db.url=SUPABASE_DB_URL \
  --override-name api.url=SUPABASE_URL \
  --override-name auth.service_role_key=SUPABASE_SERVICE_ROLE_KEY 2>/dev/null \
  | grep -E '^(SUPABASE_DB_URL|SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)=' | sed 's/^/export /')"
node -e 'for (const v of ["SUPABASE_DB_URL","SUPABASE_URL","SUPABASE_SERVICE_ROLE_KEY"]) console.log(v, process.env[v] ? "set" : "MISSING")'   # 값 대신 설정 여부만

# 가짜 데이터 파이프라인으로 카드 채우기(SUPABASE_DB_URL 사용, 로컬 전용)
cd backend
uv run python -m m30.pipeline 2026-10-13 --scenario scenarios/events_and_tags.json   # 10종목: 일정·레버리지 태그(TQQQ·SQQQ)·지연·미지원
uv run python -m m30.pipeline 2026-10-16 --scenario scenarios/first_card.json        # (선택) 같은 10종목의 다음 거래일: 등락률 상승·하락
cd ../web

npm install
# 배포 보호(아래 "배포 보호" 절). 없으면 모든 요청이 401이다. 비밀번호는 화면에 안 보이게 입력받는다(셸 기록에도 안 남는다)
export DASHBOARD_USER=owner
printf 'Dashboard password: '; read -rs DASHBOARD_PASSWORD; echo; export DASHBOARD_PASSWORD
npm run dev                               # http://localhost:3000(랜딩), /cards(카드) → 브라우저 로그인 창에 위 아이디·비밀번호 (운영 빌드 확인: npm run build && npm start)
```

- `/cards`는 DB에서 가장 최근 거래일의 카드만 보여준다. 위 두 줄을 다 돌리면 2026-10-16 카드가 보이고, 첫 줄만 돌리면 2026-10-13 카드가 보인다.
- 첫 번째 줄은 파이프라인이 저장한 코드 문구(`No new SEC filings found` / `Update delayed` / `Not covered yet`)다. 소식이 있는 종목은 검수(#7)가 끝나기 전까지 첫 번째 줄이 없는 축소판이고, 화면에는 `Update delayed`로 보인다.
- 백엔드 `uv run pytest`는 로컬 DB의 `public` 테이블을 전부 비운다. 돌린 뒤에는 위 파이프라인 줄로 다시 채운다.
- `SUPABASE_URL`·`SUPABASE_SERVICE_ROLE_KEY`가 없으면 페이지가 에러를 낸다. 값은 위 `eval` 줄로만 넣는다. `NEXT_PUBLIC_` 접두사를 붙이지 않는다(브라우저 번들에 들어간다).

## 배포 보호 (#25)

`src/proxy.ts`가 모든 요청(정적 파일 포함) 앞에서 HTTP Basic Auth를 확인한다. 아이디·비밀번호는 서버 환경 변수 `DASHBOARD_USER`·`DASHBOARD_PASSWORD`에서 요청 때마다 읽는다(빌드에 박히지 않는다). 둘 중 하나라도 없거나 비면 맞는 값이나 쿠키를 보내도 전부 401이다(닫힌 쪽). 401 응답에는 `WWW-Authenticate: Basic realm="market_in_30sec"`와 `Authentication required`만 있고 비밀값·환경 변수 이름은 없다.

- 로컬: 위 "로컬에서 띄우기"처럼 셸에서 `export`한다. `.env*` 파일을 만들지 않는다. `NEXT_PUBLIC_` 접두사를 붙이지 않는다(브라우저 번들에 들어간다).
- 확인: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/` → `401` (`/cards`도 같다).
- **Vercel(사용자 조치)**: 프로젝트 Settings → Environment Variables에 `DASHBOARD_USER`·`DASHBOARD_PASSWORD`를 **Sensitive**로, Production·Preview 둘 다에 **사용자가 직접** 넣는다(채팅·레포·로그에 값을 남기지 않는다). 값을 넣거나 바꾼 뒤에는 재배포해야 반영된다. 넣기 전 배포는 전부 401이라 공개되지 않는다.
- **기기당 한 번 로그인, 1년 기억**: Basic 로그인에 성공하면 `m30_auth` 쿠키(`HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=31536000`)를 심고, 이 쿠키가 있으면 로그인 창 없이 통과한다. 만료는 처음 로그인 뒤 1년 고정이다(쿠키로 들어온 요청은 쿠키를 다시 심지 않는다). 쿠키 값은 `DASHBOARD_PASSWORD`·`DASHBOARD_USER`에서 HKDF-SHA256(HMAC 기반)으로 만든 값이라 아이디·비밀번호가 들어 있지 않고, 따로 둘 비밀값도 없다. 다만 쿠키를 훔치면 비밀번호를 오프라인으로 추측해 볼 수 있으니 `DASHBOARD_PASSWORD`는 긴 무작위 값(20자 이상)으로 둔다.
- 로그아웃: 버튼은 없다. 모든 기기를 내보내려면 Vercel에서 `DASHBOARD_PASSWORD`를 바꾸고 재배포한다(이전 쿠키가 전부 무효가 된다). 한 기기만 내보내려면 그 브라우저에서 이 사이트 쿠키를 지운다.
- Basic Auth와 쿠키는 HTTPS 위에서만 안전하다(Vercel 도메인은 HTTPS). 쿠키에 `Secure`가 붙어 있어 HTTP로는 보내지지 않는다.

## 검사

```bash
cd web && npm run lint && npm test && npm run build
```

- `npm test`의 `tests/cards.db.test.ts`는 위 `eval` 줄의 환경 변수가 있어야 돌고, 로컬 주소(127.0.0.1·localhost)가 아니면 멈춘다. 2099-12-31 거래일과 `ZZW*` 테스트 티커만 넣고 끝나면 지운다(시드한 카드는 그대로).
- `tests/proxy.test.ts`는 배포 보호(`/`·`/cards` 둘 다, 인증 없음·틀린 값·형식 깨짐·환경 변수 미설정 → 401, 맞는 값 → 통과 + 쿠키, 맞는 쿠키 → 통과, 틀린 쿠키·비밀번호 바뀐 뒤 옛 쿠키 → 401, 응답·쿠키에 아이디·비밀번호 없음, matcher로 빠지는 경로 없음)를 DB 없이 본다.
- DB 없이 도는 테스트만: `npx vitest run --exclude tests/cards.db.test.ts`
- `tests/cards.read.test.ts`는 DB 없이 supabase-js 응답을 흉내 내 읽기 실패·1,000행 가드를 본다.
- 번들 노출 검사: 가짜 canary 키(`SUPABASE_SERVICE_ROLE_KEY`·`DASHBOARD_PASSWORD`)로 빌드하고 `.next/static`에서 canary와 `supabase-js|postgrest`를 찾는다. 둘 다 0건이 아니면 실패(exit 1). 값은 출력하지 않는다.

```bash
npm run check:bundle    # bundle check: N files in .next/static, canary=0, supabase-js|postgrest=0
```
