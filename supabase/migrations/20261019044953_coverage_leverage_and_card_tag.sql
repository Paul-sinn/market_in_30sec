-- 레버리지·인버스 상품의 배율. 부호가 방향이다(음수 = 인버스). 일반 종목·일반 ETF는 null (HANDOFF 3-1)
alter table public.coverage
  add column leverage numeric(4,2) check (leverage > 1 or leverage < 0);

-- 카드에 붙는 태그 문구. coverage.leverage에서 코드가 만든다. 발행된 카드는 그날의 태그를 그대로 남긴다
alter table public.stock_card
  add column leverage_tag text check (leverage_tag <> '');

-- RLS·권한은 두 테이블에 이미 걸려 있다(테이블 단위라 새 컬럼에도 적용된다)
