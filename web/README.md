# m30 웹 (카드 대시보드)

가장 최근 거래일의 카드 전부를 종목순으로 보여주는 비공개 대시보드(#24). Next.js App Router + TypeScript + Tailwind. 규칙은 `.claude/skills/web-conventions/SKILL.md`, 디자인 토큰은 `design-system/market_in_30sec/` → `src/app/globals.css`.

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
npm run dev                               # http://localhost:3000 (운영 빌드 확인: npm run build && npm start)
```

- 화면은 DB에서 가장 최근 거래일의 카드만 보여준다. 위 두 줄을 다 돌리면 2026-10-16 카드가 보이고, 첫 줄만 돌리면 2026-10-13 카드가 보인다.
- 지금 파이프라인은 첫 번째 줄을 만들지 않아(#6·#7 전) 모든 카드가 축소판이다. 첫 번째 줄은 `Update delayed`로 보인다.
- 백엔드 `uv run pytest`는 로컬 DB의 `public` 테이블을 전부 비운다. 돌린 뒤에는 위 파이프라인 줄로 다시 채운다.
- `SUPABASE_URL`·`SUPABASE_SERVICE_ROLE_KEY`가 없으면 페이지가 에러를 낸다. 값은 위 `eval` 줄로만 넣는다. `NEXT_PUBLIC_` 접두사를 붙이지 않는다(브라우저 번들에 들어간다).

## 검사

```bash
cd web && npm run lint && npm test && npm run build
```

- `npm test`의 `tests/cards.db.test.ts`는 위 `eval` 줄의 환경 변수가 있어야 돌고, 로컬 주소(127.0.0.1·localhost)가 아니면 멈춘다. 2099-12-31 거래일과 `ZZW*` 테스트 티커만 넣고 끝나면 지운다(시드한 카드는 그대로).
- `tests/cards.read.test.ts`는 DB 없이 supabase-js 응답을 흉내 내 읽기 실패·1,000행 가드를 본다.
- 번들 노출 검사: 가짜 canary 키로 빌드하고 `.next/static`에서 canary와 `supabase-js|postgrest`를 찾는다. 둘 다 0건이 아니면 실패(exit 1). 값은 출력하지 않는다.

```bash
npm run check:bundle    # bundle check: N files in .next/static, canary=0, supabase-js|postgrest=0
```
