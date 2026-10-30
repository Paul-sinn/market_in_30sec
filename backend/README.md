# m30 서버

아침 파이프라인(가짜 공시·지표 일정 수집 → 원본 저장 → 공시 분류(가짜 LLM) → 첫 번째 줄 초안 → 검수 → 가짜 시세·일정으로 등락률·두 번째 줄(일정)·세 번째 줄(가격 사실)·레버리지 태그 → 카드 저장 → 보류함)과 로컬 Supabase 스키마.

## 실행

```bash
# 준비: Docker Desktop 실행. supabase CLI, uv는 설치돼 있음
cd /Users/singyeongha/get_money_pj        # supabase/ 가 있는 레포 루트
supabase start -x gotrue,realtime,storage-api,imgproxy,kong,mailpit,postgrest,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset                         # 로컬 DB를 비우고 마이그레이션을 처음부터 적용
eval "$(supabase status -o env --override-name db.url=SUPABASE_DB_URL | grep '^SUPABASE_DB_URL=' | sed 's/^/export /')"
cd backend && uv run pytest               # 기본 테스트 (네트워크·API 키 없이. 로컬 DB 데이터는 지워짐)
uv run python -m m30.pipeline 2026-10-16 --scenario scenarios/first_card.json   # 직접 돌려보기
uv run python -m m30.pipeline 2026-10-13 --scenario scenarios/events_and_tags.json   # 두 번째 줄·태그 확인용
uv run python -m m30.pipeline 2026-10-16 --scenario scenarios/filings_day.json       # 공시 수집·분류 확인용
```

- LLM은 시나리오의 `llm_replies`(가짜, 호출 순서대로: 분류 묶음 → 첫 번째 줄 초안 종목 순 → 공시마다 사실/예측 판정(걸리면 재생성 → 재판정))를 쓴다. `ANTHROPIC_API_KEY` 없이 돈다. 실제 Anthropic은 운영 모드(아래)와 품질 확인 모드(`--quality`, 맨 아래)만 쓴다. CLI는 문장을 찍지 않는다(`drafts:`·`review:` 줄은 결과 코드만. 예외는 `--quality`뿐).
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
- 출처 실패는 시나리오의 `failures`로 넣는다: `{"source": "sec_filings", "subject": "0000320193", "error": "transient", "times": 3}`. `source`는 `prices`·`events`·`sec_filings`·`indicators`·`llm`(뒤의 둘은 `subject` 없음), `error`는 `transient`(재시도함)·`rate_limited`(429, 재시도함. 성공해도 CLI 맨 위 `RATE LIMITED (429, retried): …` 줄에 남는다)·`access_denied`(401·403, `ACCESS DENIED` 줄)·`error`. `times`가 없으면 계속 실패한다. CLI는 실제로 기다린다(재시도 간격 1·2·4초).

- `supabase start -x ...`: 테스트는 psycopg로 Postgres에 직접 붙으므로 Postgres(`supabase_db_*`)만 띄운다. 뺀 서비스: 로그인(gotrue), realtime, storage-api, imgproxy, API 게이트웨이(kong), mailpit, PostgREST, postgres-meta, Studio, edge-runtime, logflare, vector, supavisor. 로그인 화면 작업 등 이 서비스가 필요하면 `-x` 없이 `supabase start`.
- `supabase` 명령은 레포 루트에서, `uv` 명령은 `backend/`에서 실행한다.
- 테스트를 돌리면 로컬 DB의 `public` 테이블이 전부 비워진다.
- 테스트와 CLI는 `SUPABASE_DB_URL`이 로컬(127.0.0.1·localhost·::1)이 아니면 멈춘다(CLI는 `--production`이 아니면). 테스트에 원격 주소를 넣지 않는다.
- `SUPABASE_DB_URL`은 비밀번호가 든 비밀값이다. `.env` 파일에 두지 말고 위 `export` 줄로만 셸에 넣는다.
- SEC EDGAR 실제 어댑터(`m30.adapters.edgar`): `EdgarClient(load_edgar_settings())`의 `get`을 `EdgarFilingSource`·`ticker_ciks`에 넣는다. CLI 시나리오 모드는 가짜 공시, 운영 모드(`--production`)는 이 어댑터를 쓴다. SEC 공정 접근 규칙대로 User-Agent에 이름과 연락 이메일이 필요하다. 값은 채팅·파일·커밋에 쓰지 말고 셸에서만 넣는다: `export SEC_USER_AGENT="<이름> <연락 이메일>"`. 요청은 초당 8회 이하(0.125초 간격), `www.sec.gov`·`data.sec.gov` HTTPS만, 리다이렉트는 따라가지 않는다. 저장 원본(`sec_filing.payload`)은 전체 제출 파일에서 SEC-HEADER(접수 시각 원본) + 8-K·8-K/A 본문과 Exhibit 99(HTML·텍스트) 문서 구간을 원문 그대로 이은 것이다(그림·XBRL·ZIP·PDF·다른 첨부 제외). 쓸 문서가 하나도 없는 공시는 원본을 비워 그 CIK를 지연으로 둔다. 접수 시각(`accepted_at`)은 SEC-HEADER `<ACCEPTANCE-DATETIME>`(동부 벽시계)에서 읽는다. submissions JSON의 `acceptanceDateTime`은 실제로 헤더 + 8시간에 `Z`라(2026-10-21 live 관측) 받을 후보를 고르는 데만 쓰고(공시 기간 앞뒤 12시간), 헤더 시각으로 기간을 다시 정확히 거른다. 헤더 접수 시각이 없거나 틀리면 그 CIK는 지연이다. 실험 종목 15개는 `m30.experiment`(ETF 4개는 CIK 없음 → `Not covered yet`)
- SEC live 테스트(요청 10회 미만, 사용자가 요청할 때만): 위 `export` 뒤 `uv run pytest -q -m live tests/test_edgar_live.py`. `SEC_USER_AGENT`가 없으면 건너뛴다. 단언은 참/거짓과 가정 번호(`A1`~`A5`)만 찍는다(본문·User-Agent 없음). A1은 모든 공시에 헤더 접수 시각이 있고 `accepted_at`이 그 값인지 본다
- Tiingo 실제 시세 어댑터(`m30.adapters.tiingo`, #18, 벤더 확인은 `docs/vendors/tiingo.md`): `TiingoPriceSource(load_tiingo_settings())`. 종목마다 EOD 요청 1회(53주: 52주 사실 + 휴장일 여유). 토큰은 `Authorization: Token …` 헤더로만 보낸다(URL에 없음). `api.tiingo.com` HTTPS만, 리다이렉트는 따라가지 않는다. 봉은 Tiingo의 원래 시가·고가·저가·종가·거래량을 **분할만** 조정한 값이다: 각 봉을 그 뒤 봉들의 `splitFactor` 곱으로 나눈다(거래량은 곱한다). 배당까지 조정한 `adj*` 값은 쓰지 않는다. 받은 봉 중 가격이 $0.0001~$1B 밖이거나, OHLC 순서가 틀리거나(저가 ≤ 시가·종가 ≤ 고가), 하루 등락률이 DB 범위(±99,999.9%) 밖이면 그 종목만 지연이다(`failed: prices/<티커>=invalid_data`). 401·403은 키 오류로 이번 실행에서 시세를 더 부르지 않는다. 404(모르는 티커)·깨진 응답·기간 안 봉 0개(벤더 장애로 본다. 커버 종목은 모두 1년 넘게 상장)는 그 종목만 지연이고 실패로 남는다(`failed: prices/<티커>=error`, exit 1)
- Tiingo live 테스트(요청 1회, 사용자가 요청할 때만): 셸에서 `export TIINGO_API_KEY`(값을 명령에 쓰지 않는다) 뒤 `uv run pytest -q -m live tests/test_tiingo_live.py`. 키가 없으면 건너뛴다. 모양만 보고 가격은 찍지 않는다
- 실제 외부 API 테스트(live, 기본 실행에서 빠짐): 실제 Haiku로 첫 번째 줄 초안을 한 번 만든다(`tests/test_newsline_live.py`, 응답 모양만 확인하고 문장은 출력하지 않는다). 키는 명령에 값을 쓰지 말고 셸에서 미리 `export ANTHROPIC_API_KEY`로 넣은 뒤 `uv run pytest -q -m live tests/test_newsline_live.py`. 사용자가 요청할 때만

## 운영 모드 (매일 아침 실행기, #26)

```bash
uv run python -m m30.pipeline --production              # 오늘(동부) 거래일. 원격 DB를 쓸 수 있는 유일한 모드
uv run python -m m30.pipeline --production 2026-10-16   # 지난 거래일 다시 돌리기·빠진 날 채우기
```

- `.github/workflows/morning.yml`이 평일 09:17 UTC(05:17 EDT / 04:17 EST)에 이 명령을 돌린다. Actions → `morning-pipeline` → Run workflow로 수동 실행(거래일 입력은 비워도 된다). 실행은 한 번에 하나씩.
- 출처: 공시 = SEC EDGAR, LLM = Anthropic, 시세 = Tiingo(`TIINGO_API_KEY`가 있을 때). 실제 출처가 아직 없는 자리는 가짜 데이터 없이 데이터 상태 문구만: 시세 키 없음 → 등락률 지연·세 번째 줄 `Update delayed`(실패로 치지 않는다), 일정(#21 전) → 두 번째 줄 `Not covered yet`, 지표 일정 → 저장 안 함. 마지막 줄 `prices=tiingo` / `prices=none`이 어느 쪽으로 돌았는지 알려 준다. 실행 전에 실험 종목 CIK를 SEC 티커 목록으로 갱신하고, 실패하면 저장된 행을 쓴다(`coverage: NOT REFRESHED …`).
- 필요한 환경 변수 셋: `SUPABASE_DB_URL`, `ANTHROPIC_API_KEY`, `SEC_USER_AGENT`. 하나라도 없으면 DB에 붙기 전에 이름만 알리고 exit 2.
- 선택 환경 변수 `DISCORD_WEBHOOK_URL`(#17, 실패 알림): 있으면 운영 실행마다 터미널 요약 줄 그대로를 Discord로 한 번 보낸다(머리줄 `OK morning <거래일> exit=0` 또는 `**FAILED** morning <거래일> exit=<코드>` + 코드 블록). 보내지 않는 경우: 변수 없음·빈 값(아무것도 찍지 않는다), 주말·휴장일 exit 0, `ALREADY_DONE`, `--quality`. 끝에 `discord: sent` 또는 `discord: not sent (reason=bad_url|http_<상태>|timeout|connection|error)`가 찍힌다. 보내기 실패는 exit 코드를 바꾸지 않고 다시 시도하지 않는다. 주소는 `https://discord.com/api/webhooks/…` 한 줄이어야 한다(아니면 `bad_url`). 메시지에는 터미널과 같은 코드·건수·티커만 있다(카드 문장·가격·URL·키 없음). 메시지가 2000자를 넘으면 뒤 줄부터 빼고 `… N more lines (see Actions log)`.
- 선택 환경 변수 `TIINGO_API_KEY`: Tiingo **유료(Commercial) 구독 전까지 비워 둔다**. 없거나 빈 값이면 시세 없이 돈다(`prices=none`). 값이 있는데 한 줄 ASCII가 아니면(공백·줄바꿈) DB에 붙기 전에 이름만 알리고 exit 2.
- **무료(Starter) 플랜 키는 GitHub(Actions secrets)·Vercel·원격 Supabase에 절대 넣지 않는다.** 무료 시세는 개인·비상업 전용이라 구독 전 성능 검사와 Paul의 Mac 로컬 미리보기에만 쓴다(HANDOFF 4장): 로컬 Supabase 주소로 `export SUPABASE_DB_URL`(위 `eval` 줄) + 셸에서 `export TIINGO_API_KEY` 뒤 `uv run python -m m30.pipeline --production <지난 거래일>`, 확인이 끝나면 레포 루트에서 `supabase db reset`. 유료 구독 뒤 Actions에 넣을 때는 `morning.yml`의 실행 단계 `env:`에 `TIINGO_API_KEY: ${{ secrets.TIINGO_API_KEY }}` 한 줄과 `tests/test_workflow.py`의 secrets 목록을 같이 고친다.
- 원격 DB 주소는 Supabase **Session pooler**(포트 5432) URI만. Transaction pooler(6543)는 연결 전에 거부한다(`set role service_role`이 연결 내내 유지돼야 한다). Direct connection은 IPv6 전용이라 GitHub 러너에서 붙지 못한다. 비로컬 연결은 항상 `sslmode=require`.
- DB 연결 실패 줄 끝의 `(reason=…)`(원래 메시지는 호스트·사용자가 들어 있어 찍지 않는다)와 확인할 것: `bad_url` URI 형식(앞뒤 공백·줄바꿈 없이 붙여 넣기, 비밀번호 특수문자는 퍼센트 인코딩) / `auth_failed` 비밀번호 / `auth_blocked` 비밀번호를 여러 번 틀려 풀러가 잠금 → 올바른 비밀번호로 고치고 잠시 뒤 다시 / `tenant_not_found` 사용자 이름 `postgres.<프로젝트 ref>`·풀러 호스트의 리전·프로젝트 일시정지 / `host_not_found` 호스트 이름 / `network_unreachable` Direct connection(IPv6 전용) → Session pooler URI로 / `refused` 호스트·포트(5432) / `timeout` 프로젝트 상태·네트워크 / `other` 그 밖(Supabase 대시보드 로그).
- exit 코드: 0 = 정상·주말·휴장일(카드를 만들지 않는다), 2 = 인자 오류·이른/미래 날짜(그날 04:00 ET 전)·거래일 달력 표 밖의 해·설정 누락·값 형식 오류·트랜잭션 풀러(6543), 1 = DB 연결 실패·같은 거래일 실행이 이미 돌고 있음(`LOCKED:`)·예외·재시도 뒤에도 실패한 출처 호출(401·403 포함)·카드 0장(이어 하기로 건너뛴 카드도 0장). 1이면 워크플로가 실패로 끝난다.
- 거래일 달력(#16): `m30/trading_day.py`의 NYSE 휴장일 표(조기 마감일은 거래일). **매년 NYSE "Holidays & Trading Hours"(nyse.com/markets/hours-calendars)가 다음 해를 실으면 표와 `CALENDAR_YEARS`에 넣는다.** 표가 끝나기 1년 전부터 `test_거래일_달력은_내년_말까지_있다`가 실패해서 알려 준다. 표 밖의 해는 `거래일 달력(trading_day.py)에 …년 NYSE 휴장일이 없습니다`로 exit 2(휴장일 카드를 만들지 않는 쪽). 임시 휴장(예: 2025-01-09 국가 애도일)은 발표가 나면 손으로 넣는다.
- 실행 잠금·이어 하기(#16): 같은 거래일 실행은 Postgres advisory lock(`classid = 16`, `objid = YYYYMMDD`)으로 하나만 돈다. 두 번째는 기다리지 않고 `LOCKED: <날짜> …` 한 줄로 exit 1. 프로세스가 죽으면 연결이 끊기며 DB가 잠금을 푼다. 실행마다 `pipeline_run`에 한 행(끝까지 가면 `finished_at`)이 남고, 끝나지 않은 실행 뒤의 재실행은 그 실행이 저장한 카드를 건너뛴다(요약 `resumed=<티커,…>`). 깨끗하게 전부 다시 만들려면 한 번 더 돌린다(앞 실행이 끝까지 갔으면 전부 다시 만든다).
- 잠금이 남아 같은 거래일이 계속 `LOCKED:`이면(세션 풀러가 끊긴 연결의 잠금을 안 푼 경우, 확인 못 한 위험): 돌고 있는 실행이 정말 없는지 Actions에서 확인한 뒤, 사용자 확인을 받고 SQL Editor에서 `select pg_terminate_backend(pid) from pg_locks where locktype = 'advisory' and classid = 16 and objid = <YYYYMMDD>`.
- 발행 중단(#16): 잘못 나간 카드는 Supabase SQL Editor에서 `update public.stock_card set publish_suspended = true where ticker = '<티커>' and trading_day = '<YYYY-MM-DD>'`. 카드 데이터·보류함·이력은 남고 웹·알림 후보에서 빠진다. 파이프라인 재실행은 이 값을 바꾸지 않는다. 되돌리려면 `false`. 바꾼 기록은 수정 이력에 남는다.
- 예상 못 한 예외는 `RUN FAILED: <예외 이름> [sqlstate=<코드>]` 한 줄만 찍는다(메시지·traceback 없음: DB 오류 DETAIL에 행 내용, 라이브러리 메시지에 키가 섞일 수 있다). 원인을 보려면 로컬 DB에서 같은 날짜로 `run_production`을 직접 부른다.
- 종목 예외(#17): 외부 호출 하나(시세·일정·공시·편입 보고·LLM)에서 예상 못 한 예외가 나면 그 대상만 지연이고 `failed: <출처>/<대상>=unexpected:<예외 이름>`으로 남는다. 카드 만들기·저장에서 나면 그 종목 카드만 전 줄 지연으로 저장하고(보류함 행은 그대로) `failed: card/<티커>=unexpected:<예외 이름>`. 둘 다 실패한 실행(exit 1)이다. 전 줄 지연 카드마저 저장하지 못하면 `RUN FAILED`로 끝나고 다음 실행이 이어 한다.
- 실패한 실행(exit 1이 되는 요약)은 맨 위에 `!!! FAILED: failures=<출처 실패 + 종목 예외> cards=<저장 + 이어 하기로 건너뛴 카드> !!!`와 `failed: …` 목록을 찍는다. 요약에는 LLM 토큰(`tokens=in:…,out:…,cache_read:…,cache_write:…`)과 줄 상태별 카드 수(`lines: change[…] news[…] event[…] price[…]`, 0은 뺀다)가 있다.
- GitHub 예약 실행(예비)이 끝난 실행 없이 돌기 시작하면 첫 줄에 `BACKUP RUN: no finished run when the GitHub schedule backup started (check pg_cron dispatch)`. 정시 dispatch(pg_cron, #43)가 오지 않았거나 실패했다는 신호다.
- 실행 기록(#17): 끝까지 간 실행은 `pipeline_run` 행에 `finished_at`과 함께 `failed`(exit 1이 되는 실행인지)와 `summary`(jsonb: `counts`·`lines`·`failures`·`access_denied`·`rate_limited`·`llm`, 코드·건수·티커만)를 남긴다. 죽은 실행은 셋 다 null(사후 기록 없음. 그 정보는 Actions 로그·Discord에 있다). 읽기 예: 최근 실패 `select trading_day, summary->'failures' from public.pipeline_run where failed order by id desc limit 10`, 이번 달 입력 토큰 `select sum((summary->'llm'->>'input_tokens')::bigint) from public.pipeline_run where started_at >= date_trunc('month', now())`.
- **레포가 공개라 Actions 로그도 공개다.** CLI는 결과 코드·건수·티커만 찍는다(예외: 로컬 DB 전용 `--quality`, 맨 아래). 카드 문장·공시 본문·가격·URL·키·환경 변수 값을 출력에 더하지 않는다(#17·#18·#21도 같은 규칙).
- 사용자 설정(값은 채팅·파일·커밋에 쓰지 않는다): ① Supabase Connect → Session pooler URI(비밀번호 칸 채움, 특수문자는 퍼센트 인코딩) ② GitHub Settings → Environments → `production`(배포 브랜치 `main`만) + environment secrets 셋(Tiingo 유료 구독 뒤에 `TIINGO_API_KEY` 추가) ③ 실패한 Actions 알림 켜기 ④ main 병합 뒤 첫 실행은 수동으로 ⑤ (선택) Discord 채널 설정 → 연동 → 웹후크 → 새 웹후크 → URL 복사 → `gh secret set DISCORD_WEBHOOK_URL --env production`(프롬프트에 붙여 넣는다. 셸 기록에 남기지 않는다).

## 커밋 전 비밀값 검사 (gitleaks, #17)

키 모양 문자열(API 키·토큰·DB 접속 문자열의 비밀번호·Discord 웹훅 주소·Supabase 비밀 키)이 든 커밋을 커밋 전에 막는다. 규칙은 레포 루트 `.gitleaks.toml`(gitleaks 기본 규칙 + 이 레포 규칙 셋), 훅은 `.githooks/pre-commit`.

```bash
brew install gitleaks                        # 설치(클론한 Mac마다 한 번)
git config core.hooksPath .githooks          # 켜기(클론마다 한 번, 레포 루트에서)
# 확인(커밋하지 않는다): 가짜 웹훅 주소를 스테이지하고 훅을 직접 돌린다 → exit=1, 값은 REDACTED
echo "x=https://discord.com/api/webhooks/123456789012345678/$(openssl rand -hex 34)" > leak_check.txt
git add leak_check.txt && .githooks/pre-commit; echo "exit=$?"
git rm --cached -q leak_check.txt && rm leak_check.txt
```

- 훅은 스테이지된 변경만 본다(`gitleaks git --pre-commit --staged --redact`). 찾으면 커밋이 막히고 값은 가려서 찍는다. 훅을 켰는데 gitleaks가 없으면 커밋을 막는다.
- **`git commit --no-verify`로 건너뛰지 않는다.** 걸리면 그 값을 커밋에서 빼고 환경 변수로 옮긴다. 진짜 키였으면 키를 먼저 교체한다(이미 다른 곳에 복사됐을 수 있다).
- 오탐이면 `.gitleaks.toml`의 `[[allowlists]]`에 경로나 값 정규식을 더한다(`.gitleaksignore` 지문은 쓰지 않는다). 테스트 캐너리는 이름에 `Canary`를 넣으면 걸리지 않는다. 규칙 정규식을 바꾸면 `uv run pytest -q tests/test_secret_scan.py`.
- 훅을 켜지 않은 클론의 대안: `.github/workflows/secret-scan.yml`이 모든 push와 PR에서 전체 이력을 같은 설정으로 검사한다(gitleaks 버전·체크섬 고정, 값은 가린다). gitleaks를 올릴 때는 그 릴리스의 `gitleaks_<버전>_checksums.txt`에서 `linux_x64` 줄의 sha256을 `GITLEAKS_SHA256`에 넣는다.
- 덧붙여 GitHub Settings → Code security → Secret scanning·Push protection을 켜 두면 공급자 형식 키를 push 단계에서도 막는다(공개 레포 무료).
- SEC User-Agent(연락 이메일)는 키 모양이 아니라 gitleaks가 못 잡는다. 셸·secrets에만 둔다.

## 품질 확인 모드 (실제 Haiku, 로컬 DB만, #14)

통과/실패 판정이 아니라 Paul이 실제 Haiku의 카드 문장·검수 전 초안·검수 결과·보류함·분류를 눈으로 보는 명령이다. 기존 명령에 `--quality`만 붙인다.

```bash
# 위 "실행"의 eval 줄로 로컬 SUPABASE_DB_URL을 넣은 셸에서. 키는 명령 안에서 Keychain으로만 읽는다(값을 쓰거나 export하지 않는다)
cd backend && mkdir -p ../_workspace/issue-14/runs
# 시나리오(가짜 시세·공시·일정) + 실제 Haiku. 시나리오의 llm_replies는 쓰지 않는다
ANTHROPIC_API_KEY="$(security find-generic-password -s m30-anthropic -w)" \
  uv run python -m m30.pipeline 2026-10-16 --scenario scenarios/filings_day.json --quality > ../_workspace/issue-14/runs/<이름>.txt 2>&1
# 실제 EDGAR 공시 + 실제 Haiku. 시세는 항상 없이 돈다(TIINGO_API_KEY가 있어도 부르지 않는다: 무료 키 시간당 50회 보호)
ANTHROPIC_API_KEY="$(security find-generic-password -s m30-anthropic -w)" \
SEC_USER_AGENT="<app name> <contact email>" \
  uv run python -m m30.pipeline --production 2026-10-22 --quality > ../_workspace/issue-14/runs/<이름>.txt 2>&1
```

- **로컬 DB에서만 돈다.** `--scenario`는 원래 로컬 전용이고, `--production --quality`는 DB가 로컬이 아니면 DB·SEC에 닿기 전에 `--quality는 로컬 DB에서만 씁니다`로 exit 2. 카드 문장을 찍는 유일한 출력이라 Actions(원격 DB, 공개 로그)에서는 돌지 않는다. `ANTHROPIC_API_KEY`가 없으면 DB에 붙기 전에 `ANTHROPIC_API_KEY is not set`으로 exit 2.
- 출력은 `_workspace/`(git에 안 올라감)로 바로 받는다. pytest는 로컬 DB를 비우므로 측정 실행과 출력 확인 사이에 pytest를 돌리지 않는다. 실행은 그 날짜의 로컬 카드를 다시 쓴다(로컬 웹 미리보기가 같은 DB를 본다).
- **출력 파일에는 검수 전 모델 문장이 들어 있다. 레포가 공개라 이슈·PR에 그대로 붙이지 않고 `_workspace/`(gitignore 대상)에만 둔다.**
- 호출 수 상한은 운영과 같다(`llm_calls=`, 커버 범위 × 4 + 분류 묶음 수). 실제 비용이 든다.
- `scenarios/classify_probe.json`: 가상 회사 Litware(`LTWR`) 공시 8건, 분류 중요도 규칙 확인용(거래일 2026-10-16). `llm_replies`가 없어 `--quality`로만 돈다. 로컬 커버 범위에 `LTWR` 행이 남는다(다음 pytest가 비운다).
- 기존 요약 줄 뒤에 품질 블록이 붙는다. 글자 칸은 JSON 문자열(따옴표·`\n`·제어 문자 이스케이프)이다. 줄 머리는 고정이라 `grep '^  draft1 '`처럼 셀 수 있다.

| 줄 | 뜻 |
| --- | --- |
| `quality <거래일> classify=… newsline=… review=… prices=scenario\|none` | 블록 시작. 쓴 모델과 시세 출처 |
| `card <티커>` 아래 `  news`·`  event`·`  price <상태> "<카드 문구>"` | 저장된 카드의 세 줄(티커 순). 줄이 없으면 `- -` |
| `  draft1 <ok\|문제 코드> "<문장>"` | 첫 시도 초안(검수 전, 꼬리표 없음). 소식 있는 종목만. 문장이 없으면 `-` |
| `  draft2 "<문장>"` | 재생성한 경우의 마지막 LLM 문장 |
| `  review <pass\|hold:단계>[+retry] <규칙 \| …>` | 검수 결과. 규칙 읽는 법은 위 "보류함 `rules` 읽는 법". 1차 통과면 `-` |
| `lines news\|event\|price checked_found=… checked_none=… delayed=… unsupported=…` | 데이터 상태별 줄 수(있음·없음·지연·미지원) |
| `review_counts pass_first=… pass_retry=… replaced=… retried=…` | 첫 시도 통과 / 재생성 뒤 통과 / 대체 줄 / 재생성한 종목 수 |
| `hold <티커> <단계> <상태> <접수번호>` | 보류함 행(정정 행 포함). 없으면 `hold -` |
| `classify <티커> <접수번호> <종류>/<중요도> opinion=…` 또는 `unclassified=<사유>` | 분류 행. 없으면 `classify -` |
| `classify_counts kinds … importance … opinion=… unclassified=…` | 분류 분포 |
