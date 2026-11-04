-- #57 실적 추정일(P3). 추가만: 새 표 둘. 기존 표·열은 건드리지 않는다

-- 실적 공시(8-K 중 Item 2.02, 정정 8-K/A 제외)의 헤더 접수 시각. 접수번호별로 한 번 읽어 저장한다.
-- 첫 번째 줄 분류 대상인 sec_filing과 섞지 않는다(이 표의 공시는 새 소식이 아니다). 원본은 저장하지 않는다
create table public.earnings_filing (
  accession   text primary key check (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  cik         text not null check (cik ~ '^[0-9]{10}$'),   -- 처음 읽은 CIK
  accepted_at timestamptz not null,                        -- SEC-HEADER ACCEPTANCE-DATETIME(동부 벽시계)
  received_at timestamptz not null default now()
);

-- 종목·거래일마다 그날 계산한 실적 추정일(GLOSSARY EarningsEstimate). 추정이 없으면(작년 같은 분기 공시 없음·ETF·출처 실패) 행이 없다.
-- estimate_day < trading_day = 추정일이 지났는데 실적 공시가 없음(두 번째 줄 No confirmed events found)
create table public.earnings_estimate (
  ticker          text not null references public.coverage (ticker),
  trading_day     date not null,
  estimate_day    date not null,                           -- 기준 공시 접수일(동부) + 364일
  timing          text not null check (timing in ('before_open', 'after_close', 'unknown')),
  basis_accession text not null references public.earnings_filing (accession),  -- 작년 같은 분기 실적 공시
  updated_at      timestamptz not null default now(),
  primary key (ticker, trading_day)
);

-- DB 접근은 서버(service_role)만 (ADR-0003)
alter table public.earnings_filing   enable row level security;
alter table public.earnings_estimate enable row level security;
revoke all on public.earnings_filing, public.earnings_estimate from anon, authenticated, service_role;
grant select, insert         on public.earnings_filing   to service_role;  -- 처음 읽은 시각을 고치지도 지우지도 않는다
grant select, insert, update on public.earnings_estimate to service_role;  -- 같은 거래일 재실행은 같은 값으로 덮는다
