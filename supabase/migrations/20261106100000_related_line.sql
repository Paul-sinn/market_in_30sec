-- #67 세 번째 줄 연관 소식(P5). 추가만: stock_card 열 5개·제약 2개, hold_queue 열 1개·제약 1개.
-- 함수 2개를 create or replace(데이터 변경 없음): 수정 이력 비교에서 새 확인 시각 빼기, 재발행이 줄을 고르기

alter table public.stock_card
  add column related_line_text         text,
  add column related_line_status       public.line_status,
  add column related_line_checked_at   timestamptz,
  add column related_line_source_scope text,
  add column related_line_filing_count integer,  -- 다룬 공시 수 = 1등 + +N more. 무료 잠금 건수(2 related updates in Plus)
  -- 다른 줄과 같다: 넷 다 비었거나(#67 전 카드) 다 있다. 출처 범위는 미지원일 때만 비울 수 있다
  add constraint related_line_complete check (
    (related_line_status is null and related_line_text is null and related_line_checked_at is null and related_line_source_scope is null)
    or (related_line_status is not null and related_line_text is not null and related_line_checked_at is not null
        and (related_line_status = 'unsupported' or related_line_source_scope is not null))
  ),
  -- 건수는 확인함·있음 줄에만, 그때는 반드시(#67 전 행이 없어 양방향). is not distinct from: 상태 null에서 null이 돼 통과하지 않게(#77)
  add constraint related_line_filing_count_iff_found check (
    (related_line_status is not distinct from 'checked_found') = (related_line_filing_count is not null)
    and (related_line_filing_count is null or related_line_filing_count >= 1)
  );

-- 보류함 행이 대체한 줄(models.HoldLine과 같게). 지금까지의 행은 전부 첫 번째 줄
alter table public.hold_queue
  add column line text not null default 'news' check (line in ('news', 'related')),
  add constraint amended_is_news check (line = 'news' or stage <> 'amended_filing');  -- 정정 공시 표시는 첫 번째 줄만

-- 확인 시각·갱신 시각만 바뀐 갱신은 이력이 아니다(세 번째 줄 확인 시각 추가)
create or replace function public.keep_card_revision() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (to_jsonb(old) - array['updated_at', 'news_line_checked_at', 'event_line_checked_at', 'price_fact_line_checked_at', 'related_line_checked_at'])
     is distinct from
     (to_jsonb(new) - array['updated_at', 'news_line_checked_at', 'event_line_checked_at', 'price_fact_line_checked_at', 'related_line_checked_at']) then
    insert into public.stock_card_revision (ticker, trading_day, previous) values (old.ticker, old.trading_day, to_jsonb(old));
  end if;
  return null;
end $$;

-- 재발행: 행의 line이 고른 줄 문구만 바꾼다. 아침 알림은 건드리지 않는다
create or replace function public.republish_from_hold_queue() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.line = 'related' then
    update public.stock_card set related_line_text = new.edited_text, updated_at = now()
     where ticker = new.ticker and trading_day = new.trading_day and related_line_status = 'checked_found';
  else
    update public.stock_card set news_line_text = new.edited_text, updated_at = now()
     where ticker = new.ticker and trading_day = new.trading_day and news_line_status = 'checked_found';
  end if;
  if not found then
    raise exception 'hold_queue %/%: card has no filing % line to republish', new.ticker, new.trading_day, new.line;
  end if;
  return null;
end $$;

-- create or replace는 권한을 유지하지만 명시적으로 다시 회수한다(기본 권한 변화 대비). security definer 아님
revoke execute on function public.keep_card_revision(), public.republish_from_hold_queue() from public, anon, authenticated;
