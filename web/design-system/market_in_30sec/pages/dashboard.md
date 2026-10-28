# Dashboard Page (`/cards`)

> **PROJECT:** market_in_30sec · **기준:** 사용자 시안 `../../user-mockup/landing.dc.html`의 "The card" 샘플 카드(#27). `../MASTER.md`(#24)는 대체됐다.
> 값은 `web/src/app/globals.css` 토큰으로만 쓴다(컴포넌트에 hex·임의 값 금지, `tests/guards.test.ts`).

## Layout

- 머리: 브랜드(빨간 "30s" + 작업 이름) → 랜딩(`/`) 링크만. 랜딩 메뉴는 넣지 않는다(아침마다 보는 화면)
- 본문: 최대 폭 1280px(`max-w-7xl`), 좌우 32px. 거래일 날짜 h1(36px, 500) → 카드 목록 1열 → `md` 2열 → `xl` 3열, 간격 16px. 가로 스크롤 없음
- 하단: 모든 페이지 공통 `SiteFooter`(시안 하단, `Not investment advice` 포함, 링크는 `/#…` 랜딩 앵커)
- 읽기 실패(`app/cards/error.tsx`): h1 `Cards could not be loaded` + `Try again`(흰 테두리 버튼, 높이 48px). 에러 내용은 그리지 않는다

## Card (`StockCard`, 랜딩 샘플 카드도 같은 컴포넌트)

- `surface`(#303030) 바탕, 안쪽 여백 24px, 모서리 없음
- 머리 한 줄(baseline 정렬, 간격 12px): 티커 18px 700 · 종목명 14px `muted` · 등락률 18px 600 tabular-nums(상승 `up`·하락 `down`·보합 `foreground`, 지연·미지원은 14px `muted` 문구) · `prev close` 12px `muted`. 안 들어가면 등락률 묶음이 다음 줄 오른쪽으로
- 레버리지 태그(있으면): `background` 바탕 알약, 12px `muted`
- 세 줄: 14px, 줄마다 위 구분선 `border`(#484848), 위아래 12px(마지막 줄 아래 0). 확인함·있음 `foreground`, 나머지(없음·지연·미지원) `muted`. 무료 범위의 세 번째 줄(#9)은 같은 자리에 `Price facts in Plus`를 `muted`로(아이콘 없음, 문구가 잠금을 말한다). 줄을 숨기지 않는다. 상태 아이콘은 시안에 없어 뺐다(문구가 상태를 말한다)
- 하단(확인된 줄이 있을 때만): `Checked 7:30 AM ET · …` 12px `muted`
- 시안의 줄 안 꾸밈(`+2 more` 알약, `(Company)` 밑줄, `(D-2)` 흐림)은 하지 않는다: DB 문구를 한 덩어리로 그린다

## Accessibility (ui-ux-pro-max 점검, #27)

- 대비: `muted` surface 위 5.2:1, `dim`(#969696)은 surface 위 4.46:1이라 background 위에만. `up` 5.7:1, `down` 5.0:1, 흰 글자/`accent` 4.9:1
- 키보드 포커스: 모든 링크·버튼에 2px 흰 외곽선(globals.css), 흰 바탕(요금 섹션)에서는 어두운 외곽선
- 터치 영역: 링크·버튼 높이 44px 이상(`min-h-11`/`min-h-12`, tests/components.test.tsx)
- 색만으로 뜻을 전하지 않는다: 등락률은 부호가 항상 붙고, 줄 상태는 문구 자체가 말한다

## Motion

- 카드 읽는 동안 스켈레톤(`motion-safe:animate-pulse`). 그 외 애니메이션 없음
