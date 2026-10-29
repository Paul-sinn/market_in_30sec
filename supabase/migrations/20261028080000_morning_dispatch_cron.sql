-- #43 아침 실행 시각 보장. GitHub 예약 실행이 매일 4~7시간 늦어서 pg_cron이 정시(평일 09:17 UTC)에 morning.yml workflow_dispatch를 부른다.
-- GitHub schedule은 예비로 남는다(늦게 오면 CLI가 ALREADY_DONE으로 끝냄). 추가만: 테이블·운영 코드 변경 없음
create extension if not exists pg_cron;  -- Supabase 기본 위치(pg_catalog). 작업 표는 cron 스키마
create extension if not exists pg_net with schema extensions;  -- 함수는 net 스키마. public에 두지 않는다(lint)

-- 토큰은 Vault(github_dispatch_token)에서만 읽는다. 없으면 아무것도 보내지 않는다(null).
-- cron 작업 명령에는 이 함수 이름만 있어서 cron.job·job_run_details에 토큰·헤더가 남지 않는다.
-- security invoker(기본): cron이 postgres로 부르고, postgres는 Vault를 읽을 수 있다
create function public.dispatch_morning_workflow() returns bigint
language plpgsql set search_path = '' as $$
declare
  token text;
begin
  select decrypted_secret into token from vault.decrypted_secrets where name = 'github_dispatch_token';
  if coalesce(token, '') = '' then
    return null;
  end if;
  return net.http_post(
    url := 'https://api.github.com/repos/Paul-sinn/market_in_30sec/actions/workflows/morning.yml/dispatches',
    body := '{"ref":"main"}'::jsonb,
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || token,
      'Accept', 'application/vnd.github+json',
      'Content-Type', 'application/json',  -- headers를 주면 pg_net 기본값(Content-Type)이 사라진다
      'User-Agent', 'market_in_30sec-morning-dispatch'
    )
  );
end;
$$;

-- cron(postgres = 소유자)만 부른다. Supabase 기본 권한이 public 함수에 준 실행 권한을 거둔다(PostgREST rpc로 못 부르게)
revoke execute on function public.dispatch_morning_workflow() from public, anon, authenticated, service_role;

-- 같은 이름이면 pg_cron이 덮어쓴다(재적용해도 작업 하나). 시각은 UTC(cron.timezone 기본값) = morning.yml schedule과 같은 시각
select cron.schedule('morning_dispatch', '17 9 * * 1-5', 'select public.dispatch_morning_workflow()');
