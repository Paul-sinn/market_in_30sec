-- #66 알아두기(P6, GLOSSARY QuietFact). 추가만: 새 표 하나, 새 함수 하나. 기존 표·열은 건드리지 않는다

-- 종목마다 알아두기 시리즈 하나 = 그 회사 최신 10-K에서 만든 사실, seq 순서(뭘 만드는지 → 어디서 돈을 버는지 → 어떤 시장).
-- 검수 통과분만 1부터 빈틈없이, 한 종목은 한 10-K(코드가 지킨다). 새 10-K면 분기 작업이 그 종목 행을 한 트랜잭션으로 지우고 다시 쓴다.
-- 유저별 진도는 저장하지 않는다(my_quiet_facts가 센다). ETF 제외는 코드가 지킨다(커버 범위를 봐야 해서)
create table public.quiet_fact (
  ticker           text not null references public.coverage (ticker),
  seq              smallint not null check (seq between 1 and 15),
  text             text not null check (text <> ''),  -- 사실 문장만. 앞 'Did you know:'·끝 '(Annual report)'는 웹 고정 문구. 규칙·길이는 코드(check_quiet_fact)
  source_accession text not null references public.sec_annual_report (accession),
  created_at       timestamptz not null default now(),
  primary key (ticker, seq)
);

-- 알아두기 진도(#66): 유저 uid의 잠기지 않은 내 종목마다, 마지막으로 넣은 날(이력 add 행 중 id가 가장 큰 행의 local_date)부터
-- day(대시보드 거래일)까지 그 종목의 조용한 날(첫 번째 줄 checked_none, 발행 중단 제외) 수 = 오늘 seq. 그 seq의 사실이 있는 종목만.
-- seq는 1~15라 종목마다 16행까지만 센다. 오늘 카드가 조용한 날인지는 웹(exposeCards)이 본다.
-- shortcut: 유저 현지 날짜(local_date)를 동부 거래일과 그대로 비교한다. 주말에 넣으면 월요일 카드가 1번
create function public.my_quiet_facts(uid uuid, day date) returns table (ticker text, fact text)
language sql stable set search_path = '' as $$
  select s.ticker, f.text
    from public.my_stock s
    cross join lateral (
      select h.local_date from public.my_stock_history h
       where h.user_id = s.user_id and h.ticker = s.ticker and h.change = 'add'
       order by h.id desc limit 1
    ) added
    cross join lateral (
      select count(*) as seq from (
        select from public.stock_card c
         where c.ticker = s.ticker and c.trading_day between added.local_date and my_quiet_facts.day
           and c.news_line_status = 'checked_none' and not c.publish_suspended
         limit 16
      ) quiet
    ) n
    join public.quiet_fact f on f.ticker = s.ticker and f.seq = n.seq
   where s.user_id = my_quiet_facts.uid and not s.locked
$$;

-- DB 접근은 서버(service_role)만 (ADR-0003)
alter table public.quiet_fact enable row level security;
revoke all on public.quiet_fact from anon, authenticated, service_role;
grant select, insert, delete on public.quiet_fact to service_role;  -- 종목 단위로 지우고 다시 쓴다(update 없음)
revoke execute on function public.my_quiet_facts(uuid, date) from public, anon, authenticated;
grant execute on function public.my_quiet_facts(uuid, date) to service_role;
