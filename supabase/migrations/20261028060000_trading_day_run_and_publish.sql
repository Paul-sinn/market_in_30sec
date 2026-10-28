-- #16 거래일 달력·실행 잠금·발행 중단. 추가만: 운영 main 코드와 호환(새 컬럼은 null 허용·기본값, 새 테이블은 새 코드만 씀)

alter table public.stock_card
  -- 등락률·세 번째 줄이 다루는 종가 날짜(직전 거래일). 파이프라인이 달력으로 채운다. null = 이 컬럼 전 카드
  add column previous_trading_day date check (previous_trading_day < trading_day),
  -- 발행 중단: 데이터는 두고 웹 노출·알림 후보에서 뺀다. 사람이 대시보드에서 켠다. 파이프라인은 쓰지 않는다
  add column publish_suspended boolean not null default false;

-- 실행 기록: 한 실행 한 행. finished_at null = 진행 중이거나 죽음 → 다음 실행이 이어 한다. #17이 건수 컬럼을 더한다
create table public.pipeline_run (
  id          bigint generated always as identity primary key,
  trading_day date not null,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  constraint finished_after_start check (finished_at >= started_at)
);
create index pipeline_run_day on public.pipeline_run (trading_day, started_at);

-- DB 접근은 서버(service_role)만 (ADR-0003). 실행 기록은 지우지 않는다
alter table public.pipeline_run enable row level security;
revoke all on public.pipeline_run from anon, authenticated, service_role;
revoke all on sequence public.pipeline_run_id_seq from anon, authenticated;
grant select, insert on public.pipeline_run to service_role;
grant update (finished_at) on public.pipeline_run to service_role;
