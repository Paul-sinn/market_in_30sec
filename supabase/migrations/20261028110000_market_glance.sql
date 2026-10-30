-- #11 시장 한눈에. 추가만: 운영 main 코드와 호환
-- 거래일마다 한 행, 모든 유저 공용. 줄 모양은 stock_card와 같다(line_status, 확인 시각, 출처 범위)
create table public.market_glance (
  trading_day date primary key,

  close_line_text         text not null,
  close_line_status       public.line_status not null,
  close_line_checked_at   timestamptz not null,
  close_line_source_scope text,

  indicator_line_text         text not null,
  indicator_line_status       public.line_status not null,
  indicator_line_checked_at   timestamptz not null,
  indicator_line_source_scope text,

  market_news_line_text         text not null,
  market_news_line_status       public.line_status not null,
  market_news_line_checked_at   timestamptz not null,
  market_news_line_source_scope text,

  -- 검수에 걸려 Update delayed로 대체된 소식 줄의 기록. 웹은 읽지 않는다
  market_news_hold_draft text check (market_news_hold_draft <> ''),
  market_news_hold_rules text[],

  updated_at timestamptz not null default now(),

  constraint close_line_scope       check (close_line_status = 'unsupported' or close_line_source_scope is not null),
  constraint indicator_line_scope   check (indicator_line_status = 'unsupported' or indicator_line_source_scope is not null),
  constraint market_news_line_scope check (market_news_line_status = 'unsupported' or market_news_line_source_scope is not null),
  constraint market_news_hold check (
    (market_news_hold_rules is null and market_news_hold_draft is null)
    -- coalesce: cardinality(null)은 null이라 CHECK를 통과한다(규칙 없이 초안만 남는 행)
    or (coalesce(cardinality(market_news_hold_rules), 0) > 0 and market_news_line_status = 'delayed')
  )
);

-- 시장 전체 소식 원본(받은 그대로). (출처, 키)로 중복 제거, 추가만
create table public.market_news_item (
  source       text not null check (source <> ''),
  key          text not null check (key <> ''),
  published_at timestamptz not null,
  trading_day  date not null,          -- 처음 받은 실행의 거래일
  received_at  timestamptz not null default now(),
  payload      text not null,
  primary key (source, key)
);

-- DB 접근은 서버(service_role)만 (ADR-0003)
alter table public.market_glance    enable row level security;
alter table public.market_news_item enable row level security;
revoke all on public.market_glance, public.market_news_item from anon, authenticated, service_role;
grant select, insert, update on public.market_glance to service_role;   -- 재실행 = upsert. 지우지 않는다
grant select, insert on public.market_news_item to service_role;        -- 원본은 추가만
