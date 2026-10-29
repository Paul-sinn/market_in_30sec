# 웹 MVP 계획 (2026-10-20)

사용자 지시: 빠르게 MVP를 만들어 테스트. 웹 SaaS 먼저, iOS는 나중. UI는 `ui-ux-pro-max` 스킬, 배포는 Vercel MCP. 이제부터 추천안으로 결정하고 묻지 않는다(사용자만 할 수 있는 일만 요청).

## 원칙
- ADR-0003 유지: 브라우저는 DB 직접 접근 금지. Next.js 서버 코드(server-only)만 Supabase에 접근, 비밀값은 Vercel 환경 변수
- 내용은 닫힌 쪽: 검수(#7) 안 거친 AI 문장은 화면에 안 나감
- 1단계는 Paul 혼자 보는 대시보드(Vercel 배포 보호). 회원가입·무료/Plus는 2단계

## 순서 (추천)
- [x] #22 검사기 미탐·오탐 수정 — c934342, 닫힘
- [x] #6 첫 번째 줄 생성 (가짜 LLM) — 닫힘. 검수(#7) 전 AI 문장은 카드에 저장 안 함
- [x] #7 검수 + 보류함 — f5d6906, 닫힘, 원격 마이그레이션 적용
- [x] 하네스: `web-dev` 에이전트 + `web-conventions` 스킬 추가, m30-dev에 웹 단계·자율 모드 → 사용자 `/reload-plugins` 대기
- [x] 웹 MVP 티켓 발행: 부모 #23 — W1 #24, W2 #25(← #24), W3 #26(← #25)
  - [x] #24 W1 — 68823b8, 닫힘. 웹 뼈대 + 카드 대시보드(Next.js App Router, 서버에서만 카드 읽기, ui-ux-pro-max 디자인, 데이터 상태 문구 그대로) — 로컬 Supabase로 개발, #6·#7과 병렬 가능
  - [x] #25 W2 — 닫힘. 운영 https://web-theta-olive-25.vercel.app (Basic Auth). 원격 Supabase에 마이그레이션 적용 + Vercel 배포(배포 보호) + 환경 변수(사용자가 service role 등 입력)
  - [ ] #26 W3 (설계 중) 매일 파이프라인 실행기(GitHub Actions cron → 원격 Supabase, 비로컬 DB 가드에 명시적 운영 모드)
- [x] #27 사용자 시안 적용(랜딩 `/` + `/cards`) — 60d7984, 닫힘. main 병합 PR #28
- [ ] #19 SEC EDGAR 실제 어댑터 — 구현 중
- [ ] #14 실제 Haiku(사용자: `ANTHROPIC_API_KEY`), #19 SEC EDGAR 실제(사용자: `SEC_USER_AGENT`) → 실제 공시로 첫 번째 줄
- [ ] #18 시세(무료 API 성능 검사 → Marketstack 구독은 사용자), #21 일정 출처 — 그 전까지 두·세 번째 줄은 `Update delayed`
- [ ] 2단계: #8 유저·내 종목, #9 무료/Plus 노출, 로그인(Google/Apple), #15 카드 API → SaaS
  - [x] #8 유저·내 종목·교체 제한·생성 대상 — PR #35, 닫힘(2026-10-28). DB 트리거가 규칙을 지킴(ADR-0004), 원격 마이그레이션 적용. 다음: 로그인 + 내 종목 고르기 화면(티켓 없음)
  - [x] 스펙 #36 → #37 Google 로그인·유저 프로필, #38 내 종목 고르기·빼기 — PR #39, 닫힘(2026-10-28). 남은 것: 사용자 Google 로그인 설정(`web/README.md`) 후 운영 수동 확인
  - [x] #9 무료/Plus 줄 노출 — PR #40, 닫힘(2026-10-28)
- [x] #16 거래일 달력·실행 잠금·이어 하기·발행 중단·종가 날짜 라벨 — PR #41, 닫힘
- [x] #10 ETF 카드(상위 편입 종목 SEC N-PORT) — PR #42, 닫힘
- [x] #43 아침 실행 시각 보장(Supabase pg_cron → workflow_dispatch) — PR #44, 닫힘. 10-29 09:17:01 UTC 정시 실행 성공, GitHub 스케줄 대비 실행은 `ALREADY_DONE`
- [x] #17 실행 기록·Discord 요약·gitleaks — PR #45, 닫힘
- [x] #12 아침 알림 문구 — PR #46, 닫힘
- [ ] #11 시장 한눈에 — **보류(피봇)**. 백엔드 중간 작업은 `wip-11-market-glance` 브랜치(테스트 미실행, 원격 미적용, 로컬 DB에서도 되돌림). 설계 `_workspace/issue-11/01_architect_spec.md`(로컬)
- [ ] 다음: #18·#21·#20(사람 몫), 커버 범위 확대(#20에서), 푸시 발송·즉시 생성(#15 후보) — 피봇 결정 후 다시 정리

## 피봇 인수인계 (2026-10-29)
사용자가 기능을 더 줄이는 피봇을 검토 중. 새 세션에서 이어 한다.
1. 새 세션 ①: `/grill-with-docs`로 뺄 기능 결정 → HANDOFF·GLOSSARY·ADR 고침 → 하네스 점검(`harness:harness`, 에이전트·스킬을 새 범위에 맞춤)
2. 재시작(에이전트 정의는 세션 시작 때만 읽힘) → 새 세션 ②: m30-dev로 리팩토링
- 현재 운영: 매 평일 아침 카드 15개 자동 생성(pg_cron 09:17 UTC), 웹 https://web-theta-olive-25.vercel.app
- 레포 루트 `debate.py`, `debate_*`, `gpt-context.md`, `docs/research/`는 사용자 파일, 커밋하지 않음

## 사용자 할 일 (2026-10-29 기준)
- Google 로그인 설정 3가지(Google Cloud OAuth 클라이언트, Supabase Auth Google 켜기·Email 끄기·URL, Vercel `SUPABASE_PUBLISHABLE_KEY`) → 운영 로그인·내 종목 확인
- Discord 웹훅 → `gh secret set DISCORD_WEBHOOK_URL --env production`
- Tiingo Commercial 구독 결정($50/월, 공개 시 Redistribution 필요) → 가격 줄
- `brew install gitleaks` 후 `git config core.hooksPath .githooks`
- GitHub dispatch 토큰 만료일(약 2027-10) 전에 갱신 → Vault `github_dispatch_token`
- [ ] #16·#17 운영(달력·잠금·실행 기록·Discord·gitleaks) → #20 10거래일 실험

## 사용자가 해야 할 일 (모아서 요청)
- `/compact` (지금), 하네스 추가 후 `/reload-plugins`
- 비밀값: Supabase service role 키 또는 DB URL(원격), `ANTHROPIC_API_KEY`, `SEC_USER_AGENT`(이메일 포함 문자열) — 채팅에 붙이지 말고 Vercel/GitHub 환경 변수에 직접
- 시세 벤더 구독(#18)

## 진행 기록
- 2026-10-20: #2~#5 완료·닫힘. #21(일정 출처)·#22(검사기) 발행. 원격 Supabase 마이그레이션 0개(아직 미적용)
- 2026-10-20: 하네스 웹 단계 추가, #23~#26 발행. MVP는 GitHub Actions cron(상시 AWS 서버는 실험 뒤)
- 2026-10-21: #6·#7·#24·#27 닫힘, #25 웹 보호 완료(사용자 Vercel import 대기), 원격 마이그레이션 4개. 다음: #19 EDGAR 실제 어댑터
