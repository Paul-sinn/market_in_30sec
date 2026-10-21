# 웹 MVP 계획 (2026-10-20)

사용자 지시: 빠르게 MVP를 만들어 테스트. 웹 SaaS 먼저, iOS는 나중. UI는 `ui-ux-pro-max` 스킬, 배포는 Vercel MCP. 이제부터 추천안으로 결정하고 묻지 않는다(사용자만 할 수 있는 일만 요청).

## 원칙
- ADR-0003 유지: 브라우저는 DB 직접 접근 금지. Next.js 서버 코드(server-only)만 Supabase에 접근, 비밀값은 Vercel 환경 변수
- 내용은 닫힌 쪽: 검수(#7) 안 거친 AI 문장은 화면에 안 나감
- 1단계는 Paul 혼자 보는 대시보드(Vercel 배포 보호). 회원가입·무료/Plus는 2단계

## 순서 (추천)
- [x] #22 검사기 미탐·오탐 수정 — c934342, 닫힘
- [x] #6 첫 번째 줄 생성 (가짜 LLM) — 닫힘. 검수(#7) 전 AI 문장은 카드에 저장 안 함
- [ ] #7 검수 + 보류함
- [x] 하네스: `web-dev` 에이전트 + `web-conventions` 스킬 추가, m30-dev에 웹 단계·자율 모드 → 사용자 `/reload-plugins` 대기
- [x] 웹 MVP 티켓 발행: 부모 #23 — W1 #24, W2 #25(← #24), W3 #26(← #25)
  - [x] #24 W1 — 68823b8, 닫힘. 웹 뼈대 + 카드 대시보드(Next.js App Router, 서버에서만 카드 읽기, ui-ux-pro-max 디자인, 데이터 상태 문구 그대로) — 로컬 Supabase로 개발, #6·#7과 병렬 가능
  - [ ] #25 W2 (원격 마이그레이션 적용, Basic Auth 6c81ad6 완료 → main 병합 → 사용자 Vercel import·env) 원격 Supabase에 마이그레이션 적용 + Vercel 배포(배포 보호) + 환경 변수(사용자가 service role 등 입력)
  - [ ] #26 W3 매일 파이프라인 실행기(GitHub Actions cron → 원격 Supabase, 비로컬 DB 가드에 명시적 운영 모드)
- [ ] #27 사용자 시안 적용(랜딩 `/` + `/cards`) — 진행 중
- [ ] #14 실제 Haiku(사용자: `ANTHROPIC_API_KEY`), #19 SEC EDGAR 실제(사용자: `SEC_USER_AGENT`) → 실제 공시로 첫 번째 줄
- [ ] #18 시세(무료 API 성능 검사 → Marketstack 구독은 사용자), #21 일정 출처 — 그 전까지 두·세 번째 줄은 `Update delayed`
- [ ] 2단계: #8 유저·내 종목, #9 무료/Plus 노출, 로그인(Google/Apple), #15 카드 API → SaaS
- [ ] #16·#17 운영(달력·잠금·실행 기록·Discord·gitleaks) → #20 10거래일 실험

## 사용자가 해야 할 일 (모아서 요청)
- `/compact` (지금), 하네스 추가 후 `/reload-plugins`
- 비밀값: Supabase service role 키 또는 DB URL(원격), `ANTHROPIC_API_KEY`, `SEC_USER_AGENT`(이메일 포함 문자열) — 채팅에 붙이지 말고 Vercel/GitHub 환경 변수에 직접
- 시세 벤더 구독(#18)

## 진행 기록
- 2026-10-20: #2~#5 완료·닫힘. #21(일정 출처)·#22(검사기) 발행. 원격 Supabase 마이그레이션 0개(아직 미적용)
- 2026-10-20: 하네스 웹 단계 추가, #23~#26 발행. MVP는 GitHub Actions cron(상시 AWS 서버는 실험 뒤)
