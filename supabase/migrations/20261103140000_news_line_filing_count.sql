-- #63 카드 헤더(P2). 추가만: 첫 번째 줄이 다룬 공시 수(1등 + +N more). 읽는 쪽이 문장을 파싱하지 않게 저장한다.
-- 확인함·있음 줄에만 1 이상. 데이터 상태 문구 줄·축소판은 비운다.
-- #63 전 checked_found 카드는 비어 있다(데이터 update 없음) → news_line_accession_only_found처럼 한쪽 방향만 막는다.
-- is not distinct from: 축소판(news_line_status null)에서 = 비교가 null이 돼 check를 통과하지 않게
alter table public.stock_card
  add column news_line_filing_count integer,
  add constraint news_line_filing_count_only_found check (
    news_line_filing_count is null or (news_line_status is not distinct from 'checked_found' and news_line_filing_count >= 1)
  );
