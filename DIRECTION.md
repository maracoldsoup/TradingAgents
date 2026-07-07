# DIRECTION.md — 이 저장소에서 작업하는 모든 사람·AI가 지켜야 할 방향

> 이 문서는 장식이 아니다. 외부 AI 모델 투입으로 발생한 실제 사고 2건
> (프런트엔드 디자인 전면 삭제, 코스닥 접미사 하드코딩)의 재발 방지 장치다.
> 코드를 만지기 전에 읽고, 아래 불변조건과 충돌하는 작업은 하지 마라.

## 0. 프로젝트가 향하는 곳

멀티에이전트 분석 파이프라인(TradingAgents 포크)을 기반으로 한
**트리거 기반 자동 콘텐츠 생산** (특징주 단신 → 카드뉴스 → 영상, 한국 → 다국가).
트레이딩 자동 주문은 로드맵에 없다. 자세한 것은 `docs/roadmap_v2` 참고.

## 1. 절대 불변조건 (위반 = 롤백 대상)

### 데이터 정직성
- **LLM이든 프런트든, 숫자를 지어내지 않는다.** 가격·지표는 구조화 출력
  (`trader_structured`/`pm_structured`/`signal.json levels`) 또는 검증 스냅샷에서만 온다.
- 산문 정규식 추출(`dashboard/events.py`)은 free-text 폴백 전용이다. 구조화 필드가
  있으면 항상 그것이 이긴다 (`levels_source` 필드로 추적).
- 값이 애매하면 표시하지 않는다. 틀린 숫자 > 빈 칸이 아니라, 빈 칸 > 틀린 숫자다.
- DATA_UNAVAILABLE 프로토콜 유지: 소스가 죽으면 "없다"고 말하고 진행한다. 조용한
  폴백·조작 금지 (벤더 체인 철학).

### 한국 시장 처리
- **시장 접미사(.KS/.KQ)를 하드코딩하지 마라.** DART corp 맵에는 시장 구분이 없다.
  접미사는 `/api/resolve`의 yfinance 실측 프로브로만 판별한다.
  (하드코딩은 코스닥 1,285종목을 침묵 속에 죽인다 — 실제 있었던 사고다.)
- KRX 종목은 미국 소셜 소스(StockTwits/Reddit)를 네트워크 요청 없이 스킵한다
  (`symbol_utils.is_korean_listing`).

### 아키텍처
- 애널리스트 4명은 `state["messages"]` 채널을 공유하므로 **LangGraph 평면 팬아웃 금지.**
  병렬화는 격리 서브그래프 방식만(`graph/parallel_analysts.py` 모듈 주석 참고).
- 대시보드는 관찰자다: `propagate(on_chunk=...)` 훅으로 구경만 한다.
  별도 파이프라인을 만들지 마라. 옵저버 예외는 절대 런을 죽이면 안 된다.
- `save_reports`는 **디렉토리(리포트 트리)** 를 반환한다. 파일을 기대하는 코드를 쓰지 마라.

### 프런트엔드 (AGENT DESK)
- 디자인 시스템을 갈아엎지 마라. 토큰: 배경 `#0B0E14`, 앰버 `#FFB000`,
  **한국식 색 문법 — 상승/매수 빨강 `#E8453C`, 하락/매도 파랑 `#3D7BE8`.**
  브랜드는 AGENT DESK다. 개명·리브랜딩 금지.
- 필수 요소: 에이전트 카드 펄스, Bull/Bear 말풍선, 5등급 게이지, 가격 사다리
  (사다리는 entry/stop/target 가격 3종만 — %·배수 스칼라 금지).
- 스크립트 상단에서 스크립트 뒤에 오는 DOM을 직접 참조하지 마라 (위임 바인딩 사용).
  이것 때문에 검색창이 통째로 죽은 적이 있다.

## 2. 계약 (스키마 바꾸려면 소비자 전부 확인)

- `signal.json` (schema_version 1): rating/action/bias/score + 선택적 `levels`
  {entry, stop, target, position_size_pct}. 소비자: 대시보드, (예정) 백테스트, 콘텐츠 템플릿.
- 대시보드 SSE 이벤트 타입: stage / report / telemetry / debate / trader / risk /
  final / artifact / error. 필드 제거는 파괴적 변경이다.
- 5등급 표준 어휘는 `agents/utils/rating.py`가 유일한 정의처다.

## 3. 작업 규칙

- 설치는 `pip install -e ".[dashboard]"` (editable 필수 — 소스 수정 즉시 반영).
- `.env`는 저장소 루트 하나만. 실행도 저장소 루트에서.
- 커밋 전 `python -m pytest tests/ -q` 전체 통과 필수. 테스트 삭제·완화로
  통과시키는 행위 금지 (UI 문자열 단언 같은 취약 테스트는 기능 단언으로 교체는 가능).
- 프런트 수정 시 `node --check` + 스텁 DOM top-level 실행 검증까지.
- 실측이 우선이다: "될 것이다"가 아니라 로그·테스트로 증명하고 커밋 메시지에 근거를 남겨라.
