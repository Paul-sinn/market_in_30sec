# Dashboard Page Overrides

> **PROJECT:** market_in_30sec
> **Page Type:** 카드 대시보드 (`/`, #24)

> Rules in this file **override** `../MASTER.md`. Only deviations are listed. 생성기 기본안(Enterprise Gateway 랜딩 섹션·CTA·hover lift·GSAP)은 이 화면에 맞지 않아 뺐다: 카드는 누를 수 없고, 투자 앱처럼 보이는 연출을 하지 않는다(HANDOFF 5장).

## Layout

- 모바일 우선 1열 → `md` 2열 → `xl` 3열. 최대 폭 `max-w-6xl`, 좌우 여백 16px(`sm` 이상 24px). 가로 스크롤 없음
- 순서: 작업 이름(작게) → 거래일 날짜(h1) → 카드 목록 → 페이지 하단 `Not investment advice`
- 카드: 머리(티커·종목명 | 등락률 + 아래 `Last close` 라벨) → 레버리지 태그(있으면) → 세 줄 → 하단 `Checked … ET · 출처 범위`(확인된 줄만, 없으면 하단 없음). 줄을 숨기지 않는다
- 읽기 실패(`app/error.tsx`): h1 `Cards could not be loaded` + `Try again` 버튼(높이 44px, 테두리, 키보드 포커스 외곽선 `foreground`). 하단 고지는 레이아웃에 남는다

## Color (MASTER 다크 팔레트 + 라이트 짝, 시스템 설정을 따른다)

| 토큰 (Tailwind) | Light | Dark | 용도 |
| --- | --- | --- | --- |
| `background` | `#F8FAFC` | `#020617` | 페이지 |
| `surface` | `#FFFFFF` | `#0E1223` | 카드 |
| `foreground` | `#0F172A` | `#F8FAFC` | 본문, 확인함·있음 줄, 보합 |
| `muted` | `#475569` | `#94A3B8` | 확인함·없음·지연·미지원 줄, 메타 |
| `border` | `#CBD5E1` | `#334155` | 카드·태그 테두리(장식) |
| `up` | `#15803D` | `#22C55E` | 상승 |
| `down` | `#B91C1C` | `#F87171` | 하락 (MASTER destructive `#EF4444`보다 대비 여유) |
| `warning` | `#B45309` | `#FBBF24` | 지연 아이콘 |

- 대비(surface 위): light muted 7.6 / up 5.0 / down 6.5, dark muted 7.3 / up 8.2 / down 6.7. 전부 4.5:1 이상
- Tailwind 기본 색은 `--color-*: initial`로 지웠다. 위 토큰만 쓴다. 컴포넌트에 hex·임의 값 클래스 금지(tests/guards.test.ts)
- 색만으로 뜻을 전하지 않는다: 등락률은 부호(`+`, `−`)가 항상 붙고, 줄 상태는 문구 자체가 말한다(아이콘은 장식)

## Typography

- MASTER: 제목 Fira Code / 본문 Fira Sans → 바꿈: 본문·제목 모두 **Fira Sans**, **Fira Code는 티커·등락률만**(고정폭 숫자). 코드 글꼴 제목은 "30초 안에 읽는" 화면에 딱딱하다
- 줄 문구 16px(`text-base`), 등락률 20px, 날짜 24px, 메타(종목명·태그·확인 시각) 14px

## Status display (줄 상태 → 표시 방식만)

| 상태 | 글자색 | 아이콘(aria-hidden) |
| --- | --- | --- |
| 확인함·있음 | foreground | 채운 점 |
| 확인함·없음 | muted | 빈 원 |
| 지연 | muted | 시계(warning) |
| 미지원 | muted | 가로줄 |

## Motion

- 카드 읽는 동안 스켈레톤(`motion-safe:animate-pulse`). 그 외 애니메이션 없음
