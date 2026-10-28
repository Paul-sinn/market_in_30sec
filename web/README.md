# m30 웹 (랜딩 + 카드 대시보드)

- `/` 랜딩(#27, 정적 페이지, DB를 읽지 않는다)
- `/cards` 가장 최근 거래일의 카드 전부를 종목순으로 보여주는 비공개 대시보드(#24). 위에 Google 로그인·로그아웃 버튼(#37). 로그인하면 위 "My stocks", 아래 "Browse"(#38, 아래 "내 종목" 절)
- `/auth/sign-in`(POST)·`/auth/callback`(GET)·`/auth/sign-out`(POST) 로그인 라우트(#37, 아래 "로그인" 절)
- `/my-stocks`(POST) 내 종목 넣기·빼기(#38)

Next.js App Router + TypeScript + Tailwind. 규칙은 `.claude/skills/web-conventions/SKILL.md`. 디자인 기준은 사용자 시안 `design-system/user-mockup/landing.dc.html`, 그 값을 옮긴 토큰은 `src/app/globals.css` 한 곳(카드 화면 메모: `design-system/market_in_30sec/pages/dashboard.md`). 글꼴 Inter는 `next/font`가 빌드 때 받아 자체 제공한다.

DB는 서버 전용 모듈만 만진다: 카드·커버 범위 읽기 `src/server/cards.ts`, 유저 데이터(프로필 보장·내 종목 읽기·넣기·빼기)는 `src/server/my-stocks.ts` 한 곳(웹의 유일한 쓰기 지점), 로그인 `src/server/auth.ts`. 브라우저 번들에는 Supabase 클라이언트도 키도 없다(ADR-0003).

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
  --override-name auth.service_role_key=SUPABASE_SERVICE_ROLE_KEY \
  --override-name auth.publishable_key=SUPABASE_PUBLISHABLE_KEY 2>/dev/null \
  | grep -E '^(SUPABASE_DB_URL|SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY|SUPABASE_PUBLISHABLE_KEY)=' | sed 's/^/export /')"
node -e 'for (const v of ["SUPABASE_DB_URL","SUPABASE_URL","SUPABASE_SERVICE_ROLE_KEY","SUPABASE_PUBLISHABLE_KEY"]) console.log(v, process.env[v] ? "set" : "MISSING")'   # 값 대신 설정 여부만

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
- `SUPABASE_URL`·`SUPABASE_SERVICE_ROLE_KEY`가 없으면 페이지가 에러를 낸다. `SUPABASE_PUBLISHABLE_KEY`가 없으면 카드는 그대로이고 로그인만 실패 문구가 된다. 값은 위 `eval` 줄로만 넣는다. `NEXT_PUBLIC_` 접두사를 붙이지 않는다(브라우저 번들에 들어간다).

## 배포 보호 (#25)

`src/proxy.ts`가 모든 요청(정적 파일 포함) 앞에서 HTTP Basic Auth를 확인한다. 아이디·비밀번호는 서버 환경 변수 `DASHBOARD_USER`·`DASHBOARD_PASSWORD`에서 요청 때마다 읽는다(빌드에 박히지 않는다). 둘 중 하나라도 없거나 비면 맞는 값이나 쿠키를 보내도 전부 401이다(닫힌 쪽). 401 응답에는 `WWW-Authenticate: Basic realm="market_in_30sec"`와 `Authentication required`만 있고 비밀값·환경 변수 이름은 없다.

- 로컬: 위 "로컬에서 띄우기"처럼 셸에서 `export`한다. `.env*` 파일을 만들지 않는다. `NEXT_PUBLIC_` 접두사를 붙이지 않는다(브라우저 번들에 들어간다).
- 확인: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/` → `401` (`/cards`도 같다).
- **Vercel(사용자 조치)**: 프로젝트 Settings → Environment Variables에 `DASHBOARD_USER`·`DASHBOARD_PASSWORD`를 **Sensitive**로, Production·Preview 둘 다에 **사용자가 직접** 넣는다(채팅·레포·로그에 값을 남기지 않는다). 값을 넣거나 바꾼 뒤에는 재배포해야 반영된다. 넣기 전 배포는 전부 401이라 공개되지 않는다.
- **기기당 한 번 로그인, 1년 기억**: Basic 로그인에 성공하면 `m30_auth` 쿠키(`HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=31536000`)를 심고, 이 쿠키가 있으면 로그인 창 없이 통과한다. 만료는 처음 로그인 뒤 1년 고정이다(쿠키로 들어온 요청은 쿠키를 다시 심지 않는다). 쿠키 값은 `DASHBOARD_PASSWORD`·`DASHBOARD_USER`에서 HKDF-SHA256(HMAC 기반)으로 만든 값이라 아이디·비밀번호가 들어 있지 않고, 따로 둘 비밀값도 없다. 다만 쿠키를 훔치면 비밀번호를 오프라인으로 추측해 볼 수 있으니 `DASHBOARD_PASSWORD`는 긴 무작위 값(20자 이상)으로 둔다.
- 로그아웃: 버튼은 없다. 모든 기기를 내보내려면 Vercel에서 `DASHBOARD_PASSWORD`를 바꾸고 재배포한다(이전 쿠키가 전부 무효가 된다). 한 기기만 내보내려면 그 브라우저에서 이 사이트 쿠키를 지운다.
- Basic Auth와 쿠키는 HTTPS 위에서만 안전하다(Vercel 도메인은 HTTPS). 쿠키에 `Secure`가 붙어 있어 HTTP로는 보내지지 않는다.

## 로그인 (#37)

Google 로그인(Supabase Auth)은 전부 웹 서버에서 돈다. 브라우저는 일반 폼으로 `/auth/sign-in`·`/auth/sign-out`에 POST할 뿐이고 Supabase 클라이언트·키를 받지 않는다(ADR-0003).

- 흐름: `Sign in to pick your stocks` → `POST /auth/sign-in`(브라우저 타임존을 숨은 칸으로 보냄) → 서버가 Auth 설정에서 Google이 켜졌는지 확인 → PKCE 검증값 쿠키를 심고 Supabase `/authorize`로 303 → Google → Supabase → `GET /auth/callback?code=…&timezone=…` → 코드 교환(세션 쿠키) → 첫 로그인이면 무료 유저 프로필(타임존이 비었거나 DB가 거절하면 `America/New_York`, 재로그인은 그대로) → `/cards`
- 세션: `sb-<ref>-auth-token`(크면 `.0` `.1` 조각) 쿠키, `HttpOnly; Secure; SameSite=Lax; Path=/`. 서버는 요청마다 Auth 서버에 확인한 유저 id만 쓴다(`getVerifiedUserId`). 액세스 토큰(1시간)은 `src/proxy.ts`가 배포 보호를 통과한 요청에서 갱신한다. 401 경로는 Supabase를 부르지 않는다
- 실패(로그인 미설정·Google 꺼짐·취소·교환 실패·프로필 실패)는 전부 `/cards?sign_in=failed` → `Sign-in could not be completed`. 카드는 그대로 보인다. 서버 로그에는 `auth: reason=<코드>` 한 줄만 남는다(`not_configured`·`provider_off`·`auth_unreachable`·`oauth_url`·`no_code`·`exchange_failed code=…`·`profile_failed`)
- 로그아웃: `Sign out` → 이 기기 세션만 끊고 쿠키 삭제 → `/cards`(로그인 전 모습)
- 이메일·비밀번호 로그인 경로는 운영 코드에 없다(`tests/guards.test.ts`). 테스트 도우미(`tests/local-supabase.ts`)만 로컬 Auth에 비밀번호로 로그인한다

### 로컬에서 확인

- 위 "로컬에서 띄우기"대로 띄우고 **`http://localhost:3000/cards`**로 연다. `next dev`·`next start`는 Host 헤더가 아니라 자기 호스트 이름(`localhost`)으로 요청 URL을 만들어서, `127.0.0.1`로 열면 로그인 버튼 뒤 리디렉션이 `localhost`로 넘어가 배포 보호 로그인 창이 한 번 더 뜬다
- 로그인 전: 카드 + `Sign in to pick your stocks` 버튼. 로컬 Supabase는 Google이 꺼져 있어 버튼을 누르면 `Sign-in could not be completed`가 나온다(= "로그인 설정이 없어도 카드는 정상, 시도만 실패" 확인). 서버 로그에 `auth: reason=provider_off`
- 로그인된 화면은 Google 없이 브라우저로 볼 수 없다(HttpOnly 세션을 넣을 길이 Google뿐이어야 운영에 이메일 경로가 안 생긴다). 대신 `tests/auth.db.test.ts`가 로컬 Auth의 진짜 세션으로 확인·갱신·로그아웃을 본다
- (선택, **커밋 금지**) 로컬에서 Google까지: `supabase/config.toml`에 `[auth.external.google]` `enabled = true`, `client_id = "env(SUPABASE_AUTH_EXTERNAL_GOOGLE_CLIENT_ID)"`, `secret = "env(SUPABASE_AUTH_EXTERNAL_GOOGLE_SECRET)"`, 그리고 `[auth]` `additional_redirect_urls`에 `"http://localhost:3000/**"`를 넣는다(위 이유로 콜백이 `localhost`로 돌아온다). Google 클라이언트의 리디렉션 URI에 `http://127.0.0.1:54321/auth/v1/callback`을 추가하고 `supabase stop && supabase start`. `enabled = true`를 커밋하면 env가 없는 다른 사람의 `supabase start`가 깨질 수 있다

### 사용자 조치 (운영 로그인에만 필요, 자동 테스트에는 필요 없음)

순서는 ③을 먼저 해도 된다. Google을 켜기 전에는 버튼을 누르면 실패 문구만 나오고 카드는 정상이다. Client secret·키는 채팅·파일에 남기지 말고 바로 붙여 넣는다.

1. **Google Cloud** (https://console.cloud.google.com)
   1. 프로젝트 선택 → New Project → 이름 `market-in-30sec` → Create
   2. APIs & Services → OAuth consent screen(Google Auth Platform → Get started) → App name `market_in_30sec`, User support email = 본인 → Audience **External** → Contact email → Create
   3. Google Auth Platform → Audience → Test users → **Add users** → 본인 Google 계정. Publishing status는 Testing 그대로(기본 범위 openid·email·profile이라 심사 불필요)
   4. Google Auth Platform → Clients → **Create client** → **Web application** → Name `m30 web` → Authorized JavaScript origins는 비움 → Authorized redirect URIs에 Supabase Google 설정 화면의 **Callback URL**(`https://<project-ref>.supabase.co/auth/v1/callback`) → Create → Client ID·Client secret을 2-1에 바로 붙여 넣기
2. **Supabase 대시보드** (https://supabase.com/dashboard → 프로젝트)
   1. Authentication → Sign In / Providers → **Google** → Enable ON → Client IDs, Client Secret 붙여 넣기 → Save
   2. 같은 화면 → **Email** → Enable Email provider **OFF** → Save. 위쪽 "Allow new users to sign up"은 **ON 유지**(끄면 Google 첫 로그인도 막힌다)
   3. Authentication → URL Configuration → Site URL `https://web-theta-olive-25.vercel.app` → Redirect URLs에 `https://web-theta-olive-25.vercel.app/**`, `http://localhost:3000/**`, `http://127.0.0.1:3000/**` → Save
   4. Project Settings → API Keys → **Publishable key** 복사 → 3-1에 바로 붙여 넣기
3. **Vercel** (web 프로젝트)
   1. Settings → Environment Variables → Key `SUPABASE_PUBLISHABLE_KEY`, Environments **Production·Preview**, **Sensitive** ON → Save(`NEXT_PUBLIC_` 붙이지 않는다)
   2. Deployments → 최신 Production → ⋯ → **Redeploy**

운영 확인: `/cards` → Sign in → Google → `/cards`로 돌아와 `Sign out` 버튼이 보인다 → Supabase Table Editor `user_profile`에 본인 행(`free`, 브라우저 타임존) → Sign out → Sign in 버튼으로 돌아온다. 실패하면 Vercel 로그에서 `auth: reason=` 줄을 본다. Preview 배포에서는 로그인이 안 된다(돌아갈 주소가 허용 목록 밖, 스펙 #37 R5).

## 내 종목 (#38)

- 로그인 화면: 거래일 제목 → **My stocks**(잠기지 않은 내 종목을 넣은 순서로. 그날 카드가 없으면 같은 자리에 `Summary arrives tomorrow morning`, 카드마다 `Remove`) → **Browse**(나머지 카드). 무료면 제목 옆에 `Swaps left today: N`
- 고르기: My stocks 아래 `Pick your stocks` 펼침(커버 범위 중 내 종목이 아닌 것마다 `Add`). 내 종목이 0개면 열린 채로 나온다(첫 방문). 로그인 전 화면은 #37 그대로
- 넣기·빼기는 일반 폼 `POST /my-stocks`(`change=add|remove`, `ticker`) → 303 `/cards`(실패하면 `/cards?my_stock=<코드>`). JS 없이 돌고 브라우저에 Supabase가 없다. 유저는 세션(`getVerifiedUserId`)으로만 알고 본문의 유저 id는 읽지 않는다. 세션이 없으면 쓰지 않고 `/cards`로
- 규칙은 DB 트리거만 지킨다(ADR-0004): 무료 잠기지 않은 내 종목 3개, 빼기 = 교체 1회·하루 3회(프로필 타임존 자정), 넣기는 교체가 아님, 이미 내 종목이면 아무 일 없음(이력 없음). 웹은 거절 이름만 문구로 바꾼다
  - `free_swap_limit` → `Free plan can swap stocks 3 times a day. Plus has no limit.`
  - `free_my_stock_limit` → `Free plan can pick 3 stocks. Remove one to add another.`
  - 그 밖(커버 범위 밖 티커, DB 오류) → `My stocks could not be updated`. 서버 로그는 `my_stock: reason=write_failed code=<DB 코드>` 한 줄
- 남은 교체 = 3 − 오늘(`user_local_date`) 빼기 수, 0 미만은 0. 표시용이고 막는 건 DB다. Plus는 그리지 않는다
- 웹은 AI를 부르지 않는다. 넣은 종목의 카드는 다음 아침 실행부터 생긴다(생성 대상, #8)
- 원격에 `supabase/migrations/20261028043018_my_stock_readd_noop.sql`이 없으면 3개가 찬 무료 유저의 다시 넣기가 `free_my_stock_limit`로 거절된다(원격 적용은 사용자 확인 후)

## 검사

```bash
cd web && npm run lint && npm test && npm run build
```

- `npm test`의 `tests/*.db.test.ts`는 위 `eval` 줄의 환경 변수(`SUPABASE_PUBLISHABLE_KEY` 포함)가 있어야 돌고, 로컬 주소(127.0.0.1·localhost)가 아니면 멈춘다. `cards.db.test.ts`는 2099-12-31 거래일과 `ZZW*` 테스트 티커만 넣고 끝나면 지운다(시드한 카드는 그대로). `auth.db.test.ts`·`my-stocks.db.test.ts`는 로컬 Auth admin으로 `…@example.test` 유저를 만들고 끝나면 Auth admin으로 지운다(프로필·내 종목·이력은 FK cascade). `my-stocks.db.test.ts`는 커버 범위에 `ZZM*` 테스트 티커를 넣고 끝나면 지운다.
- `tests/auth.db.test.ts`: 진짜 세션으로 확인(정상·없음·위조 3종·만료), 프록시 갱신(새 쿠키가 응답과 같은 요청의 페이지 둘 다에), 로그아웃(쿠키 삭제 + Auth에서 폐기), 콜백 실패(code 없음·공급자 오류·가짜 code). `tests/my-stocks.db.test.ts`: 프로필 보장(첫 로그인·재로그인 그대로·이상한 타임존 → NY·빈 타임존 → NY), 내 종목(#38: 3개 → 4번째 거절 → 빼기 → 남은 교체 → 4번째 빼기 거절 → 다시 넣기 무변화, 프로필 타임존의 오늘, Plus, 잠금, 다른 유저 안 보임, 커버 범위 밖 티커는 쓰지 않음)
- `tests/my-stocks.route.test.ts`(DB 없음): `POST /my-stocks` 세션 없음 → 쓰지 않음, 세션 유저 id로만 쓰기, 거절 이름 → 결과 코드, 교착(40P01) 1회 재시도, 그 밖 오류·이상한 입력 → 실패 코드와 고정 로그, 열린 리디렉션 없음
- `tests/auth.test.ts`(DB 없음): 로그인 미설정·Google 꺼짐·Auth 응답 없음 → 실패 문구, Google 켜짐 → PKCE authorize + HttpOnly 검증값 쿠키, 콜백 → 프로필 보장 연결, 프로필 실패 → 세션 삭제, 로그인·콜백·로그아웃이 `next`·`redirect` 값을 무시(열린 리디렉션 없음)
- `tests/proxy.test.ts`는 배포 보호(`/`·`/cards` 둘 다, 인증 없음·틀린 값·형식 깨짐·환경 변수 미설정 → 401, 맞는 값 → 통과 + 쿠키, 맞는 쿠키 → 통과, 틀린 쿠키·비밀번호 바뀐 뒤 옛 쿠키 → 401, 응답·쿠키에 아이디·비밀번호 없음, matcher로 빠지는 경로 없음)와 로그인 세션 갱신의 경계(게이트 거부·세션 없음·`/_next/` 정적 파일이면 Auth 요청 0회)를 DB 없이 본다.
- DB 없이 도는 테스트만: `npx vitest run --exclude 'tests/*.db.test.ts'`
- `tests/cards.read.test.ts`는 DB 없이 supabase-js 응답을 흉내 내 읽기 실패·1,000행 가드를 본다.
- 번들 노출 검사: 가짜 canary 키(`SUPABASE_SERVICE_ROLE_KEY`·`SUPABASE_PUBLISHABLE_KEY`·`DASHBOARD_PASSWORD`)로 빌드하고 `.next/static`에서 canary와 `supabase-js|postgrest|gotrue-js|supabase-ssr`를 찾는다. 둘 다 0건이 아니면 실패(exit 1). 값은 출력하지 않는다.

```bash
npm run check:bundle    # bundle check: N files in .next/static, canary=0, supabase-js|postgrest|gotrue-js|supabase-ssr=0
```
