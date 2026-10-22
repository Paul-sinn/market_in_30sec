-- #7 검수 + 보류함: 공시 보고 기준일, 카드 첫 번째 줄의 출처 공시, 보류함, 카드 수정 이력

-- EDGAR reportDate(8-K "Date of Report"). 8-K/A와 원래 공시를 잇는다. null = 출처가 주지 않음
alter table public.sec_filing add column report_date date;

-- 첫 번째 줄이 쓴 공시(통과·대체·재발행 줄). 데이터 상태 문구 줄은 null. 정정 공시가 오면 이 카드를 찾는다
alter table public.stock_card
  add column news_line_accession text references public.sec_filing (accession),
  add constraint news_line_accession_only_found check (news_line_accession is null or news_line_status = 'checked_found');

create type public.hold_stage as enum ('draft', 'numbers', 'copy_rules', 'fact_check', 'amended_filing');  -- models.HoldStage와 같게
create type public.hold_state as enum ('pending', 'edited', 'republished');                               -- models.HoldState와 같게

-- 보류함(GLOSSARY HoldQueue): 대체 줄로 나간 첫 번째 줄, 정정 공시가 온 발행 카드. 사람이 대시보드에서 사후 확인
create table public.hold_queue (
  ticker           text not null,
  trading_day      date not null,
  accession        text not null references public.sec_filing (accession),  -- 이 행을 만든 공시(검수 = 초안의 공시, 정정 = 8-K/A)
  stage            public.hold_stage not null,                               -- 마지막 시도가 걸린 단계
  draft_text       text,                                                     -- 원래 문장. null = 문장 없음·정정 행
  rules            text[] not null check (cardinality(rules) > 0),           -- 걸린 규칙
  replacement_text text,                                                     -- 카드에 들어간 대체 줄. 정정 행은 null
  state            public.hold_state not null default 'pending',
  edited_text      text check (edited_text <> ''),                           -- 사람이 쓴 첫 번째 줄(꼬리표 포함 전체)
  created_at       timestamptz not null default now(),
  primary key (ticker, trading_day, accession),
  foreign key (ticker, trading_day) references public.stock_card (ticker, trading_day),
  constraint replacement_iff_review check ((stage = 'amended_filing') = (replacement_text is null)),
  constraint amended_has_no_draft check (stage <> 'amended_filing' or draft_text is null),
  constraint edited_needs_text check (state = 'pending' or edited_text is not null)
);

-- 카드 수정 이력: 내용(시각 열 제외)이 바뀐 갱신마다 바뀌기 전 행 전체. 행 전체라 카드 열이 늘어도 이 코드는 그대로
create table public.stock_card_revision (
  id          bigint generated always as identity primary key,
  ticker      text not null,
  trading_day date not null,
  revised_at  timestamptz not null default now(),
  previous    jsonb not null
);

-- 확인 시각·갱신 시각만 바뀐 갱신(같은 입력 재실행)은 이력이 아니다. 첫 저장(insert)도 이력이 아니다
create function public.keep_card_revision() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (to_jsonb(old) - array['updated_at', 'news_line_checked_at', 'event_line_checked_at', 'price_fact_line_checked_at'])
     is distinct from
     (to_jsonb(new) - array['updated_at', 'news_line_checked_at', 'event_line_checked_at', 'price_fact_line_checked_at']) then
    insert into public.stock_card_revision (ticker, trading_day, previous) values (old.ticker, old.trading_day, to_jsonb(old));
  end if;
  return null;
end $$;

create trigger keep_card_revision after update on public.stock_card
  for each row execute function public.keep_card_revision();

-- 재발행: 보류함 행을 republished로 바꾸거나, republished인 행의 edited_text를 다시 고치면 그 카드의 첫 번째 줄 문구만 바꾼다.
-- 아침 알림은 건드리지 않는다
create function public.republish_from_hold_queue() returns trigger
language plpgsql set search_path = '' as $$
begin
  update public.stock_card set news_line_text = new.edited_text, updated_at = now()
   where ticker = new.ticker and trading_day = new.trading_day and news_line_status = 'checked_found';
  if not found then
    raise exception 'hold_queue %/%: card has no filing news line to republish', new.ticker, new.trading_day;
  end if;
  return null;
end $$;

create trigger republish_from_hold_queue after update of state, edited_text on public.hold_queue
  for each row when (new.state = 'republished'
                     and (old.state <> 'republished' or new.edited_text is distinct from old.edited_text))
  execute function public.republish_from_hold_queue();

-- DB 접근은 서버(service_role)만 (ADR-0003). 트리거 함수는 직접 부를 일이 없다
alter table public.hold_queue          enable row level security;
alter table public.stock_card_revision enable row level security;
-- service_role도 먼저 회수: Supabase 기본 권한이 새 테이블에 전부를 주면 이력이 추가 전용이 아니게 된다
revoke all on public.hold_queue, public.stock_card_revision from anon, authenticated, service_role;
revoke all on sequence public.stock_card_revision_id_seq from anon, authenticated;
grant select, insert, update, delete on public.hold_queue to service_role;
grant select, insert on public.stock_card_revision to service_role;  -- 이력은 추가만
revoke execute on function public.keep_card_revision(), public.republish_from_hold_queue() from public, anon, authenticated;
