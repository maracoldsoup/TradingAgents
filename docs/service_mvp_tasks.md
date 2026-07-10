# 서비스 MVP 작업 목록

## 원칙

공개 서비스와 운영 콘솔을 같은 화면에 섞지 않는다.

- 공개 서비스: 사용자가 읽는 종목/ETF/테마 콘텐츠
- 운영 콘솔: 후보 큐, 비용 가드, 수집 상태, 발행 상태
- 파일럿 산출물: 공개 서비스의 원재료 또는 운영 지표

## 재사용할 것

### 공개 서비스 재료

- `tradingagents/content_snapshot.py`
- `tradingagents/content_profiles.py`
- `tradingagents/content_pilot.py`
- `tradingagents/content_quality.py`
- `tradingagents/content_preview.py`의 시각화 로직 일부
- `.pilot/content_with_market/*/content_snapshot.json`
- `.pilot/profile_content/*/content_snapshot.json`

### 데이터 수집/신뢰 레이어

- `tradingagents/dataflows/toss_securities.py`
- `tradingagents/dataflows/toss_market_snapshot.py`
- `tradingagents/toss_report_snapshots.py`
- `tradingagents/etf_profile_importer.py`
- `tradingagents/theme_profile_importer.py`

### 운영 콘솔 재료

- `tradingagents/candidate_queue.py`
- `tradingagents/candidate_gap.py`
- `tradingagents/candidate_input_review.py`
- `tradingagents/pilot_assessment.py`
- `tradingagents/pilot_dashboard.py`
- `tradingagents/pilot_api.py`의 운영 API 일부

## 공개 서비스에서 숨길 것

- 후보 수
- 비용 가드 점수
- 내부 파일 경로
- `ready_shortfall`
- 파일럿 평가 문구
- API 호출 실패 로그

이 정보는 `/ops`에서만 보여준다.

## 새로 만들 것

### 1. 서비스 데이터 모델

파일:

- `tradingagents/service_assets.py`

역할:

- content snapshot을 공개 서비스용 asset 객체로 변환
- stock/ETF/theme 공통 필드 제공
- 상세 페이지에 필요한 블록을 정규화

필수 필드:

- `id`
- `kind`: `stock`, `etf`, `theme`
- `ticker`
- `name`
- `market`
- `one_liner`
- `why_moved`
- `composition`
- `bull_points`
- `bear_points`
- `risk_points`
- `watch_points`
- `visuals`
- `sources`
- `as_of`
- `publish_status`

### 2. 공개 API

파일:

- `tradingagents/service_api.py`

필수 endpoint:

- `GET /api/assets`
- `GET /api/assets/{id}`
- `GET /api/themes`
- `GET /api/ops/status`

주의:

- `/api/assets`에는 내부 파일 경로를 노출하지 않는다.
- `/api/ops/status`에만 내부 후보 큐/갭 상태를 노출한다.

### 3. 공개 화면

첫 구현 범위:

- `/`: 홈
- `/stocks/{ticker}` 또는 `/assets/{id}`: 상세
- `/themes/{slug}`는 theme 상세가 준비되면 연결

홈 필수 영역:

- 오늘의 움직임
- 테마 지도
- ETF 구성 카드
- 국내/해외 연결 카드
- 초보자용 설명 카드

### 4. 운영 콘솔

기존 `pilot_api.py`는 공개 서비스가 아니라 `/ops`로 한정한다.

필수 영역:

- 후보 큐
- 부족 슬롯
- 수집 상태
- 발행 가능/불가
- 비용 가드

## 구현 순서

1. `service_assets.py` 작성
2. `tests/test_service_assets.py` 작성
3. `service_api.py` 작성
4. `tests/test_service_api.py` 작성
5. 기존 `pilot_api.py`는 `/ops` 전용으로 역할 축소
6. 공개 HTML은 API가 통과한 뒤 작성

## 현재 구현 상태

- `tradingagents/service_assets.py`가 content snapshot을 공개 asset 모델로 변환한다.
- `tradingagents/service_api.py`가 공개 홈, 검색, 상세, 사후 점검, `/ops`를 제공한다.
- 공개 상세 URL은 `/stocks/{ticker}`, `/etfs/{ticker}`, `/themes/{slug}`를 우선 사용한다.
- `/assets/{id}`는 내부 호환용으로만 유지한다.
- 홈은 빠른 탐색, 섹터·테마, ETF 구성, Hot 내러티브, 사후 점검 레일을 가진다.
- 상세 페이지는 종목 가격·거래량 스냅샷, ETF 집중도/국가 노출, 테마 국내·해외 연결 지도, 시각화 상태 보드를 가진다.
- `/ops`는 공개 홈과 분리된 운영 콘솔로 유지하며 Service Health, Source Intake, Collection Workers, Cost Guard, Publish Gate, Candidate Queue를 가진다.

## 다음 코드 변경 목표

MVP 완료 전 최종 점검을 수행한다.

- 공개 서비스: 내부 경로, 후보 부족, 비용 상태가 노출되지 않는지 확인한다.
- 운영 콘솔: 후보 큐, 수집 상태, 비용 가드, 발행 상태가 `/ops`와 `/api/ops/status`에서만 보이는지 확인한다.
- API: 공개 API와 운영 API의 응답에 필요한 필드가 있고 내부 경로가 없는지 확인한다.

## 첫 번째 코드 변경 목표 완료 기록

`content_snapshot.json` 7개를 읽어 다음이 가능해야 한다.

- 공개 asset list 생성
- stock/ETF/theme 구분
- ETF holdings 노출
- theme value_chain 노출
- 내부 파일 경로 숨김
- 출처/데이터 부족 상태 표시

이 단계는 완료되었고, 현재는 공개 HTML까지 구현된 상태다.
