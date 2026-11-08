# Dashboard Page (`/cards`)

> **PROJECT:** market_in_30sec · **기준:** #93(2026-11-07 사용자 결정, 밝고 둥근 초보 친화 스타일). #27 어두운 시안·`../MASTER.md`(#24)는 대체됐다.
> 값은 `web/src/app/globals.css` 토큰으로만 쓴다(컴포넌트에 hex·임의 값 금지, `tests/guards.test.ts`).

## Layout

- 머리: 둥근 피치 "30s" 로고 + 작업 이름 → 랜딩(`/`) 링크만. 랜딩 메뉴는 넣지 않는다(아침마다 보는 화면)
- 본문: 최대 폭 1280px(`max-w-7xl`), 좌우 20px(폰)·32px(sm 이상). 로그인 버튼 → 거래일 날짜 h1(28~36px, 800) → 초보용 한 줄 설명(`DASHBOARD_INTRO`, `muted`) → 시장 한눈에(흰 둥근 패널, 데스크톱은 줄을 한 행에) → 카드 1열 → `md` 2열 → `xl` 3열, 간격 16px. 가로 스크롤 없음
- 하단: 모든 페이지 공통 `SiteFooter`(`Not investment advice` 포함)
- 읽기 실패(`app/cards/error.tsx`): h1 `Cards could not be loaded` + `Try again`(피치 알약 버튼, 높이 48px). 에러 내용은 그리지 않는다

## Card (`StockCard`, 랜딩 샘플 카드도 같은 컴포넌트)

- `surface`(흰색) 바탕, `rounded-card`(24px), `shadow-card`(따뜻한 부드러운 그림자), 안쪽 여백 20px(sm 24px)
- 머리: 회사 이름 h2 20px 800(초보는 티커보다 이름을 안다) → 한 줄에 티커 칩(`tint` 바탕 12px `muted`) · 레버리지 태그 칩 · 헤더 알약(새 공시 = `accent-soft` 바탕 `foreground`, 조용한 날·지연·미지원 = `tint` 바탕 `muted`) · (가격 표시 on일 때만) 등락률·종가 라벨
- 줄: 칸마다 `background`(크림) 바탕 `rounded-cell`(16px), 간격 8px. 칸 위 12px 라벨(`LINE_LABELS`: What happened / What's next / Related, `muted` 700), 그 아래 줄 문구 16px(DB 그대로). 확인함·있음 `foreground`, 나머지 `muted`. 알아두기는 첫 칸 안 14px `muted`
- 잠금: 세 번째 줄 잠금·잠긴 자리는 점선 알약 버튼(`border-muted`, 높이 44px, hover `tint`). 랜딩 샘플은 같은 모양의 /plus 링크
- 하단(확인된 줄이 있을 때만): `Checked 7:30 AM ET · …` 12px `muted`
- 줄 안 꾸밈(`+2 more` 알약 등)은 하지 않는다: DB 문구를 한 덩어리로 그린다
