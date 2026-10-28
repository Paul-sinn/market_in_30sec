-- #38 내 종목이 있는 유저도 계정 삭제(auth.admin.deleteUser)가 된다. 이력도 같이 지워진다(의도).
-- 삭제는 supabase_auth_admin이 auth.users를 지우고 cascade한다. cascade 쿼리와 BEFORE 트리거는 테이블 소유자 권한으로 돌지만,
-- AFTER 트리거(log_my_stock_change)는 바깥 문장 끝에 그 역할(security invoker)로 돌아 user_local_date에서 42501이 났다.
-- 이때 프로필은 이미 지워져 user_local_date가 null → 이력을 쓰지 않고 끝난다. 거기까지 가는 권한만 준다.
-- user_profile은 RLS가 켜져 있고 이 역할의 정책이 없어 읽어도 0행이다(BYPASSRLS 없음): 열 권한만으로 프로필 값은 보이지 않는다
grant execute on function public.user_local_date(uuid, timestamptz) to supabase_auth_admin;
grant select (user_id, timezone, day_timezone, day_timezone_until) on public.user_profile to supabase_auth_admin;
