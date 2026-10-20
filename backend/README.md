# m30 서버

아침 파이프라인(가짜 시세·일정 → 등락률·두 번째 줄(일정)·세 번째 줄(가격 사실)·레버리지 태그 → 카드 저장)과 로컬 Supabase 스키마.

## 실행

```bash
# 준비: Docker Desktop 실행. supabase CLI, uv는 설치돼 있음
cd /Users/singyeongha/get_money_pj        # supabase/ 가 있는 레포 루트
supabase start -x gotrue,realtime,storage-api,imgproxy,kong,mailpit,postgrest,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset                         # 로컬 DB를 비우고 마이그레이션을 처음부터 적용
eval "export $(supabase status -o env --override-name db.url=SUPABASE_DB_URL | grep '^SUPABASE_DB_URL=')"
cd backend && uv run pytest               # 기본 테스트 (네트워크·API 키 없이. 로컬 DB 데이터는 지워짐)
uv run python -m m30.pipeline 2026-10-16 --scenario scenarios/first_card.json   # 직접 돌려보기
uv run python -m m30.pipeline 2026-10-13 --scenario scenarios/events_and_tags.json   # 두 번째 줄·태그 확인용
```

- `supabase start -x ...`: 테스트는 psycopg로 Postgres에 직접 붙으므로 Postgres(`supabase_db_*`)만 띄운다. 뺀 서비스: 로그인(gotrue), realtime, storage-api, imgproxy, API 게이트웨이(kong), mailpit, PostgREST, postgres-meta, Studio, edge-runtime, logflare, vector, supavisor. 로그인 화면 작업 등 이 서비스가 필요하면 `-x` 없이 `supabase start`.
- `supabase` 명령은 레포 루트에서, `uv` 명령은 `backend/`에서 실행한다.
- 테스트를 돌리면 로컬 DB의 `public` 테이블이 전부 비워진다.
- 테스트와 CLI는 `SUPABASE_DB_URL`이 로컬(127.0.0.1·localhost·::1)이 아니면 멈춘다. 원격 주소를 넣지 않는다.
- `SUPABASE_DB_URL`은 비밀번호가 든 비밀값이다. `.env` 파일에 두지 말고 위 `export` 줄로만 셸에 넣는다.
- 실제 외부 API 테스트: `uv run pytest -m live` (사용자가 요청할 때만. 지금은 0개)
