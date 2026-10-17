---
name: ios-conventions
description: "30초 종목 리포트 iOS 앱(ios/, SwiftUI)의 구현 규칙. 온보딩, 홈, 카드, 아침 알림 설정, 아레나 탭, 잠금화면 위젯, Plus 잠금 화면을 작성·수정·리뷰할 때 사용한다. 서버 코드는 backend-conventions, 문장 내용은 card-copy-rules를 쓴다."
---

# iOS 구현 규칙

스택: SwiftUI, WidgetKit, StoreKit 2, Sign in with Apple + Google. 설계 근거는 `docs/HANDOFF.md` 3-1~3-5, 3-7, 3-8.

## 1. 꼭 지킬 규칙과 이유

| 규칙 | 이유 |
| --- | --- |
| 화면 문구를 코드에 하드코딩하지 않고 String Catalog(`Localizable.xcstrings`)에 둔다 | MVP는 영어지만 다국어 확장을 처음부터 대비한다(HANDOFF 3-1) |
| 앱에 API 키, LLM 호출, 벤더 직접 호출을 넣지 않는다 | 빌드에서 추출된다. 모든 데이터는 서버 API로 받는다 |
| 숫자 계산·무료/Plus 판단·문장 생성을 앱에서 하지 않는다. 서버가 보낸 값을 그린다 | 값이 두 곳에서 어긋나거나 잠금이 우회된다 |
| 방향 의견(콜, 토크)은 아레나 탭 화면에서만 그린다 | ADR-0001 |
| 등락률: 전일 종가 기준, 진짜 마이너스 기호(−), 상승 초록·하락 빨강 | HANDOFF 3-3 |
| 아레나 수익률 옆에 기준 표시를 항상 붙이고, 장중에 실제 데이터 없이 움직이는 연출을 하지 않는다 | 실시간 데이터가 없는데 있는 것처럼 보이면 안 된다(HANDOFF 3-5) |
| 조용한 날에도 세 줄 모두 숨기지 않고 서버가 보낸 "없음"·잠금 문구를 그린다 | 카드 높이가 날마다 크게 바뀌지 않게 한다 |
| 알림 시간 선택지는 동부 7:45 이후만 보여준다(기기 타임존으로 환산) | 카드가 준비되기 전에 알림이 가지 않게 한다 |
| "Not investment advice" 고지를 온보딩 동의, 상세 화면 하단, 설정에 둔다 | HANDOFF 3-3 |
| 계정 삭제를 앱 안에서 할 수 있게 한다 | 애플 심사 요건 |
| 둘러보기 화면은 서버가 보낸 잠금 상태를 그대로 그린다. 교체 4번째 시도에 서버가 거절하면 업셀 화면을 띄운다. 교체 카운트 요청에 기기 타임존을 보낸다 | 제한 판단은 서버가 한다(HANDOFF 3-2) |
| 온보딩: 종목 고르기 → 카드 바로 보여주기(계정 없음) → "매일 아침 받으려면 저장" → Apple/Google 로그인 → 알림 시간 → 푸시 권한. 로그인 전 첫 번째 줄이 없는 카드는 "Sign in to get today's summary"를 그린다 | 첫 화면 이탈을 줄이고, 저장 시점에 로그인한다(HANDOFF 3-2) |

## 2. 디렉터리

```
ios/
├── M30.xcodeproj
├── M30/            # 앱: Features/(Onboarding, Home, Card, Arena, Settings, Paywall), Models/, Networking/
├── M30Widget/      # 잠금화면 위젯
└── M30Tests/
```

architect 스펙이 다르게 정하면 스펙을 따른다.

## 3. 서버 연동

- API 응답 모델은 architect 스펙의 구조를 그대로 `Codable`로 옮긴다. 필드 이름을 앱 사정으로 바꾸지 않는다
- 서버 응답에 없는 필드를 앱이 추측해 채우지 않는다
- 개발 중에는 스펙의 예시 JSON으로 만든 목업 응답으로 화면을 확인한다

## 4. 빌드·테스트

```bash
xcodebuild -project ios/M30.xcodeproj -scheme M30 -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build test
```

시뮬레이터 이름은 `xcrun simctl list devices available`로 확인해 맞춘다.

## 5. 사용자가 직접 해야 하는 일

Apple 개발자 계정, 서명·인증서, 푸시 인증 키, App Store Connect 상품 등록은 에이전트가 할 수 없다. 필요하면 멈추고 "사용자 조치 필요"로 보고한다.
