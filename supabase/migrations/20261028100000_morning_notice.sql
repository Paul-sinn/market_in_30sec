-- #12 아침 알림 문구: 유저·거래일마다 한 문장. 추가만(새 테이블은 새 코드만 쓴다)
create table public.morning_notice (
  user_id      uuid not null references public.user_profile (user_id) on delete cascade,  -- 계정 삭제 = 같이 삭제
  trading_day  date not null,
  text         text not null check (char_length(text) between 1 and 100),  -- 코드가 100자로 자르고 DB가 한 번 더 막는다
  created_at   timestamptz not null default now(),
  primary key (user_id, trading_day)
);

-- DB 접근은 서버(service_role)만 (ADR-0003). 같은 거래일 재실행은 그날 행을 지우고 다시 넣는다(아직 발송이 없다).
-- 계정 삭제 cascade는 FK 동작이라 테이블 소유자 권한으로 돈다: 트리거가 없어 supabase_auth_admin에 권한을 더 주지 않는다(#38과 다름)
alter table public.morning_notice enable row level security;
revoke all on public.morning_notice from anon, authenticated, service_role;
grant select, insert, delete on public.morning_notice to service_role;
