-- #60 분기 작업(P4a): 10-K 원문과 업종 코드. 추가만: 새 표 하나, coverage 새 열 하나. 기존 sec_filing(8-K 전용, 첫 번째 줄 분류 대상)은 건드리지 않는다

-- SEC 업종 코드(SIC 4자리). 분기 작업이 회사 submissions JSON에서 채운다(이 열만 고친다).
-- null = 아직 안 채움, ETF(CIK 없음), SEC가 주지 않음. 연관 종목 같은 업종(peer, #64)의 입력
alter table public.coverage
  add column sic text check (sic ~ '^[0-9]{4}$');

-- 10-K 원문: 접수번호마다 한 행, 처음 받은 그대로 둔다(같은 접수번호는 다시 받지 않는다).
-- body = 주 문서(TYPE 10-K)의 글자(태그를 뗀 원문, 블록마다 줄바꿈, 앞 1,000,000자). 첨부·그림·XBRL은 저장하지 않는다.
-- shortcut: 원격 무료 한도(500MB). 연 약 60~100MB(압축 후 추정). 한도에 가까우면 Item 1만 남기거나 유료 플랜으로
create table public.sec_annual_report (
  accession   text primary key check (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  cik         text not null check (cik ~ '^[0-9]{10}$'),  -- 받은 회사(공동 제출 10-K는 처음 받은 회사)
  accepted_at timestamptz not null,                       -- SEC-HEADER ACCEPTANCE-DATETIME(동부 벽시계)
  received_at timestamptz not null default now(),
  body        text not null check (body <> '')            -- 길이 상한은 코드(ANNUAL_REPORT_BODY_MAX)가 지킨다: 상한을 바꿀 때 제약 drop이 필요 없게
);

-- DB 접근은 서버(service_role)만 (ADR-0003). 원문은 고치지도 지우지도 않는다
alter table public.sec_annual_report enable row level security;
revoke all on public.sec_annual_report from anon, authenticated, service_role;
grant select, insert on public.sec_annual_report to service_role;
-- coverage는 RLS·권한이 이미 걸려 있다(표 단위라 새 열에도 적용된다). service_role은 이미 update가 있다
