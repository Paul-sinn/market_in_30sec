-- #8 유저 프로필·내 종목·내 종목 이력·기본 종목. 내 종목 규칙은 트리거가 지킨다(쓰는 서버가 Python·Next.js 둘)

create type public.plan as enum ('free', 'plus');              -- GLOSSARY Free / Plus
create type public.my_stock_change as enum ('add', 'remove');  -- 교체 = 삭제(HANDOFF 3-2)

create table public.user_profile (
  user_id             uuid primary key references auth.users (id) on delete cascade,  -- 앱 안 계정 삭제 = 전부 삭제
  plan                public.plan not null default 'free',
  timezone            text not null,        -- 기기 타임존(IANA). 트리거가 pg_timezone_names로 검사
  morning_push_time   time,                 -- timezone 기준 현지 시각. null = 고르지 않음 → 동부 9:00 (HANDOFF 3-2)
  day_timezone        text,                 -- 하루 기준 보류: day_timezone_until 전까지 하루는 이 타임존 자정 기준
  day_timezone_until  timestamptz,
  constraint day_timezone_pair check ((day_timezone is null) = (day_timezone_until is null))
);

create table public.my_stock (                -- GLOSSARY MyStocks. 현재 상태만
  user_id   uuid not null references public.user_profile (user_id) on delete cascade,
  ticker    text not null references public.coverage (ticker),  -- 커버 범위 밖은 넣을 수 없다
  locked    boolean not null default false,   -- 다운그레이드 잠금. 플랜 변경 트리거만 바꾼다
  added_at  timestamptz not null default now(),  -- "먼저 등록한 3개" 순서(added_at, ticker)
  primary key (user_id, ticker)
);

create table public.my_stock_history (        -- 추가 전용
  id           bigint generated always as identity primary key,
  user_id      uuid not null references public.user_profile (user_id) on delete cascade,
  change       public.my_stock_change not null,
  ticker       text not null references public.coverage (ticker),
  occurred_at  timestamptz not null default now(),
  local_date   date not null                  -- user_local_date(user_id, occurred_at). 교체 횟수·월간 성적표가 쓴다
);
create index my_stock_history_user_day on public.my_stock_history (user_id, local_date);

create table public.default_ticker (          -- GLOSSARY DefaultTicker
  quarter  date not null check (extract(day from quarter) = 1 and extract(month from quarter) in (1, 4, 7, 10)),
  ticker   text not null references public.coverage (ticker),
  primary key (quarter, ticker)
);

-- 어떤 시각의 "유저 하루"는 이 함수로만 센다. 보류 중(instant < day_timezone_until)이면 그 전 타임존 자정 기준. 프로필 없음 = null
create function public.user_local_date(uid uuid, instant timestamptz) returns date
language sql stable set search_path = '' as $$
  select (instant at time zone case when instant < p.day_timezone_until then p.day_timezone else p.timezone end)::date
    from public.user_profile p where p.user_id = uid
$$;

-- 기기 타임존은 IANA 이름만(신뢰 경계). 바꾸면 바로 저장하되 하루 기준은 다음 날부터(HANDOFF 3-2): 바꾼 순간의 타임존과
-- 그 타임존의 다음 자정을 보류 쌍에 넣는다. 보류 중(같은 날 또 바꿈)이면 쌍을 그대로 둔다. 타임존을 바꿔 횟수를 리셋하지 못하게
-- shortcut: 서쪽으로 24시간 넘게 옮기면(UTC+14 → UTC−11) 전날 칸이 다시 열린다, 실제로 보이면 max(local_date) 하한으로
-- shortcut: 자정이 없는 DST 타임존은 Postgres가 고른 시각을 쓴다
create function public.user_profile_timezone() returns trigger
language plpgsql set search_path = '' as $$
begin
  if not exists (select from pg_catalog.pg_timezone_names z where z.name = new.timezone) then
    raise exception using errcode = 'check_violation', constraint = 'timezone_name', message = 'timezone_name';
  end if;
  if tg_op = 'UPDATE' and new.timezone is distinct from old.timezone
     and (old.day_timezone_until is null or now() >= old.day_timezone_until) then
    new.day_timezone := old.timezone;
    new.day_timezone_until := (date_trunc('day', now() at time zone old.timezone) + interval '1 day') at time zone old.timezone;
  end if;
  return new;
end $$;

create trigger user_profile_timezone before insert or update of timezone on public.user_profile
  for each row execute function public.user_profile_timezone();

-- 무료 규칙(HANDOFF 3-2). 거절은 정해진 이름의 check_violation(스펙 #8 4-1 오류 계약, 메시지에 유저 값 없음)
create function public.my_stock_rules() returns trigger
language plpgsql set search_path = '' as $$
declare
  row_ public.my_stock;
  user_plan public.plan;
begin
  if tg_op = 'UPDATE' then  -- locked는 플랜 변경 트리거 안에서만(중첩 깊이 2). 고르기 화면 티켓이 다시 연다
    if pg_trigger_depth() < 2 then
      raise exception using errcode = 'check_violation', constraint = 'lock_by_plan_only', message = 'lock_by_plan_only';
    end if;
    return new;
  end if;
  if tg_op = 'INSERT' then row_ := new; else row_ := old; end if;
  -- 같은 유저의 쓰기를 한 줄로 세운다: 동시에 지워도 4번째가 통과하지 못하게. 삭제 횟수는 이력을 쓴 뒤 log_my_stock_change가 센다
  select p.plan into user_plan from public.user_profile p where p.user_id = row_.user_id for update;
  if tg_op = 'INSERT' and user_plan = 'free'
     and (select count(*) from public.my_stock s where s.user_id = row_.user_id and not s.locked) >= 3 then
    raise exception using errcode = 'check_violation', constraint = 'free_my_stock_limit', message = 'free_my_stock_limit';
  end if;
  return row_;
end $$;

create trigger my_stock_rules before insert or delete or update of locked on public.my_stock
  for each row execute function public.my_stock_rules();

-- 내 종목 이력: 실제로 넣고 뺀 행마다 한 줄(on conflict do nothing으로 건너뛴 추가는 남지 않는다). 잠금·해제는 남기지 않는다.
-- 무료 삭제 횟수도 여기서 센다: 한 문장으로 여러 행을 지우면 BEFORE 트리거는 모두 이력 쓰기 전에 돌아 횟수를 못 본다
create function public.log_my_stock_change() returns trigger
language plpgsql set search_path = '' as $$
declare
  row_ public.my_stock;
  day date;
begin
  if tg_op = 'INSERT' then row_ := new; else row_ := old; end if;
  day := public.user_local_date(row_.user_id, now());
  if day is null then  -- 프로필이 지워지는 중(계정 삭제 cascade): 이력도 같이 지워진다
    return null;
  end if;
  insert into public.my_stock_history (user_id, change, ticker, local_date)
    values (row_.user_id, case when tg_op = 'INSERT' then 'add' else 'remove' end::public.my_stock_change, row_.ticker, day);
  if tg_op = 'DELETE'
     and (select p.plan from public.user_profile p where p.user_id = row_.user_id) = 'free'
     and (select count(*) from public.my_stock_history h
           where h.user_id = row_.user_id and h.change = 'remove' and h.local_date = day) > 3 then
    raise exception using errcode = 'check_violation', constraint = 'free_swap_limit', message = 'free_swap_limit';
  end if;
  return null;
end $$;

create trigger log_my_stock_change after insert or delete on public.my_stock
  for each row execute function public.log_my_stock_change();

-- 다운그레이드 잠금(HANDOFF 3-8): free가 되면 먼저 등록한 3개만 남기고 잠근다, plus가 되면 전부 푼다. 행은 지우지 않는다
create function public.lock_my_stocks_on_plan_change() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.plan = 'free' then
    update public.my_stock s set locked = true
     where s.user_id = new.user_id and s.ticker not in (
       select f.ticker from public.my_stock f where f.user_id = new.user_id order by f.added_at, f.ticker limit 3);
  else
    update public.my_stock s set locked = false where s.user_id = new.user_id and s.locked;
  end if;
  return null;
end $$;

create trigger lock_my_stocks_on_plan_change after update of plan on public.user_profile
  for each row when (old.plan is distinct from new.plan) execute function public.lock_my_stocks_on_plan_change();

-- DB 접근은 서버(service_role)만 (ADR-0003). 유저별 분리는 서버가 검증한 토큰의 user id로 거른다
alter table public.user_profile     enable row level security;
alter table public.my_stock         enable row level security;
alter table public.my_stock_history enable row level security;
alter table public.default_ticker   enable row level security;
-- service_role도 먼저 회수: Supabase 기본 권한이 새 테이블에 전부를 준다
revoke all on public.user_profile, public.my_stock, public.my_stock_history, public.default_ticker
  from anon, authenticated, service_role;
revoke all on sequence public.my_stock_history_id_seq from anon, authenticated;
grant select, delete on public.user_profile to service_role;
grant insert (user_id, plan, timezone, morning_push_time), update (plan, timezone, morning_push_time)
  on public.user_profile to service_role;                 -- 보류 쌍은 트리거만. update 권한은 for update 잠금에도 필요
grant select, delete on public.my_stock to service_role;
grant insert (user_id, ticker), update (locked) on public.my_stock to service_role;  -- locked: 플랜 트리거가 service_role로 돈다
grant select, insert on public.my_stock_history to service_role;                      -- 이력은 추가만
grant select, insert, delete on public.default_ticker to service_role;
revoke execute on function public.user_local_date(uuid, timestamptz), public.log_my_stock_change(),
  public.my_stock_rules(), public.lock_my_stocks_on_plan_change(),
  public.user_profile_timezone() from public, anon, authenticated;
grant execute on function public.user_local_date(uuid, timestamptz) to service_role;  -- 트리거 안 호출은 service_role 권한
