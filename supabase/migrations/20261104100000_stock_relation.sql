-- #64 연관 종목(P4b). 추가만: 새 표 둘. 기존 표·열은 건드리지 않는다

-- 10-K 하나에서 LLM이 뽑고 코드가 검증한 회사 언급. 10-K마다 한 행, 처음 쓴 그대로(같은 10-K는 다시 뽑지 않는다).
-- mentions = [{"name", "relation", "evidence"}] (모양은 코드가 지킨다). [] = 뽑았지만 없음. 행 없음 = 아직 안 뽑음(다음 실행).
-- 커버 범위와의 맞추기는 저장하지 않는다: stock_relation을 계산할 때 지금 커버 범위로 맞춘다
create table public.annual_report_mentions (
  accession    text primary key references public.sec_annual_report (accession),
  mentions     jsonb not null check (jsonb_typeof(mentions) = 'array'),
  extracted_at timestamptz not null default now()
);

-- 종목마다 연관 종목(GLOSSARY RelatedTicker). 분기 작업이 계산 결과가 바뀐 종목만 통째로 지우고 다시 쓴다.
-- rank 1~5 + (ticker, rank) 유일 = 종목당 5개 이하. ETF 제외는 코드가 지킨다(다른 표를 봐야 해서)
create table public.stock_relation (
  ticker           text not null references public.coverage (ticker),
  related_ticker   text not null references public.coverage (ticker),  -- 상대 회사의 대표 티커(그 CIK 티커 중 정렬 첫 번째)
  relation         text not null check (relation in ('competitor', 'customer', 'supplier', 'peer')),
  basis            text not null check (basis in ('own_10k', 'reverse_10k', 'sic')),
  rank             smallint not null check (rank between 1 and 5),
  source_accession text references public.sec_annual_report (accession),  -- own_10k = 내 10-K, reverse_10k = 상대 10-K
  evidence         text check (evidence <> ''),                           -- 그 10-K의 문장 그대로. 길이 상한은 코드(SENTENCE_MAX)
  updated_at       timestamptz not null default now(),
  primary key (ticker, related_ticker),
  unique (ticker, rank),
  check (related_ticker <> ticker),
  check ((basis = 'sic') = (relation = 'peer')),
  check ((basis = 'sic') = (source_accession is null)),
  check ((source_accession is null) = (evidence is null))
);

-- DB 접근은 서버(service_role)만 (ADR-0003)
alter table public.annual_report_mentions enable row level security;
alter table public.stock_relation         enable row level security;
revoke all on public.annual_report_mentions, public.stock_relation from anon, authenticated, service_role;
grant select, insert         on public.annual_report_mentions to service_role;  -- 고치지도 지우지도 않는다
grant select, insert, delete on public.stock_relation         to service_role;  -- 종목 단위로 지우고 다시 쓴다(update 없음)
