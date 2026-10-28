-- #38 이미 내 종목인 종목을 다시 넣으면 아무 일도 없다(오류·이력 없음). 일반 insert와 on conflict do nothing(웹 upsert) 둘 다.
-- BEFORE 트리거는 중복 검사보다 먼저 돈다: 3개가 찬 무료 유저의 재추가가 free_my_stock_limit로 거절됐다. 바뀐 곳은 재추가 줄뿐
create or replace function public.my_stock_rules() returns trigger
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
  -- 재추가는 행을 건너뛴다(AFTER 이력 트리거도 돌지 않는다). 잠근 뒤에 봐서 같은 종목 두 번 누르기도 앞 커밋을 보고 건너뛴다
  if tg_op = 'INSERT' and exists (select from public.my_stock s where s.user_id = row_.user_id and s.ticker = row_.ticker) then
    return null;
  end if;
  if tg_op = 'INSERT' and user_plan = 'free'
     and (select count(*) from public.my_stock s where s.user_id = row_.user_id and not s.locked) >= 3 then
    raise exception using errcode = 'check_violation', constraint = 'free_my_stock_limit', message = 'free_my_stock_limit';
  end if;
  return row_;
end $$;
