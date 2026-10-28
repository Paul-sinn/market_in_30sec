-- #10 ETF 카드 라이트 버전. 추가만: 운영 main 코드와 호환(새 컬럼은 null 허용, 새 테이블은 새 코드만 씀)

-- 편입 종목을 읽을 ETF. 일반 ETF = 자기 자신, 레버리지·인버스 = 같은 지수의 일반 ETF(TQQQ → QQQ). null = 편입 종목 소식 대상 아님.
-- FK는 걸지 않는다: 같은 테이블 안 참조라 upsert 순서가 꼬인다. 없는 티커를 가리키면 파이프라인이 미지원으로 처리한다
alter table public.coverage
  add column holdings_ticker text check (holdings_ticker ~ '^[A-Z][A-Z0-9.-]{0,9}$');

-- 편입 종목 보고(N-PORT). 보고 하나 = 한 행, 추가만. holdings = 코드가 읽은 행, payload = 원본 그대로
create table public.fund_holdings (
  accession   text primary key check (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  fund        text not null references public.coverage (ticker),
  period_end  date not null,
  holdings    jsonb not null check (jsonb_typeof(holdings) = 'array'),
  received_at timestamptz not null default now(),
  payload     text not null
);
create index fund_holdings_latest on public.fund_holdings (fund, period_end desc, received_at desc);

-- DB 접근은 서버(service_role)만 (ADR-0003). 원본은 처음 받은 그대로 둔다
alter table public.fund_holdings enable row level security;
revoke all on public.fund_holdings from anon, authenticated, service_role;
grant select, insert on public.fund_holdings to service_role;
