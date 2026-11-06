-- #69 잠긴 자리 + 대기 등록(P8). 추가만: user_profile 새 열 하나, 새 표 하나, 새 함수 하나

-- 대기 등록(GLOSSARY Waitlist): Notify me를 처음 누른 시각. null = 등록 안 함. 웹이 null일 때만 채운다(다시 눌러도 처음 시각).
-- 이메일은 따로 받지 않는다: 출시 알림은 Auth 계정 이메일로 1회(개인정보처리방침)
alter table public.user_profile add column waitlisted_at timestamptz;
grant update (waitlisted_at) on public.user_profile to service_role;  -- insert 열 목록에는 넣지 않는다(프로필 생성 땐 늘 null)

-- 잠긴 자리·세 번째 줄 잠금 탭 수(HANDOFF 3-8). 일별 합계만: 유저 id·IP·시각 열 없음
create table public.locked_slot_tap (
  day  date    not null,  -- 탭한 동부 날짜(count_locked_slot_tap이 정한다)
  slot text    not null check (slot in ('earnings_summary', 'big_holders', 'related_lock')),  -- 웹 TAP_SLOTS와 같게
  taps integer not null check (taps > 0),
  primary key (day, slot)
);

-- 1 올리기. 한 문장(insert … on conflict do update)이라 동시 탭도 잃지 않는다. 날짜는 세션 시간대와 무관하게 동부 날짜.
-- security invoker(기본), 서버만 부른다
create function public.count_locked_slot_tap(slot text) returns void
language sql set search_path = '' as $$
  insert into public.locked_slot_tap as t (day, slot, taps)
  values ((now() at time zone 'America/New_York')::date, count_locked_slot_tap.slot, 1)
  on conflict (day, slot) do update set taps = t.taps + 1
$$;

-- DB 접근은 서버(service_role)만 (ADR-0003)
alter table public.locked_slot_tap enable row level security;
revoke all on public.locked_slot_tap from anon, authenticated, service_role;
grant select, insert, update on public.locked_slot_tap to service_role;  -- 증가 함수가 invoker 권한으로 쓴다. delete 없음
revoke execute on function public.count_locked_slot_tap(text) from public, anon, authenticated;
grant execute on function public.count_locked_slot_tap(text) to service_role;
