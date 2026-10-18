# market_in_30sec — 30초 종목 리포트 + AI 아레나

기준 문서: `docs/HANDOFF.md`(결정), `GLOSSARY.md`(용어), `docs/adr/`(되돌리기 어려운 결정). `docs/service-decisions.md`는 HANDOFF보다 오래됐다. 둘이 다르면 HANDOFF를 따른다.

## 하네스: 30초 종목 리포트 앱 개발

**목표:** HANDOFF 7장 개발 순서를 설계 → 구현 → 검증(문구 검수 + QA) 흐름으로 진행한다.

**호출 조건:** 이 앱의 기능 구현·수정·다음 개발 단계 진행을 요청받으면 `m30-dev` 스킬을 사용한다. 단순 질문이나 문서 수정에는 직접 답해도 된다.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
| --- | --- | --- | --- |
| 2026-10-17 | Harness v2로 처음 구성 | 전체 | - |
| 2026-10-18 | codex 리뷰·엣지 케이스·보안 결정을 conventions 스킬에 반영, 원격 Supabase 규칙 추가 | backend-conventions, ios-conventions, card-copy-rules, CLAUDE.md | 스펙 #1 개정 |
| 2026-10-17 | 에이전트 5명 로드 확인. copy-reviewer에 "항목 판정 먼저, 요약은 나중" 규칙 추가, 시뮬레이터 이름 수정, GLOSSARY 세 번째 줄 잠금 문구 명확화 | copy-reviewer, ios-conventions, GLOSSARY | 스모크 테스트에서 요약 숫자 오류, 없는 시뮬레이터 이름, 정의 모호함 발견 |

## 원격 Supabase 규칙

- 읽기 조회(테이블·로그·보안 어드바이저)는 묻지 않고 해도 된다
- 스키마 변경은 마이그레이션 파일로 만들고, 로컬 Supabase 테스트를 통과한 뒤, 사용자 확인을 받고 원격에 적용한다
- 데이터 수정·삭제 SQL은 항상 사용자 확인 후 실행한다
- 자동 테스트는 로컬 Supabase에서만 돈다. 원격은 실데이터 실험용이다

## 실수 기록

실수나 실패가 생기면 한 줄 추가: `날짜 — 증상 → 원인 → 교훈`

## Agent skills

### Issue tracker

Issues live in GitHub Issues for Paul-sinn/market_in_30sec (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
