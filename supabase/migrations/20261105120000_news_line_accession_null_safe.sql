-- #77 축소판(news_line_status null)에서 = 비교가 null이 돼 접수번호가 통과하던 빈틈을 막는다. 의미는 그대로(확인함·있음 줄에만 출처 공시)
-- 데이터 update 없음. 원격 위반 행 0개 확인(2026-11-05). news_line_filing_count_only_found(#63)와 같은 null 안전 비교
alter table public.stock_card
  drop constraint news_line_accession_only_found,
  add constraint news_line_accession_only_found check (
    news_line_accession is null or news_line_status is not distinct from 'checked_found'
  );
