# 저비용 실행 계획

## 원칙

12개월 전체 LLM 백테스트부터 시작하지 않는다. 먼저 콘텐츠 제품으로서
필요한 데이터 구조, 시각화, 설명 품질을 검증하고, 비용이 큰 모델 호출은
후보가 좁혀진 뒤에만 사용한다.

## 1단계: 무과금 현황 감사

목표: 이미 생성된 리포트와 read-only 데이터에서 발행 가능성과 결함을 측정한다.
이 단계에서는 Gemini 같은 외부 LLM API를 쓰지 않는다.

비용 가드:

```bash
python3 scripts/check_low_cost_config.py
python3 scripts/check_low_cost_config.py --env-file .env.lowcost.example --local-only
python3 scripts/run_local_pilot.py --limit 20 --output-dir .pilot/local
```

Toss 증권 키 점검:

```bash
python3 scripts/probe_toss_securities.py --env-file .env
python3 scripts/probe_toss_securities.py --env-file .env --path /api/v1/stocks --param symbols=005930
python3 scripts/probe_toss_securities.py --env-file .env --path /api/v1/prices --param symbols=005930
python3 scripts/collect_toss_market_snapshot.py --env-file .env 005930.KS AAPL --candle-count 60
python3 scripts/collect_toss_market_snapshots_for_reports.py --limit 20 --dry-run
python3 scripts/collect_toss_market_snapshots_for_reports.py --limit 20 --candle-count 60
```

감사 명령:

```bash
python3 scripts/audit_report_quality.py --limit 20
```

콘텐츠 파일럿 명령:

```bash
python3 scripts/run_content_pilot.py --limit 20 --output-dir .pilot/content
python3 scripts/run_content_pilot.py \
  --limit 20 \
  --output-dir .pilot/content_with_market \
  --market-snapshot-dir .pilot/toss_market
```

ETF/테마 프로필 파일럿 명령:

```bash
python3 scripts/import_etf_profile.py \
  --holdings docs/examples/etf_holdings/demo_global_ai_holdings.csv \
  --ticker DEMOIMPORT \
  --name "CSV 임포트 AI ETF 데모" \
  --issuer "Demo Asset" \
  --currency USD \
  --as-of 2026-07-09 \
  --source docs/examples/etf_holdings/demo_global_ai_holdings.csv \
  --output .pilot/imported_profiles/demo_imported_etf.json

python3 scripts/run_profile_content_pilot.py \
  --profiles docs/examples/content_profiles.sample.json \
  --output-dir .pilot/profiles \
  --market-snapshot-dir .pilot/toss_market

python3 scripts/run_profile_content_pilot.py \
  --profiles .pilot/imported_profiles \
  --output-dir .pilot/imported_profiles/batch_content

python3 scripts/import_theme_profile.py \
  --theme-map docs/examples/theme_maps/demo_ai_semiconductor_theme.csv \
  --ticker KR-AI-SEMI-CSV \
  --name "CSV AI 반도체 테마" \
  --description "CSV에서 가져온 AI 반도체 밸류체인입니다." \
  --as-of 2026-07-09 \
  --source docs/examples/theme_maps/demo_ai_semiconductor_theme.csv \
  --output .pilot/imported_profiles/demo_imported_theme.json
```

20개 후보 큐 점검:

```bash
# 실제 후보를 수동으로 추가할 때는 이 헤더를 사용한다.
# docs/examples/candidate_queue.template.csv

python3 scripts/review_candidate_inputs.py \
  --profiles docs/examples/content_profiles.sample.json \
  --profiles .pilot/imported_profiles \
  --candidates docs/examples/candidate_queue.template.csv \
  --market-snapshot-dir .pilot/toss_market \
  --output-dir .pilot/candidates

python3 scripts/build_candidate_queue.py \
  --report-limit 20 \
  --profiles docs/examples/content_profiles.sample.json \
  --profiles .pilot/imported_profiles \
  --candidates docs/examples/candidate_queue.template.csv \
  --market-snapshot-dir .pilot/toss_market \
  --target-candidates 20 \
  --output-dir .pilot/candidates

python3 scripts/analyze_candidate_gap.py \
  --candidate-queue .pilot/candidates/candidate_queue.json \
  --output-dir .pilot/candidates

python3 scripts/render_pilot_dashboard.py \
  --output .pilot/dashboard/index.html

python3 scripts/run_pilot_api.py --port 8652
```

로컬 서비스 화면:

- `http://127.0.0.1:8652/`: Cloudflare식 제품 제어면. 방문자용 종목/ETF/테마 콘텐츠 라우트와 운영 상태를 함께 보여준다.
- `http://127.0.0.1:8652/console`: 후보 seed row와 구조화 profile JSON을 추가하고 로컬 산출물을 재빌드하는 내부 콘솔이다.
- `http://127.0.0.1:8652/ops`: 비용 가드, 후보 큐, 갭, 품질 상태를 보는 운영 상태판이다.

핵심 API:

- `GET /api/pilot/service`: 서비스 홈에 쓰는 로컬 콘텐츠 카드, 후보 큐 요약, 갭 요약
- `GET /api/pilot/status`: 파일럿 판정 요약
- `GET /api/pilot/candidates`: 후보 큐
- `GET /api/pilot/gap`: 다음 보강 슬롯
- `POST /api/pilot/candidate-seeds`: 수동 후보 CSV row 추가
- `POST /api/pilot/profiles`: 구조화 stock/ETF/theme profile JSON 추가
- `POST /api/pilot/rebuild`: 후보 입력 검수, 후보 큐, 갭, 평가, 운영 상태판 재생성

통합 로컬 파일럿 명령:

```bash
python3 scripts/run_local_pilot.py \
  --limit 20 \
  --output-dir .pilot/local \
  --market-snapshot-dir .pilot/toss_market \
  --profiles docs/examples/content_profiles.sample.json

python3 scripts/run_pilot_assessment.py \
  --output-dir .pilot/assessment
```

Toss snapshot을 먼저 채우는 통합 순서:

```bash
python3 scripts/collect_toss_market_snapshots_for_reports.py --limit 20 --dry-run
python3 scripts/collect_toss_market_snapshots_for_reports.py \
  --limit 20 \
  --candle-count 60 \
  --output-dir .pilot/toss_market
python3 scripts/run_local_pilot.py \
  --limit 20 \
  --output-dir .pilot/local \
  --market-snapshot-dir .pilot/toss_market
python3 scripts/render_content_preview.py \
  --input-dir .pilot/content_with_market \
  --output .pilot/preview/index.html
python3 scripts/render_content_preview.py \
  --input-dir .pilot/local/profiles \
  --output .pilot/preview/profiles.html \
  --title "TradingAgents Stock ETF Theme Profile Preview"
python3 scripts/audit_content_quality.py --input-dir .pilot/content_with_market
python3 scripts/audit_content_quality.py --input-dir .pilot/local/profiles
```

산출물:

- `.pilot/local/local_pilot_report.json`
- `.pilot/local/local_pilot_report.md`
- `.pilot/local/content/content_pilot_summary.json`
- `.pilot/local/profiles/profile_content_pilot_summary.json`
- `.pilot/candidates/candidate_input_review.json`
- `.pilot/candidates/candidate_input_review.md`
- `.pilot/candidates/candidate_queue.json`
- `.pilot/candidates/candidate_queue.md`
- `.pilot/candidates/candidate_gap.json`
- `.pilot/candidates/candidate_gap.md`
- `.pilot/assessment/pilot_assessment.json`
- `.pilot/assessment/pilot_assessment.md`
- `.pilot/dashboard/index.html`
- `.pilot/preview/index.html`
- `.pilot/preview/profiles.html`

판정 기준:

- `status`: 현재 LLM 설정이 저비용 파일럿에 적합한지
- `levels_complete_pct`: 가격 사다리 표시 가능 비율
- `avg_content_ready_score`: 콘텐츠 발행 준비도
- `markets`: 국내/해외 커버리지 분포
- `warnings`: 누락 레벨, 데이터 소스 공백, 과도한 산출물 크기
- `publish_ready_pct`: 콘텐츠 카드/시각화 계약 기준 발행 가능 비율
- `missing_visuals`: ETF와 테마 발행을 막는 구성 시각화 누락
- `market_snapshots_attached`: Toss 등 read-only market snapshot이 붙은 리포트 수
- `price_trend_ready`, `volume_change_ready`: 실제 캔들/거래량 데이터로 시각화 가능해진 리포트 수
- `gate.status`: 통합 로컬 파일럿 최종 상태. 비용 가드 실패, 리포트 부재, 콘텐츠 파일럿 부재는 `fail`이다.
- `content_quality.pass_pct`: 카드 메타데이터 누수, 시각화 데이터 연결, 발행 게이트 상태를 종합한 무LLM 품질 통과율
- `candidate_input_review.summary.status`: 후보 CSV/profile JSON이 큐에 넣을 수 있는 최소 입력인지
- `candidate_queue.gate.status`: 20개 이상 로컬 후보, 국내/해외, stock/ETF/theme 커버리지를 채웠는지
- `candidate_gap.summary.ready_shortfall`: paid-model 비교 전까지 더 채워야 하는 준비 후보 수
- `candidate_gap.slot_plan`: 다음 후보를 어떤 시장/유형/입력으로 채울지에 대한 로컬 작업 슬롯
- `pilot_assessment.verdict.status`: 비용 가드, 커버리지, ETF/테마/해외 경로, 후보 수를 합친 제품 진행 판정
- `pilot_dashboard`: 비용 가드, 후보 큐, 갭, 품질 상태를 한 화면으로 보는 로컬 HTML 보드
- `pilot_api`: 위 산출물을 서비스 화면 `/`, 내부 콘솔 `/console`, 운영 상태판 `/ops`, JSON API로 제공하는 로컬 백엔드

현재 1차 감사 결과:

- 현재 기본 실행 환경은 비용 가드 기준 `fail`이다.
  - deep 모델이 `pro` 계열이다.
  - 토론/리스크 라운드가 각각 1회 켜져 있다.
  - 병렬 분석이 켜져 있어 무료 티어 rate limit과 burst 비용 위험이 있다.
  - 체크포인트가 꺼져 있어 중단 시 재실행 비용이 발생할 수 있다.
- `.env.lowcost.example`의 Ollama 프리셋은 비용 가드 기준 `pass`, 100/100이다.
- Toss 증권 Open API 공식 문서는 비JS/AI agent용 `llms.txt`와 Markdown/OpenAPI 문서를 제공한다.
  - 공식 기본 서버는 `https://openapi.tossinvest.com` 이다.
  - 인증은 OAuth 2.0 Client Credentials Grant, 토큰 발급 endpoint는 `POST /oauth2/token` 이다.
  - 국내(KRX) 및 미국 주식의 현재가, 호가, 체결, 캔들, 종목 정보, 환율, 장 캘린더, 랭킹, 지수는 OAuth 토큰만으로 조회 가능하다.
  - 계좌, 자산, 주문, 조건주문은 `X-Tossinvest-Account` 헤더가 추가로 필요하므로 콘텐츠 파일럿에서는 차단한다.
- Toss는 국내/해외 개별주 콘텐츠의 무료/저비용 read-only 데이터 소스로 우선 검증한다.
  - 주문, 계좌, 잔고, 이체, 매수/매도 path는 파일럿에서 차단한다.
  - `/api/v1/stocks`, `/api/v1/prices`, `/api/v1/candles`, `/api/v1/market-calendar/KR`, `/api/v1/market-calendar/US`부터 확인한다.
  - 응답 헤더의 `X-RateLimit-*` 값을 기록해 무료 티어 병렬도를 제한한다.
- 2026-07-09 실측 검증:
  - `.env`의 Toss 키와 시크릿은 OAuth2 토큰 발급에 성공했다.
  - `GET /api/v1/stocks?symbols=005930,AAPL`은 국내 삼성전자와 미국 Apple 종목 기본정보를 함께 반환했다.
  - `GET /api/v1/prices?symbols=005930,AAPL`은 KRW/USD 현재가를 함께 반환했다.
  - `GET /api/v1/candles?symbol=005930&interval=1d&count=5`와 `symbol=AAPL` 모두 OHLCV를 반환했다.
  - `GET /api/v1/exchange-rate?baseCurrency=USD&quoteCurrency=KRW`는 해외 종목 원화 환산에 필요한 환율을 반환했다.
  - `GET /api/v1/market-calendar/KR`와 `/US`는 국내/미국 장 운영 시간 카드를 만들 수 있는 데이터를 반환했다.
- 2026-07-09 최근 5개 리포트 Toss batch 수집 결과:
  - dry-run 대상은 `068270`, `207940`, `005930` 세 종목이다.
  - `scripts/collect_toss_market_snapshots_for_reports.py --limit 5 --candle-count 60` 실행으로 세 종목 모두 stocks, prices, candles 수집에 성공했다.
  - `.pilot/toss_market/reports_068270__207940__005930_20260709_092915.json`에 로컬 market snapshot이 저장됐다.
  - `scripts/run_local_pilot.py --limit 5 --market-snapshot-dir .pilot/toss_market` 결과 `market_snapshots_attached`는 5/5다.
  - `price_trend_ready`와 `volume_change_ready`도 각각 5/5로 개선됐다.
  - `scripts/audit_content_quality.py --input-dir .pilot/content_with_market` 결과 5/5 통과, 평균 점수 100/100이다.
  - `Executive Summary`, `보고서 작성일`, `대상 종목`, `분석 대상` 같은 리포트 메타 문구는 재생성된 콘텐츠와 preview에서 검출되지 않았다.
- 2026-07-09 해외 개별주 Toss 수집 결과:
  - `scripts/collect_toss_market_snapshot.py --env-file .env AAPL NVDA --candle-count 60` 실행으로 `.pilot/toss_market/AAPL__NVDA_20260709_095847.json`을 저장했다.
  - coverage는 stocks, prices, AAPL/NVDA candles, US market calendar, USD/KRW exchange rate 모두 `true`다.
  - `source_policy.llm_used`는 `false`이며 계좌/주문 endpoint는 사용하지 않았다.
  - `scripts/run_profile_content_pilot.py --market-snapshot-dir .pilot/toss_market` 결과 AAPL stock profile의 `market_snapshots_attached`, `price_trend_ready`, `volume_change_ready`가 각각 1로 개선됐다.
  - `.pilot/local/profiles/AAPL/content_snapshot.json`은 Toss snapshot을 참조하며 AAPL 현재가, 1일/5일/20일 변화율, 60일 고저가, 가격/거래량 차트를 표시한다.
  - `scripts/audit_content_quality.py --input-dir .pilot/local/profiles` 결과 profile snapshot 4/4 통과, 평균 점수 100/100이다.
- 로컬 ETF holdings CSV 임포트 결과:
  - `scripts/import_etf_profile.py`는 운용사/무료 데이터 사이트에서 내려받은 CSV/JSON을 기존 profile JSON으로 변환한다.
  - 지원 열 이름 예시는 `Ticker`, `Name`, `Weight (%)`, `Sector`, `Country`이며, 섹터/국가 비중은 holdings weight를 합산해 만든다.
  - 샘플 CSV `docs/examples/etf_holdings/demo_global_ai_holdings.csv`를 `.pilot/imported_profiles/demo_imported_etf.json`으로 변환했다.
  - 변환된 ETF profile은 `scripts/run_profile_content_pilot.py --profiles .pilot/imported_profiles/demo_imported_etf.json`에서 1/1 발행 가능, 품질 감사 100/100을 통과했다.
  - `.pilot/preview/imported_etf.html`에서 상위 보유 종목, 섹터 비중, 국가 비중 렌더링을 확인했다.
- 로컬 테마 map CSV 임포트 결과:
  - `scripts/import_theme_profile.py`는 밸류체인 단계, 국내/해외 대표 종목, 촉매, 리스크가 들어 있는 CSV/JSON을 기존 theme profile JSON으로 변환한다.
  - 지원 열 이름 예시는 `Stage`, `Description`, `Scope`, `Ticker`, `Name`, `Role`, `Market`, `Country`, `Catalysts`, `Risks`, `Metrics`다.
  - 샘플 CSV `docs/examples/theme_maps/demo_ai_semiconductor_theme.csv`를 `.pilot/imported_profiles/demo_imported_theme.json`으로 변환했다.
  - 변환된 theme profile은 `scripts/run_profile_content_pilot.py --profiles .pilot/imported_profiles/demo_imported_theme.json`에서 1/1 발행 가능, 품질 감사 100/100을 통과했다.
  - `.pilot/preview/imported_theme.html`에서 테마 밸류체인, 국내/해외 대표 종목, 촉매, 리스크 렌더링을 확인했다.
- profile batch 로딩 결과:
  - `scripts/run_profile_content_pilot.py --profiles .pilot/imported_profiles`처럼 디렉터리를 넘기면 직속 profile JSON 파일을 합쳐 배치 파일럿을 실행한다.
  - `.pilot/imported_profiles`에 있는 imported ETF와 imported theme 2개가 2/2 발행 가능, 품질 감사 100/100을 통과했다.
  - `.pilot/preview/imported_batch.html`에서 여러 profile 파일의 ETF/테마 화면을 한 번에 확인했다.
- 로컬 제품 판정 결과:
  - `scripts/run_pilot_assessment.py --output-dir .pilot/assessment` 결과 `status`는 `continue_with_constraints`다.
  - blocker는 없다. 즉 지금 당장 Gemini 같은 외부 LLM API로 넘어갈 이유는 없다.
  - 현재 증거는 saved report 5개, profile path 6개, 총 11개 후보 경로다.
  - 다만 중복 제거된 후보 큐 기준으로는 `ready_for_local_pilot` 9개이며, 20개 목표까지 11개가 더 필요하다.
  - KR/US, stock/ETF/theme 경로와 Toss market snapshot 연결은 확인됐다.
  - 다만 20개 이상 실후보 검증 전에는 paid-model 비교나 12개월 검증으로 넘어가지 않는다.
  - 12개월 검증은 지금 단계에서는 과하다. 콘텐츠 MVP는 설명 구조, 데이터 출처, 시각화 반복 생산성이 먼저이고, 12개월 검증은 자동매매 성과나 정량 랭킹을 주장할 때 좁은 후보군에만 붙인다.
- 로컬 후보 큐 운영 원칙:
  - `scripts/review_candidate_inputs.py`는 후보 CSV와 profile JSON을 먼저 검수한다.
  - stock profile은 시장 snapshot이 없으면 경고를 남기고, ETF/theme profile은 구성 데이터 누락 시 error로 막는다.
  - 후보 CSV row는 seed로만 인정되며, queue-ready가 되려면 saved report 또는 structured profile이 추가로 필요하다.
  - `scripts/build_candidate_queue.py`는 저장 리포트, profile JSON, 선택 CSV/JSON 후보 파일을 합쳐 중복 제거된 후보 큐를 만든다.
  - 이 명령은 로컬 파일만 읽고 API/LLM을 호출하지 않는다.
  - `ready_for_local_pilot`가 20개 미만이면 paid-model 비교로 넘어가지 않는다.
  - stock 후보는 Toss 등 로컬 market snapshot이 붙어야 `ready_for_local_pilot`다.
  - ETF/theme 후보는 실제 holdings/sector/country 또는 value_chain/대표 종목 profile이 있어야 한다.
  - `scripts/analyze_candidate_gap.py`는 후보 큐를 읽어 20개 목표까지의 부족분을 `candidate_gap.md`에 작업 슬롯으로 펼친다.
  - 현재 갭 기준으로는 준비 후보 11개가 더 필요하며, 최소 stock 4개, ETF 1개, theme 2개, KR 4개, US 3개를 보강하는 쪽이 균형이 맞다.
  - `scripts/render_pilot_dashboard.py`는 `local_pilot_report`, `candidate_queue`, `candidate_gap`, `pilot_assessment`를 합쳐 `.pilot/dashboard/index.html`을 만든다.
  - 이 dashboard는 외부 CDN, JavaScript, LLM 호출 없이 로컬 HTML/CSS만 사용한다.
  - `scripts/run_pilot_api.py --port 8652`는 같은 산출물을 FastAPI 백엔드로 제공한다.
  - 루트 `/`는 Cloudflare식 제품 제어면이다. 종목, ETF, 테마 콘텐츠 스냅샷을 읽어 방문자용 서비스 화면으로 보여준다.
  - `/console`은 후보 seed row와 profile JSON을 넣는 내부 작업 화면이다.
  - `/ops`는 기존 로컬 dashboard를 보여준다.
  - 핵심 endpoint는 `GET /api/pilot/service`, `GET /api/pilot/status`, `GET /api/pilot/candidates`, `GET /api/pilot/gap`, `GET /api/pilot/artifacts/{name}`, `POST /api/pilot/candidate-seeds`, `POST /api/pilot/profiles`, `POST /api/pilot/rebuild`다.
  - `POST /api/pilot/rebuild`는 후보 입력 검수, 후보 큐, 갭, 평가, dashboard HTML을 로컬에서 재생성한다. 외부 LLM/API를 호출하지 않는다.
- Toss만으로는 부족한 영역:
  - ETF 상위 보유종목, 섹터/국가 비중은 별도 ETF provider 또는 수동 프로필이 필요하다.
  - 테마 밸류체인과 국내/해외 대표 종목 묶음도 Toss가 자동으로 제공하지 않는다.
  - 뉴스의 원인 해석은 Naver/news provider + 사람이 확인 가능한 근거 링크가 필요하다.
- 최근 5개 리포트 모두 KR 종목이다.
- `signal.json`은 모두 존재한다.
- entry, stop, target, position_size_pct가 모두 채워진 리포트는 1개뿐이다.
- 기존 리포트 재처리 기준 개별주 콘텐츠 발행 가능률은 5/5, 100%다.
- 다만 4개 리포트는 가격 사다리를 숨겨야 한다.
- 스키마 데모 기준 stock/ETF/테마 프로필 파일럿은 4/4, 100% 발행 가능이다.
  - 해외 개별주 1개, 국내 ETF 1개, 해외 ETF 1개, 국내/해외 대표 종목을 포함한 테마 1개를 검증한다.
  - AAPL 해외 개별주 프로필은 제품/서비스, 지역 노출, 비교 대상, 촉매, 리스크를 표시한다.
  - AAPL 가격/거래량은 Toss market snapshot이 붙어 `price_trend`와 `volume_change`가 `ready`다.
  - ETF는 holdings, sectors, countries가 모두 있어야 통과한다.
  - 테마는 value_chain과 국내/해외 대표 종목 중 하나 이상이 있어야 통과한다.
- `.pilot/preview/profiles.html`은 해외 개별주 사업/지역 구성, ETF 상위 보유 종목, 섹터/국가 비중, 테마 밸류체인, 국내/해외 대표 종목을 정적 HTML/CSS로 확인하는 미리보기다.
- `scripts/run_profile_content_pilot.py --market-snapshot-dir ...`와 `scripts/run_local_pilot.py --market-snapshot-dir ...`는 같은 로컬 Toss snapshot index를 사용한다. AAPL/NVDA 같은 해외 개별주 snapshot 파일이 추가되면 프로필 콘텐츠의 가격 추이/거래량 시각화도 자동으로 `ready`가 된다.
- `scripts/import_etf_profile.py`를 쓰면 ETF 보유종목 CSV/JSON을 별도 LLM/API 없이 구조화 프로필로 만들 수 있다. 이 경로는 실제 운용사 파일을 수동으로 내려받아 로컬에서 검증할 때 우선 사용한다.
- `scripts/import_theme_profile.py`를 쓰면 테마 밸류체인 CSV/JSON을 별도 LLM/API 없이 구조화 프로필로 만들 수 있다. 이 경로는 사람이 정리한 테마 맵이나 공개 표 데이터를 검증 가능한 콘텐츠 입력으로 바꿀 때 우선 사용한다.
- 따라서 지금은 매매 신호 검증보다 콘텐츠 구조 검증이 먼저다.

주의:

- `.env.lowcost.example`은 키 없이 저장할 수 있는 안전한 저비용 프리셋이다.
- 기본 파일럿 명령은 원본 리포트 폴더를 수정하지 않는다.
- `--output-dir`를 쓰면 재생성된 `content_snapshot.json`과 요약 JSON을 별도 폴더에 저장한다.
- `--market-snapshot-dir`를 쓰면 로컬 JSON artifact만 읽어 가격 추이/거래량 시각화 준비도를 갱신한다.
- 원본 리포트에 `content_snapshot.json`을 채우려면 명시적으로 `--write-back`을 붙인다.
- `docs/examples/content_profiles.sample.json`은 스키마 데모용이며 실제 시장 데이터가 아니다.
- `scripts/run_local_pilot.py`는 외부 LLM API를 호출하지 않는다. 기본값은 `--local-only`이며, `.env.lowcost.example`로 비용 가드를 통과해야 한다.
- `scripts/render_content_preview.py`는 content snapshot과 market snapshot을 정적 HTML/SVG로 렌더링한다. 외부 CDN, JavaScript, LLM 호출이 없다.
- `scripts/audit_content_quality.py`는 발행 가능률과 별도로 카드 문장 품질/메타데이터 누수/시각화 데이터 연결을 검사한다.

## 2단계: 로컬 스크리닝

목표: 많은 후보를 무LLM 또는 로컬 모델로 거른다. 외부 LLM API가 필요해 보여도
Gemini를 먼저 쓰지 않는다.

로컬 우선 설정:

```env
TRADINGAGENTS_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
TRADINGAGENTS_QUICK_THINK_LLM=qwen3:latest
TRADINGAGENTS_DEEP_THINK_LLM=qwen3:latest
TRADINGAGENTS_MAX_DEBATE_ROUNDS=0
TRADINGAGENTS_MAX_RISK_ROUNDS=0
TRADINGAGENTS_PARALLEL_ANALYSTS=false
TRADINGAGENTS_CHECKPOINT_ENABLED=true
```

주의:

- 무료 모델은 후보 발굴과 초안 생성에만 쓴다.
- 숫자와 가격 레벨은 데이터 도구 또는 구조화 출력에서만 사용한다.
- 무료 티어가 막히면 병렬 실행을 끄고, 체크포인트를 켠 상태로 재개한다.

## 3단계: ETF/테마 데이터 구조화

목표: ETF와 테마는 구성 시각화가 있어야 발행한다.

입력 파일:

- `docs/examples/content_profiles.sample.json` 구조를 따른다.
- 실제 운영에서는 ETF 보유 종목, 섹터/국가 비중, 테마 밸류체인 데이터를 데이터 수집기로 채운다.
- LLM은 이 숫자를 만들지 않는다.

필수 데이터:

- ETF: 상위 보유 종목, 섹터 비중, 국가 비중, 보수, 운용자산
- 테마: 대표 종목, 밸류체인 단계, 촉매 이벤트, 최근 수익률
- 공통: 가격 변화, 거래량, 주요 뉴스, 리스크 요약

출력 단위:

- 한 줄 정의
- 오늘 움직인 이유
- 구성 설명
- 숫자 카드
- 리스크 카드
- 다음 관찰 포인트

## 4단계: 시각화 MVP

목표: 초보자가 30초 안에 이해할 수 있는 화면을 만든다.

필수 차트:

- 가격 추이
- 거래량 변화
- ETF 상위 보유 종목 막대 차트
- ETF 섹터/국가 비중
- 테마 밸류체인 지도
- 이벤트 타임라인

표시 규칙:

- 가격 레벨이 없으면 가격 사다리를 숨긴다.
- ETF 구성 데이터가 없으면 ETF 콘텐츠를 발행하지 않는다.
- 테마 대표 종목이 없으면 테마 콘텐츠를 발행하지 않는다.

## 5단계: 유료 모델 승격

목표: 발행 후보만 품질을 끌어올린다.

유료 모델 사용 조건:

- 데이터 구조가 채워져 있다.
- 구성 시각화가 가능하다.
- 초안이 콘텐츠로 쓸 만하다.
- 사람 검수 또는 자동 품질 점수가 기준을 넘는다.

사용 위치:

- 제목 후보 생성
- 카드뉴스 문장 다듬기
- 숏폼 영상 내레이션
- 리스크 표현 완화
- 해외 종목의 한국어 현지화

## 6단계: 백테스트

목표: 매매 신호 주장을 할 때만 수행한다.

순서:

1. 캐시된 `signal.json`으로만 재계산한다.
2. 20-30개 샘플 날짜로 신호 품질을 본다.
3. 가격 레벨 완성도가 안정되면 3개월 범위로 확장한다.
4. 그 다음에만 12개월 검증을 고려한다.

금지:

- 처음부터 12개월 x 일별 LLM 실행
- 레벨이 비어 있는 신호로 성과 주장
- 혼합 모델 캐시를 섞은 백테스트
