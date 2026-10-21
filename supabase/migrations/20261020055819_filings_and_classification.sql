-- 공시 제출 회사의 SEC CIK(10자리 0 채움). 같은 회사의 여러 티커(GOOGL/GOOG)는 같은 값. null = 공시 출처 미지원(ETF 등)
alter table public.coverage
  add column cik text check (cik ~ '^[0-9]{10}$');

-- 8-K 원본. payload는 받은 그대로. 나머지 열은 조회·연결용
create table public.sec_filing (
  accession   text primary key check (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  cik         text not null check (cik ~ '^[0-9]{10}$'),
  form        text not null check (form in ('8-K', '8-K/A')),
  accepted_at timestamptz not null,
  items       text[] not null,
  trading_day date not null,          -- 처음 받은 실행의 거래일 = 이 공시가 새 소식인 카드
  received_at timestamptz not null default now(),
  payload     text not null
);

-- 지표 발표 일정 원본
create table public.indicator_release (
  name        text not null check (name <> ''),
  released_at timestamptz not null,
  trading_day date not null,
  received_at timestamptz not null default now(),
  payload     text not null,
  primary key (name, released_at)
);

create type public.unclassified_reason as enum ('batch_failed', 'missing', 'unknown_ticker', 'invalid');

-- 공시 × 연결 티커. 분류됨(종류·중요도·의견글) 또는 미분류(사유) 한쪽만
create table public.filing_classification (
  accession    text not null references public.sec_filing (accession),
  ticker       text not null references public.coverage (ticker),
  kind         text check (kind in ('earnings', 'guidance', 'deal', 'leadership', 'capital_return',
                                    'financing', 'legal', 'restructuring', 'product', 'other')),   -- U1. models.NewsKind와 같게
  importance   smallint check (importance between 1 and 5),                                     -- U2. models.IMPORTANCE_MAX와 같게
  is_opinion   boolean,
  unclassified public.unclassified_reason,
  primary key (accession, ticker),
  constraint classified_xor_unclassified check (
    (unclassified is null and kind is not null and importance is not null and is_opinion is not null)
    or (unclassified is not null and kind is null and importance is null and is_opinion is null)
  )
);

-- DB 접근은 서버(service_role)만 (ADR-0003)
alter table public.sec_filing            enable row level security;
alter table public.indicator_release     enable row level security;
alter table public.filing_classification enable row level security;
revoke all on public.sec_filing, public.indicator_release, public.filing_classification from anon, authenticated;
grant select, insert, update, delete on public.sec_filing, public.indicator_release, public.filing_classification to service_role;
