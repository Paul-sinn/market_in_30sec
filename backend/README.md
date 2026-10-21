# m30 서버

아침 파이프라인(가짜 공시·지표 일정 수집 → 원본 저장 → 공시 분류(가짜 LLM) → 첫 번째 줄 초안 → 검수 → 가짜 시세·일정으로 등락률·두 번째 줄(일정)·세 번째 줄(가격 사실)·레버리지 태그 → 카드 저장 → 보류함)과 로컬 Supabase 스키마.

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
uv run python -m m30.pipeline 2026-10-16 --scenario scenarios/filings_day.json       # 공시 수집·분류 확인용
```

- LLM은 시나리오의 `llm_replies`(가짜, 호출 순서대로: 분류 묶음 → 첫 번째 줄 초안 종목 순 → 공시마다 사실/예측 판정(걸리면 재생성 → 재판정))를 쓴다. `ANTHROPIC_API_KEY` 없이 돈다. CLI에 실제 Haiku를 연결하는 것은 #14. CLI는 문장을 찍지 않는다(`drafts:`·`review:` 줄은 결과 코드만).
- 검수: 초안 → 숫자 대조(계산 원본 `numbers`) → 금지어(`m30.copy_rules`, 종목명을 가리고) → 사실/예측 판정(LLM) → 걸리면 이유를 넣어 1회 재생성. 그래도 걸리면 카드에 8-K 항목 대체 줄(`Apple reported quarterly results (SEC filing)` 등)을 쓰고 `hold_queue`(보류함)에 행을 남긴다. 문장 없이 대체 줄만 나간 경우(본문 없음·LLM 실패)도 행이 생긴다. 8-K/A가 앞선 카드가 쓴 공시(같은 CIK·같은 `report_date` = EDGAR reportDate. 가짜 시나리오는 공시의 선택 키 `"report_date": "YYYY-MM-DD"`)를 정정하면 그 카드는 그대로 두고 `amended_filing` 행(`정정 공시 있음`)을 남긴다.
- 보류함 `rules` 읽는 법: 한 칸 = `{시도} {단계}: {이유}`.
  - 시도: `1` 처음 쓴 줄, `2` 걸린 이유를 넣어 한 번 다시 쓴 줄(`2 draft: call_limit`이면 다시 쓰려다, `2 fact_check: call_limit`이면 다시 쓴 줄을 판정받으려다 실행당 호출 상한에 막힘). `2`가 없으면 다시 쓰지 않은 것(문장이 없었거나 판정을 못 받음)
  - 단계: `draft` 초안 형식·문장 없음, `numbers` 숫자 대조, `copy_rules` 금지어 검사, `fact_check` 사실/예측 판정, `amended_filing` 정정 공시
  - `draft:` 뒤 이유: `no_text` 공시 본문을 못 읽어 AI를 부르지 않음 / `json_invalid`·`llm_failed`·`call_limit` AI가 문장을 못 줌(응답 형식 깨짐 두 번·전송 실패·실행당 호출 상한) / `empty` 빈 줄, `refusal` AI가 쓸 사실이 없다고 답함, `leftover` `#`이나 문장 중간 `+N more`가 남음, `multiple_sentences` 두 문장 이상, `too_long` 15단어 초과
  - `numbers: not from source`: 계산 원본(`numbers`)에 없는 숫자. `copy_rules:` 뒤는 검사기 문구 그대로(`금지어 'buy'` 등)
  - `fact_check:` 뒤: `forecast`·`opinion` 판정이 예측·의견이라고 봄 / `json_invalid`·`llm_failed`·`call_limit` 판정을 못 받음(문장이 나쁘다는 뜻이 아니다. 닫힌 쪽이라 대체 줄로 보냄)
  - `정정 공시 있음`: 이 카드가 쓴 공시에 8-K/A가 왔다. 카드는 자동으로 고치지 않았다
- 보류함 재발행(Supabase 대시보드 Table Editor에서 직접):
  1. `hold_queue`에서 그 행을 연다(`replacement_text`가 지금 카드에 나간 줄)
  2. `edited_text`에 꼬리표까지 포함한 줄 전체를 쓴다(예: `Apple named a new CFO (SEC filing)`). 문장만 저장해 두려면 `state`를 `edited`로(카드 그대로)
  3. `state`를 `republished`로 바꿔 저장하면 DB 트리거가 그 카드의 첫 번째 줄 문구만 바꾼다(아침 알림은 다시 만들지 않는다). 이미 `republished`인 행의 `edited_text`를 다시 고쳐도 카드가 따라 바뀐다. 바뀌기 전 줄은 수정 이력에 남는다
  - 같은 거래일을 다시 돌려도 재발행된 줄은 덮지 않는다. 공시 줄이 없는 카드(데이터 상태 문구)는 재발행이 오류로 거부된다
  - 사람 문장은 검사기를 거치지 않으니 저장 전에 미리 본다: `echo "Name named a new CFO (SEC filing)" | python3 .claude/skills/card-copy-rules/scripts/check_copy.py --mode card -`(레포 루트에서). 파이프라인처럼 그 카드의 종목명·티커를 단어마다 `Name`으로 바꿔 넣는다. 안 바꾸면 이름 때문에 정상 줄이 걸린다(`Best Buy`의 `buy`, `3M`의 숫자)
- 카드 수정 이력: 카드 내용(확인 시각·갱신 시각 제외)이 바뀔 때마다 바뀌기 전 행 전체가 `stock_card_revision.previous`(jsonb)에 남는다(트리거, 추가만).
- 출처 실패는 시나리오의 `failures`로 넣는다: `{"source": "sec_filings", "subject": "0000320193", "error": "transient", "times": 3}`. `source`는 `prices`·`events`·`sec_filings`·`indicators`·`llm`(뒤의 둘은 `subject` 없음), `error`는 `transient`(재시도함)·`access_denied`(401·403)·`error`. `times`가 없으면 계속 실패한다. CLI는 실제로 기다린다(재시도 간격 1·2·4초).

- `supabase start -x ...`: 테스트는 psycopg로 Postgres에 직접 붙으므로 Postgres(`supabase_db_*`)만 띄운다. 뺀 서비스: 로그인(gotrue), realtime, storage-api, imgproxy, API 게이트웨이(kong), mailpit, PostgREST, postgres-meta, Studio, edge-runtime, logflare, vector, supavisor. 로그인 화면 작업 등 이 서비스가 필요하면 `-x` 없이 `supabase start`.
- `supabase` 명령은 레포 루트에서, `uv` 명령은 `backend/`에서 실행한다.
- 테스트를 돌리면 로컬 DB의 `public` 테이블이 전부 비워진다.
- 테스트와 CLI는 `SUPABASE_DB_URL`이 로컬(127.0.0.1·localhost·::1)이 아니면 멈춘다. 원격 주소를 넣지 않는다.
- `SUPABASE_DB_URL`은 비밀번호가 든 비밀값이다. `.env` 파일에 두지 말고 위 `export` 줄로만 셸에 넣는다.
- 실제 외부 API 테스트(live, 기본 실행에서 빠짐): 실제 Haiku로 첫 번째 줄 초안을 한 번 만든다(`tests/test_newsline_live.py`, 응답 모양만 확인하고 문장은 출력하지 않는다). 키는 명령에 값을 쓰지 말고 셸에서 미리 `export ANTHROPIC_API_KEY`로 넣은 뒤 `uv run pytest -q -m live tests/test_newsline_live.py`. 사용자가 요청할 때만
