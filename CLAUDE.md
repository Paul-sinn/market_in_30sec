# market_in_30sec — 30초 종목 리포트 + AI 아레나

기준 문서: `docs/HANDOFF.md`(결정), `GLOSSARY.md`(용어), `docs/adr/`(되돌리기 어려운 결정). `docs/service-decisions.md`는 HANDOFF보다 오래됐다. 둘이 다르면 HANDOFF를 따른다.

## 하네스: 30초 종목 리포트 앱 개발

**목표:** HANDOFF 7장 개발 순서를 설계 → 구현 → 검증(문구 검수 + QA) 흐름으로 진행한다.

**호출 조건:** 이 앱의 기능 구현·수정·다음 개발 단계 진행을 요청받으면 `m30-dev` 스킬을 사용한다. 단순 질문이나 문서 수정에는 직접 답해도 된다.

**전체 흐름:** 결정(`/grill-with-docs`) → 스펙(`/mattpocock-skills:to-spec`, GitHub 이슈) → 티켓(`/mattpocock-skills:to-tickets`, 하위 이슈 + 선행 관계) → 구현(`m30-dev #N`). to-spec·to-tickets는 모델이 부를 수 없어 사용자가 직접 입력한다. 스펙·티켓 단계도 이 하네스의 앞단이다.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
| --- | --- | --- | --- |
| 2026-10-17 | Harness v2로 처음 구성 | 전체 | - |
| 2026-10-17 | 에이전트 5명 로드 확인. copy-reviewer에 "항목 판정 먼저, 요약은 나중" 규칙 추가, 시뮬레이터 이름 수정, GLOSSARY 세 번째 줄 잠금 문구 명확화 | copy-reviewer, ios-conventions, GLOSSARY | 스모크 테스트에서 요약 숫자 오류, 없는 시뮬레이터 이름, 정의 모호함 발견 |
| 2026-10-18 | 티켓 기반 흐름으로 변경: m30-dev가 GitHub 티켓을 입력으로 받고 선행 티켓·라벨을 확인, 산출물은 `_workspace/issue-{N}/`. backend-dev는 TDD(스펙 #1의 테스트 입구 2곳), qa는 완료 기준 대조·최신 경계 사례·보안 확인 추가, architect는 티켓 범위만 | m30-dev, backend-dev, qa, architect | 스펙 #1·티켓 #2~#20 생성 후 하네스가 옛 흐름(스펙부터 새로 작성)에 머물러 있었음 |
| 2026-10-18 | codex 리뷰·엣지 케이스·보안 결정을 conventions 스킬에 반영, 원격 Supabase 규칙 추가 | backend-conventions, ios-conventions, card-copy-rules, CLAUDE.md | 스펙 #1 개정 |
| 2026-10-18 | 회고(harness:evolve): ① CLAUDE.md에 결정→스펙→티켓→구현 전체 흐름 ② m30-dev 0단계에 "결정 문서가 하네스보다 새로우면 점검 제안" 확인 ③ card-copy-rules에 새 고정 문구 절차 + 통과·차단 예시 파일 ④ m30-dev에 사용자 설명 방식(단계마다 무엇·왜, 용어 풀기) | CLAUDE.md, m30-dev, card-copy-rules | 하네스 존재를 사용자가 두 번 물음, 결정 변경 후 하네스가 옛 기준에 머묾, 금지어 검사 오탐 3회 반복, "p0 이뭐야"·"각 단계 뭘 왜 하는지 설명해줘" 요청 |
| 2026-10-18 | 테스트 입구에 "프로세스 출력"(보안 규칙 전용) 추가, DB 연결 실패 시 비밀번호 없는 예외 규칙 | backend-dev, backend-conventions | #2 qa에서 연결 실패 시 pytest 출력에 비밀번호 노출 발견, 이 규칙은 기존 입구 2곳으로 검사 불가 |
| 2026-10-18 | 금지어 검사 기준을 서버(`m30.copy_rules` + TOML)로 한 벌만 두고 스킬 스크립트는 실행기로. 예시 파일은 `backend/tests/copy_examples/`, 회귀 확인은 pytest. 프로세스 출력 입구에 "외부 패키지 없이 도는 스킬 실행기" 추가 | card-copy-rules, backend-conventions, backend-dev | #3 구현. 사용자 결정(입구 확장): copy-reviewer가 시스템 python3로 실행기를 부르므로 서버 의존 import가 섞이는 회귀를 자동으로 잡기 위해 |
| 2026-10-18 | 읽기 전용 에이전트 보고서 저장 규칙: Bash로 지정 파일 하나만 쓰고, 못 쓰면 답변 전문 → 메인이 그대로 저장 | qa, copy-reviewer, m30-dev | #3에서 qa가 "보고서 파일 작성 금지"로 판단해 파일을 안 씀(Write 도구 없음). 다음 단계는 파일 경로로 읽으므로 보고서가 빠질 뻔함 |
| 2026-10-18 | 세 번째 줄 기준값·우선순위·% 표기, 사실 없음 문구 `No additional price highlights`(데이터 오류는 지연과 구분), 극소액 배당 `<$0.0001/share`, `pipeline/lines`·`trading_day` 디렉터리 | card-copy-rules, backend-conventions | #4 사용자 결정(U1~U7, copy-reviewer 보류 2건) |

## 원격 Supabase 규칙

- 읽기 조회(테이블·로그·보안 어드바이저)는 묻지 않고 해도 된다
- 스키마 변경은 마이그레이션 파일로 만들고, 로컬 Supabase 테스트를 통과한 뒤, 사용자 확인을 받고 원격에 적용한다
- 데이터 수정·삭제 SQL은 항상 사용자 확인 후 실행한다
- 자동 테스트는 로컬 Supabase에서만 돈다. 원격은 실데이터 실험용이다

## 실수 기록

실수나 실패가 생기면 한 줄 추가: `날짜 — 증상 → 원인 → 교훈`

- 2026-10-18 — #2 qa가 변이 확인(코드를 일부러 망가뜨려 테스트가 잡는지 보기) 중 되돌리기를 두 번 놓침 → `backend/`가 아직 커밋 전(untracked)이라 `git diff`로 되돌림을 확인할 수 없었음 → 변이 확인은 구현을 커밋(또는 스냅샷)한 뒤에 하고, 끝나면 `git status`가 깨끗한지 확인
- 2026-10-18 — DB 연결 실패 시 pytest traceback에 비밀번호가 찍힘 → 접속 문자열을 지역 변수로 든 채 예외가 올라감 → 연결 실패는 비밀번호 없는 메시지로 `from None` 재발생(backend-conventions에 규칙화)

## Agent skills

### Issue tracker

Issues live in GitHub Issues for Paul-sinn/market_in_30sec (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
