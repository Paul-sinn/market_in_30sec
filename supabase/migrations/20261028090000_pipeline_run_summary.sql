-- #17 실행 기록 요약. 추가만: null = 이 컬럼 전 실행이거나 끝나지 않은(죽은) 실행. finish_run이 finished_at과 한 번에 채운다
alter table public.pipeline_run
  add column failed  boolean,  -- 워크플로를 실패로 끝낸 실행(출처 실패·종목 예외·카드 0장)
  add column summary jsonb check (jsonb_typeof(summary) = 'object'),  -- 코드·건수·티커만(문장·가격·비밀값 없음)
  add constraint summary_when_finished check ((failed is null) = (summary is null) and (summary is null or finished_at is not null));
grant update (failed, summary) on public.pipeline_run to service_role;
