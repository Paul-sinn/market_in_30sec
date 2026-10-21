create table public.coverage (
  ticker text primary key check (ticker ~ '^[A-Z][A-Z0-9.-]{0,9}$'),
  name   text not null check (name <> '')
);

create type public.card_status as enum ('normal', 'fallback');
create type public.line_status as enum ('checked_found', 'checked_none', 'delayed', 'unsupported');

create table public.stock_card (
  ticker        text not null references public.coverage (ticker),
  trading_day   date not null,
  status        public.card_status not null,
  change_pct    numeric(6,1),
  change_status public.line_status not null,

  news_line_text         text,
  news_line_status       public.line_status,
  news_line_checked_at   timestamptz,
  news_line_source_scope text,

  event_line_text         text,
  event_line_status       public.line_status,
  event_line_checked_at   timestamptz,
  event_line_source_scope text,

  price_fact_line_text         text,
  price_fact_line_status       public.line_status,
  price_fact_line_checked_at   timestamptz,
  price_fact_line_source_scope text,

  updated_at timestamptz not null default now(),

  primary key (ticker, trading_day),

  -- 등락률: 계산함(checked_found)일 때만 값이 있다. 확인함·없음은 등락률에 쓰지 않는다
  constraint change_pct_matches_status check (
    (change_status = 'checked_found' and change_pct is not null)
    or (change_status in ('delayed', 'unsupported') and change_pct is null)
  ),
  -- 축소판 = 첫 번째 줄 없이 발송된 카드 (GLOSSARY FallbackCard)
  constraint fallback_iff_no_news_line check ((status = 'fallback') = (news_line_status is null)),
  -- 줄은 네 컬럼이 모두 비었거나(아직 안 만듦) 모두 있다. 출처 범위는 미지원일 때만 비울 수 있다
  constraint news_line_complete check (
    (news_line_status is null and news_line_text is null and news_line_checked_at is null and news_line_source_scope is null)
    or (news_line_status is not null and news_line_text is not null and news_line_checked_at is not null
        and (news_line_status = 'unsupported' or news_line_source_scope is not null))
  ),
  constraint event_line_complete check (
    (event_line_status is null and event_line_text is null and event_line_checked_at is null and event_line_source_scope is null)
    or (event_line_status is not null and event_line_text is not null and event_line_checked_at is not null
        and (event_line_status = 'unsupported' or event_line_source_scope is not null))
  ),
  constraint price_fact_line_complete check (
    (price_fact_line_status is null and price_fact_line_text is null and price_fact_line_checked_at is null and price_fact_line_source_scope is null)
    or (price_fact_line_status is not null and price_fact_line_text is not null and price_fact_line_checked_at is not null
        and (price_fact_line_status = 'unsupported' or price_fact_line_source_scope is not null))
  )
);

-- DB 접근은 서버(service_role)만 (ADR-0003). anon·authenticated 정책은 만들지 않는다
alter table public.coverage   enable row level security;
alter table public.stock_card enable row level security;

-- anon 키는 앱에 들어가므로 직접 읽기를 열면 서버의 요청 제한·캐시·노출 판단을 우회한다 (HANDOFF 3-7).
-- Supabase가 public 새 테이블에 주는 기본 권한은 버전마다 달라 명시적으로 회수한다
revoke all on public.coverage, public.stock_card from anon, authenticated;
grant select, insert, update, delete on public.coverage, public.stock_card to service_role;
