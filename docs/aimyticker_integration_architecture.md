# AImyticker 통합 아키텍처

## 목표

AImyticker(마티, 이하 앱)를 TradingAgents 리서치 파이프라인과 연결해 고도화한다.

- KBO 위젯(`app/src/pages/KboWidget.tsx`, `app/public/kbo/*`, `api/kbo*.js`,
  `kbo-widget-intelligence/`)은 스코프 밖이다. 이 문서는 다루지 않는다.
- 기존 번역 레이어(`supabase/functions/translate-article`의 Gemini 온디맨드 번역,
  `n8n_legacy/WF01_news_pipeline.json`)는 제거 대상이다. 앱이 뉴스를 받고 나서
  버튼 클릭 시 Gemini를 호출하는 구조를 없앤다.
- 피드는 코인니스식으로 계속 업데이트되는 속보 스트림을 기본으로 하되, 그 사이에
  TradingAgents가 만드는 리서치 카드가 섞여 들어간다. 완전한 리서치 카드 전용
  피드로 바꾸는 게 아니다.
- 게임화(예측 챌린지, 배틀 등)는 하지 않는다. `League.tsx`는 기존 기능으로
  그대로 두되, 이번 통합에서 새로 채우거나 연동하지 않는다.

## 제품 색깔

경쟁 서비스 대비 우리가 다르게 가져갈 지점은 세 가지다.

1. **개인화 티커 정보**: 피드는 시장 전체의 트렌딩이 아니라 사용자가 구독한
   티커(`ticker_slots`, `Shop.tsx`에 이미 있음)를 우선한다. 같은 속보/리서치
   소스라도 사용자마다 상단에 뜨는 항목이 달라야 한다.
2. **특징주 파악**: 지금 이 순간 비정상적으로 움직이는 종목을 잡아낸다. Toss
   증권 `/api/v1/rankings`(TOP_GAINERS/TOP_LOSERS/거래량·거래대금 상위)를
   1차 소스로 쓰고, `candidate_gap`/`candidate_queue`로 원인 설명을 붙인다.
   구독하지 않은 종목도 노출되는 발견 경로다. 자세한 내용은 아래 "Toss 증권
   API 우선 활용" 참고.
3. **관련 분석 + 포인트로 분석 트리거**: 특징주나 관심 티커를 보다가 더 깊이
   알고 싶을 때, 포인트를 써서 그 종목에 대한 분석을 요청하는 게 핵심 동선이다.
   `Shop.tsx`에 이미 있는 포인트 경제(`ticker_slot_5`, `notif_boost_30`)에 새
   아이템을 추가하는 형태다. 자세한 내용은 아래 "포인트 기반 온디맨드 분석"
   참고.

## 레포 경계

두 레포는 물리적으로 합치지 않는다.

- `TradingAgents` (Python): 리서치 콘텐츠를 생성하고 HTTP API로 노출한다.
- `aimyticker` (TypeScript/Supabase/Capacitor): 사용자가 보는 앱, 커뮤니티,
  구독/과금(Shop), 푸시(Firebase)를 담당한다. `League.tsx`(게임화)도 있지만
  이번 통합 스코프에는 포함하지 않는다.

연결은 `tradingagents/research_gateway.py`가 이미 제공하는 API를 계약으로
삼는다 (`scripts/run_service_api.py`로 구동). 앱 쪽에서 이 API를 주기적으로
당겨와 Supabase 테이블에 반영하는 새 Edge Function이 경계를 넘는 유일한
지점이다.

## 콘텐츠 타입 두 가지

### 1. research_card (이미 존재)

`research_gateway`의 `/api/assets`, `/api/assets/{id}`, `/api/themes`가 이미
`content_snapshot.json`(문서: `docs/analysis_snapshot_contract.md`)을 감싸서
내려준다. `schema_version`, `publish_gate`, `composition_data`, `market_data`가
포함돼 있고 ETF/테마는 구성 데이터 없이는 `publish_gate.status`가
`blocked`로 나온다. 앱은 이 게이트를 그대로 존중해서 `blocked` 자산은
렌더링하지 않는다.

- 카덴스: 낮음 (하루 수십 건 수준, 종목/ETF/테마 단위 심층 카드)
- 번역 문제 없음: 콘텐츠 자체가 한국어로 생성됨 (Gemini 개입 없음)
- `sector`(종목/테마) / `primary_sector`(ETF, 파생값) 필드가 필요하다 — 아래
  "섹터 > 테마 > 종목/ETF 탐색" 참고. 이 필드가 있어야 `research_cards`
  테이블에서 섹터별로 묶어서 보여줄 수 있다.

### 2. breaking_item (신규, TradingAgents 쪽에 아직 없음)

코인니스 스타일 연속 속보. 지금 TradingAgents에는 이 산출물이 없다.
`candidate_queue`/`candidate_gap`이 이미 후보 티커와 원인 후보를 추적하고
있으므로, 여기서 짧은 헤드라인+1~2줄 요약을 뽑아내는 신규 모듈이 필요하다.

정렬 우선순위는 "위 제품 색깔"과 직결된다. 같은 API 응답이라도 앱이 사용자별로
재정렬한다.

1. 사용자가 구독한 티커 (`ticker` 필드가 사용자 관심 목록에 매칭)
2. 특징주 (거래량/가격 이상치로 잡힌 종목, 구독 여부 무관 — 발견 경로)
3. 그 외 일반 속보

- 카덴스: 높음 (뉴스/공시 발생 시점에 가깝게)
- 번역: Gemini 온디맨드 호출 없이, TradingAgents의 저비용 원칙
  (`docs/content_product_spec.md`의 "로컬/무료 모델은 초안 정리에만",
  "숫자를 만들지 않는다")을 그대로 따른다. 국내 소스는 원문이 이미 한국어이고,
  해외 소스는 로컬/무료 모델 요약 또는 템플릿 기반 정규화를 쓴다. 앱에
  넘어가는 시점엔 이미 한국어로 완성돼 있어야 한다 — "번역 중" 상태를 앱이
  다시 폴링하는 구조를 만들지 않는다.
- 신규 작업: `tradingagents/content_snapshot.py`처럼 no-LLM-first로 동작하는
  `tradingagents/breaking_feed.py` 같은 모듈 + `research_gateway.py`에
  `/api/breaking` 라우트 추가. 응답 형태 제안:

  ```json
  {
    "schema_version": 1,
    "artifact": "service_breaking_list",
    "count": 0,
    "items": [
      {
        "id": "...",
        "ticker": "AAPL",
        "kind": "stock",
        "headline_ko": "...",
        "summary_ko": "...",
        "source": "...",
        "source_url": "...",
        "published_at": "2026-07-10T09:00:00Z",
        "market": "US",
        "notable_mover": false
      }
    ]
  }
  ```

  `translation_status` 같은 필드는 만들지 않는다. 항목이 API에 나타나는
  시점이 곧 "발행 준비 완료" 시점이다. `notable_mover`의 정의는 아래 "Toss
  증권 API 우선 활용 > 큰 발견" 참고 — 자체 계산한 파생값이 아니라 Toss
  `/api/v1/rankings`(TOP_GAINERS/TOP_LOSERS/거래량·거래대금 상위) 결과를
  그대로 인용한 값이다.

## 홈/피드 레이아웃 벤치마크 (AntWiki)

`https://www.ant.wiki/` 홈을 다시 확인했다 (상세 노트: `docs/reference_antwiki.md`
"2026-07-10 라이브 재확인"). 홈은 무한 스크롤 속보 스트림이 아니라 카드 블록이
세로로 쌓인 매거진형 구조이고, 순서는 히어로 → 예측 챌린지 → 개인화 주간 요약
→ 이벤트형 테마(스페이스X) → 캘린더 → 챌린지2(UpAntDown) → 뜨는 테마 →
Hot 내러티브다.

이걸 보고 "피드 = 코인니스식 연속 속보"라는 앞선 결정을 완전히 바꾸지는
않지만, 한 겹을 더 두는 게 맞다고 판단했다.

- **상단 블록 (AntWiki 패턴)**: `Feed.tsx` 최상단에 고정형 카드 블록을 둔다 —
  오늘 뜨는 테마(research_card 상위 노출), 분석 요청 진입점(아래 "포인트 기반
  온디맨드 분석" 참고), 다음 관찰 이벤트(캘린더성 카드). 이 블록은 스크롤해도
  갱신되는 스트림이 아니라 하루 단위로 갱신되는 요약이다.
- **하단 스트림 (코인니스 패턴)**: 그 아래로 `breaking_item`이 계속 흐르고,
  중간중간 `research_card`가 섞인다. 기존 설계 그대로 유지.

이렇게 나누면 "왜 움직였는지 아직 모르는 사람"은 상단 블록에서 오늘 흐름을
30초 안에 파악하고, "계속 지켜보고 싶은 사람"은 하단 스트림을 스크롤한다.
AntWiki의 핵심 원칙(테마→종목 탐색, "왜인지부터" 접근, Bull/Bear 내러티브
분리)은 그대로 research_card 쪽 설계 원칙으로 남는다 — 이미
`docs/service_mvp_spec.md`, `docs/content_product_spec.md`에 반영돼 있다.

AntWiki의 예측 챌린지/UpAntDown 같은 게임화 블록은 참고하지 않는다. 상단
블록은 게임화 대신 "오늘 뜨는 테마"와 "포인트로 분석 요청" 진입점 두 가지로
채운다.

## 섹터 > 테마 > 종목/ETF 탐색

`https://www.ant.wiki/themes`를 확인해보니 "섹터(19개) -> 테마(섹터당
10~30개) -> 종목" 3단계 드릴다운이 잘 되어 있다 (상세: `docs/reference_antwiki.md`
"섹터·테마 드릴다운 실측"). 초보자가 티커를 몰라도 익숙한 산업명에서 시작해
좁혀 들어갈 수 있다는 점이 벤치마킹 포인트다.

앤트위키는 이 드릴다운에 ETF가 없다 — 섹터/테마 페이지에 개별 종목만
나온다. 우리는 여기에 ETF를 끼워 넣는다: 테마 페이지에 "이 테마를 담은 ETF"
목록을 추가해서, 종목을 하나씩 고르기 부담스러운 사람이 테마 전체 노출
상품으로 바로 넘어가게 한다. 데이터 모델/발행 규칙은
`docs/content_product_spec.md`의 "섹터 레이어", `docs/service_mvp_spec.md`의
"3. ETF 페이지"/"4. 테마 페이지"에 이미 반영해 뒀다.

- ETF의 `primary_sector`는 새로 만드는 숫자가 아니라 이미 있는
  `composition_data.sectors`(비중 상위 섹터)에서 파생한다.
- `research_gateway.py`에 `/api/sectors`, `/api/sectors/{slug}` 라우트를
  추가한다. `/api/sectors/{slug}`는 그 섹터의 테마 목록과, 테마 없이 섹터에
  직접 속한 종목/ETF를 함께 반환한다.
- `/api/themes/{slug}`(기존) 응답에 `etfs: []` 필드를 추가한다 —
  `primary_sector`가 해당 테마의 섹터와 일치하는 ETF 목록이다.
- aimyticker 쪽: 홈 상단 블록의 "오늘 뜨는 테마"에서 섹터 목록 화면으로
  들어가는 진입점을 만든다 (기존 화면에 얹거나 신규 `Sectors.tsx`). 테마
  상세 화면에 "이 테마 ETF" 섹션을 추가하고, `TickerDetail.tsx`가 ETF일 때는
  `primary_sector` 배지를 보여주고 클릭하면 해당 섹터 페이지로 이동한다.

## 포인트 기반 온디맨드 분석

`Shop.tsx`는 이미 포인트 경제(`ShopStatus.points`, `ticker_slot_5`,
`notif_boost_30`)와 현금 플랜(`starter_pack`, `monthly_pass`, `isCash: true`)
두 축을 갖고 있다. 분석은 완전 무료가 아니다 — 두 깊이 모두 포인트가 있어야
받을 수 있고, 그 위에 현금 플랜이 깊이를 가른다.

### 두 깊이

- **간단 분석 (`analysis_light`)**: `content_snapshot.py`가 이미 만드는
  no-LLM 결정적 카드 그대로다. 배치로 미리 만들어 둔 게 없는 티커라면,
  Toss 데이터가 있는 한 즉시(또는 몇 초 내) 생성 가능하다. 포인트 소모는
  적게 잡는다 — LLM 비용이 거의 안 들기 때문이다. `Shop.tsx`의 "포인트로
  확장" 섹션에 새 아이템으로 추가한다.
- **딥 분석 (`analysis_deep`)**: 실제 멀티에이전트 파이프라인(analysts →
  bull/bear 리서처 → trader → risk → portfolio manager 전체 디베이트, 리포트
  트리에 `4_risk/`, `5_portfolio/decision.md` 등을 만드는 그 실행) 을 돌린다.
  포인트 가격을 훨씬 높게 잡거나, `starter_pack`/`monthly_pass` 같은 현금
  플랜 보유를 조건으로 건다 — 포인트만으로는 사실상 도달하기 어렵게 해서
  "유료 결제 시 딥 분석"이라는 사용자 요구를 반영한다.
- 어느 쪽이든 포인트가 없으면 요청 버튼 자체를 막는다. "무료 회원"이라는
  개념은 없고, 포인트 보유 여부가 최소 조건이다.
- 이미 만들어진 `research_card`(간단이든 딥이든)를 피드/티커 상세에서 그냥
  보는 것은 무과금이다. 포인트는 "새로 만들거나 더 깊게 다시 만들 때"만
  소모한다.
- 요청이 들어오면 `research_gateway`가 해당 깊이로 TradingAgents 파이프라인을
  백그라운드로 트리거하고, 완료되면 `research_cards` 동기화 경로(아래)를 통해
  앱에 반영된다. 즉시 응답이 아니라 "분석 중" 상태를 거치는 비동기 흐름이다.

### 비용 전략

토큰 비용 때문에 실행 경로를 깊이별로 분리한다.

- **배치 경로 (무과금)**: `breaking_item` 생성과 백그라운드 `research_card`
  갱신, 그리고 `analysis_light`는 `.env.lowcost.example`의 Option A(로컬/
  Ollama, `TRADINGAGENTS_LOCAL_ONLY=true`)를 기본값으로 한다.
  `tradingagents/cost_guard.py`가 이미 이 설정을 감사한다.
- **딥 분석 경로 (포인트/현금 트리거)**: `analysis_deep`만 유료 모델을
  허용한다. 이때도 가장 비싼 모델이 아니라 `model_catalog.py`가 이미 "가장
  저비용"으로 분류해 둔 flash-lite 계열(현재 카탈로그 기준
  `gemini-3.1-flash-lite`)을 우선 쓴다. `pro`/`opus`/`sonnet`급 모델은 쓰지
  않는다 — `cost_guard.py`의 `EXPENSIVE_MODEL_HINTS`에 이미 걸러지는 대상이다.
- 사용자가 "2.5 플래시라이트"를 언급했지만, 현재 `model_catalog.py`에 등록된
  가장 저비용 Google 모델은 `gemini-3.1-flash-lite`다. 특정 버전을 코드에
  못박지 않고, "카탈로그의 최신 flash-lite 계열"을 쓰도록 설계해서 모델
  세대가 바뀌어도 문서를 다시 안 고치게 한다.

## Toss 증권 API 우선 활용

숫자(가격, 캔들, 환율, 랭킹, 장 캘린더)는 가능한 한 전부 Toss 증권 Open API
에서 가져온다. `docs/content_product_spec.md`, `docs/low_cost_execution_plan.md`
에 이미 원칙이 있고(read-only, 계좌/주문 API 차단), 이번 통합에서는 이걸
aimyticker 쪽까지 확장한다.

### 실제 엔드포인트 (developers.tossinvest.com/docs 기준)

Base: `https://openapi.tossinvest.com`. 인증은 OAuth 2.0 Client Credentials
(`POST /oauth2/token`) — 시세/종목/시장정보 카테고리는 발급받은 액세스 토큰만
있으면 호출 가능하고(계좌 헤더 불필요), 계좌·자산·주문 카테고리만
`X-Tossinvest-Account` 헤더가 추가로 필요하다.

사용할 것 (읽기 전용, 계좌 헤더 없이 호출 가능):

| 용도 | 엔드포인트 | Rate limit |
|---|---|---|
| 현재가 | `GET /api/v1/prices` | 10 TPS |
| 호가 | `GET /api/v1/orderbook` | 10 TPS |
| 체결 | `GET /api/v1/trades` | 10 TPS |
| 상/하한가 | `GET /api/v1/price-limits` | 10 TPS |
| 캔들(1분봉·일봉) | `GET /api/v1/candles` | 5 TPS |
| 종목 마스터 | `GET /api/v1/stocks?symbols=...` | 5 TPS |
| 매수 유의사항 | `GET /api/v1/stocks/{symbol}/warnings` | 5 TPS |
| 환율 KRW↔USD | `GET /api/v1/exchange-rate` | 3 TPS |
| 국내 장 캘린더 | `GET /api/v1/market-calendar/KR` | 3 TPS |
| 해외(미국) 장 캘린더 | `GET /api/v1/market-calendar/US` | 3 TPS |
| **랭킹(거래대금·거래량·등락률, TOP_GAINERS/TOP_LOSERS 포함)** | `GET /api/v1/rankings` | 5 TPS |
| 지수/국채 현재가·캔들 | `GET /api/v1/market-indicators/*` | 5~10 TPS |

절대 쓰지 않을 것 (계좌 헤더 필요, `content_product_spec.md`가 이미
차단하기로 한 범위와 정확히 일치): `GET /api/v1/accounts`,
`GET /api/v1/holdings`, `POST /api/v1/orders*`, `GET/DELETE
/api/v1/conditional-orders*`, `GET /api/v1/buying-power`,
`GET /api/v1/sellable-quantity`, `GET /api/v1/commissions`.

### 큰 발견: 랭킹 API가 "특징주 파악"을 이미 풀어준다

`GET /api/v1/rankings`가 거래대금·거래량·등락률 기준 랭킹(TOP_GAINERS,
TOP_LOSERS 포함)을 직접 제공한다. 즉 위쪽 "제품 색깔"에서 말한 "특징주
파악"을, `market_data.metrics`에서 임계값으로 걸러내는 파생 로직으로 직접
계산할 필요가 없다 — Toss가 이미 계산해서 주는 랭킹을 그대로 후보 소스로
쓰면 된다.

- `breaking_item`의 `notable_mover` 플래그는 이제 "자체 계산한 파생값"이
  아니라 "이번 배치에서 `/api/v1/rankings` TOP_GAINERS/TOP_LOSERS/거래량
  상위에 포함됐는가"로 정의를 바꾼다. 숫자를 만들지 않는다는 원칙에 더 잘
  맞는다 — Toss가 만든 숫자를 그대로 인용하는 것뿐이다.
- `candidate_gap`/`candidate_queue`가 후보를 넓히는 역할은 유지하되, 실시간
  "오늘 뜨는 종목" 후보의 1차 소스는 랭킹 API로 옮긴다.
- `TOP_GAINERS`/`TOP_LOSERS`는 `duration=realtime`을 지원하지 않는다
  (`unsupported-ranking-duration` 에러) — 배치 주기(예: 5~15분 간격 폴링)와
  자연스럽게 맞는다. 코인니스식 "계속 흐르는" 느낌은 배치 주기를 짧게 잡는
  것으로 만든다.

### 확인된 한계

- **ETF 보유종목(holdings) 엔드포인트가 없다.** Market Data/Stock Info
  카테고리 어디에도 holdings/구성종목 API가 없다. 기존 문서(`content_product_spec.md`)
  가 이미 "ETF holdings CSV/JSON: 운용사 또는 공개 파일"을 소스로 잡아둔 게
  맞다 — Toss로 대체할 수 없다. `scripts/import_etf_profile.py` 경로를 그대로
  유지한다.
- **티커명/키워드 검색 엔드포인트가 없다.** `GET /api/v1/stocks`는 `symbols`
  (심볼 코드 목록)만 받고 이름으로 찾는 fuzzy search가 아니다. 즉 앞서
  열린 질문으로 남겨뒀던 "Finnhub search를 Toss로 대체할 수 있는가"는
  답이 나왔다 — **대체 불가, `Search.tsx`/`api/finnhub.js`의 검색 기능은
  그대로 유지한다.**
- 계좌/자산/주문/조건주문 카테고리는 전부 차단 대상이므로 처음부터 볼 필요가
  없다.

### 정리된 우선순위

**Toss(무료/read-only, 숫자·랭킹 전부) > 배치 로컬 LLM(설명 문장 정리) >
포인트 트리거 flash-lite(딥 분석 내러티브)** 순이다. Finnhub/Yahoo는 Toss가
구조적으로 못 채우는 두 구멍(ETF holdings, 이름 검색)만 메우는 보조 소스로
남는다.

## aimyticker 쪽 변경

### 제거 (완료)

- `supabase/functions/translate-article/index.ts` (Gemini 호출부)
- `n8n_legacy/WF01_news_pipeline.json` (구 번역 파이프라인, 이미 legacy 취급 중)
- `Feed.tsx`, `Community.tsx`의 온디맨드 번역 상태 머신: `translatingId`,
  `translateArticle`, `waitForTranslation`, `refreshTranslatedArticle`,
  "한국어 요약 보기" 버튼, `translation_status === 'pending'/'translating'/'failed'`
  분기

### 신규

- Supabase Edge Function `sync-research-feed` (cron, 예: 5분 간격): TradingAgents
  `research_gateway`의 `/api/breaking`과 `/api/assets`를 호출해 두 테이블에
  upsert. `collect-news`(Finnhub/RSS 수집)와 `collect-social`은 당장은
  유지하되, breaking_item 소스가 안정화되면 대체 대상으로 표시해 둔다.
- DB: `news_articles`에서 `translation_status`, `translate_requested_at`,
  `translation_error` 컬럼을 제거하거나, TradingAgents의 `publish_gate.status`를
  그대로 반영하는 값(`ready`/`blocked`)으로 의미를 바꾼다. `title_ko`,
  `summary_ko`는 이제 sync 시점에 이미 채워져서 들어온다.
- 신규 테이블 `research_cards`: `content_snapshot` 구조를 그대로 저장
  (ticker, kind, sector/primary_sector, one_liner, why_moved,
  composition_data, market_data, visuals, publish_gate). `research_gateway`
  스키마와 1:1로 맞춰서 UI가 임의로 보유종목/비중을 추정하지 않도록 한다
  (`content_product_spec.md`의 원칙과 동일).
- `Sectors.tsx` 신규 화면: 섹터 목록 → 섹터 하위 테마 목록. 테마 상세에는
  "이 테마 ETF" 섹션을, ETF 상세(`TickerDetail.tsx`)에는 `primary_sector`
  배지+링크를 추가한다.
- `Feed.tsx`: 상단 고정 블록(오늘 뜨는 테마, 분석 요청 진입점 — 위 "포인트
  기반 온디맨드 분석" 참고) + 하단 연속 스트림(속보 N건마다 리서치 카드 1건
  인터리브, 코인니스 패턴, 구독 티커/특징주 우선순위 적용) 두 겹으로 구성한다.
  리서치 카드는 `composition_data`/`market_data`를 쓰는 새 컴포넌트
  (`ResearchCard`)로 렌더링하고, `publish_gate.status !== 'blocked'`인 것만
  노출한다.
- `Shop.tsx`: `SECTIONS`의 "포인트로 확장"에 `analysis_light` 아이템, 딥 분석은
  포인트 고가 책정 또는 `starter_pack`/`monthly_pass` 보유 조건으로 추가.
  요청 후 상태를 보여줄 `analysis_requests` 테이블(사용자, 티커, 깊이:
  `light`/`deep`, 상태: `pending`/`ready`/`failed`, 생성 시각) 신설.
- `TickerDetail.tsx`: 해당 티커에 `research_card`가 없으면 "분석 요청" 버튼을
  보여주고, `pending`이면 진행 상태를 보여준다.

### 유지 (스코프 밖)

Auth, Community(게시글/댓글), League(게임화), 푸시(`send-notifications`,
`compute-trending`)는 이번 통합과 무관하게 그대로 둔다. `compute-trending`이
나중에 TradingAgents 시그널을 참조하도록 만드는 건 후속 과제로만 남긴다.
`Shop.tsx`는 위 `analysis_request` 아이템 추가만 하고, `ticker_slot_5`/
`notif_boost_30`은 손대지 않는다.

## TradingAgents 쪽 변경

0. `scripts/collect_toss_rankings.py` 신설 (`collect_toss_market_snapshot.py`와
   동일한 패턴): `GET /api/v1/rankings`를 폴링해서 `toss_rankings_snapshot`
   아티팩트로 캐시한다. `breaking_feed.py`의 `notable_mover` 판정과 특징주
   후보의 1차 입력이 된다.
1. `tradingagents/breaking_feed.py` 신설: `content_snapshot.py`와 동일하게
   결정적(no-LLM 기본)으로 동작. 숫자를 만들지 않고, 출처 없는 원인을
   단정하지 않는 원칙을 그대로 따른다. `toss_rankings_snapshot`을 읽어
   `notable_mover` 후보 목록을 만든다.
2. `research_gateway.py`에 `/api/breaking` 라우트 추가. 기존
   `/api/assets`, `/api/themes`, `/api/reviews`, `/api/ops/status` 패턴을
   그대로 따라간다 (`schema_version`, `artifact` 필드 포함).
3. `research_gateway` 배포: **완료(파일럿 단계 형태로).** 원래 계획은 GCP
   e2-micro + Cloudflare Tunnel이었고 실제로 VM까지 만들어서 서비스를
   띄웠지만, 실제로 해보니 두 가지가 틀어졌다.
   - GCP는 2024년 정책 변경으로 VM에 붙는 외부 IPv4가 임시든 고정이든
     시간당 $0.005(월 ~$3.65, ~5,500원)로 과금된다 — "Always Free"는
     컴퓨트/디스크에만 해당하고 더 이상 완전 무료가 아니다. Fly.io
     (~$3-4/월)와 사실상 같은 가격대가 됐다.
   - Toss 증권 API가 IP 허용 목록을 요구해서, 새로 만든 GCP VM의 IP가
     `access_denied: IP address not allowed`로 막혔다. 등록된 로컬 IP가
     아니면 Toss 호출 자체가 안 된다.
   - 결론: 실제 서비스 전 파일럿 단계에서는 **로컬 맥에서
     `run_service_api.py` + `cloudflared tunnel --url`을 백그라운드로
     띄우는 방식**으로 임시 운영한다 — 비용 $0, 신규 IP 등록 불필요(이미
     Toss에 등록된 로컬 IP 사용), 대신 맥이 꺼지면 같이 꺼진다. GCP VM은
     정지 상태로 보존해 뒀다가 실제 상시 운영이 필요해지는 시점에 다시
     쓴다. 두 경로 모두 `docs/deploy_research_gateway.md`에 정리돼 있다.
   - `/api/*` 데이터 라우트에 Bearer API 키 인증 추가 (`RESEARCH_GATEWAY_API_KEY`
     미설정 시 인증 비활성 — 로컬 개발 기본값). HTML 라우트는 계속 공개.
   - `/healthz` 라이브니스 라우트 추가.
   - Toss 랭킹 수집을 별도 크론이 아니라 `tradingagents/scheduler.py`
     (asyncio 인프로세스 스케줄러)로 FastAPI 프로세스 안에서 5분 간격
     실행하도록 구현 (`--enable-background-jobs`). Render/Railway의 자체
     Cron 상품이 실행 서비스와 디스크를 공유 못 하는 문제를 플랫폼
     무관하게 피하는 선택.
   - `docker/entrypoint.sh`로 한 이미지가 `serve`(FastAPI)와
     `collect-rankings`/`build-queue`/`analyze-gap`(1회성) 두 모드를 다
     처리하도록 함. 인자 없이 실행하면 기존 `tradingagents` CLI 그대로
     동작 — `docker-compose.yml`의 기존 서비스는 안 건드림.
4. `POST /api/analyze` 라우트 추가: `{ticker, kind, depth}` (`depth`는
   `"light"` 또는 `"deep"`)를 받아 TradingAgents 파이프라인 실행을 큐에 넣고
   `{status: "queued", request_id}`를 반환한다. `depth=light`는
   `content_snapshot.py`(no-LLM)만 돌리고, `depth=deep`은 전체 멀티에이전트
   디베이트 파이프라인을 flash-lite 계열로 돌린다. 실행은 비동기이며,
   완료되면 해당 티커의 `content_snapshot`이 `/api/assets`에 새로 나타난다.
   `depth=deep` 실행 경로는 배치용 `/api/breaking` 생성 루프와 분리해서,
   배치 루프까지 유료 모델로 끌어올리지 않게 한다.
5. `/api/sectors`, `/api/sectors/{slug}` 라우트 추가 + `/api/themes/{slug}`
   응답에 `etfs: []` 필드 추가. 위 "섹터 > 테마 > 종목/ETF 탐색" 참고.

## 마이그레이션 순서

1. `research_gateway.py`에 `/api/breaking` 추가하고 로컬에서 `run_service_api.py`로
   더미 데이터 확인.
2. `research_gateway` 배포 위치 확정: **완료(파일럿 단계는 로컬 맥).**
   실제 API 키(RESEARCH_GATEWAY_API_KEY)와 `cloudflared` 임시 터널 URL을
   Supabase Edge Function 시크릿에 등록. GCP VM(`mati-edab4` 프로젝트,
   `research-gateway` 인스턴스)은 정지 상태로 남겨뒀다 — 상시 운영 필요
   시점에 재개. `cloudflared` quick tunnel이 한 번 죽어서 재연결 루프에
   빠진 걸 발견 — URL이 프로세스 생애주기에 묶여 있어서 재시작할 때마다
   Supabase 시크릿을 다시 갱신해야 한다는 걸 실전에서 확인했다.
3. aimyticker에 `sync-research-feed` Edge Function 작성, `research_cards` 테이블
   마이그레이션 추가: **완료, 실제로 끝까지 검증함.** 처음엔 아래 세
   가지가 순서대로 막혔었다.
   - 마이그레이션 033/034 파일만 커밋했지 실제 DB에 적용 안 함 →
     `research_cards` 테이블/`external_id` 컬럼이 없어서 `sync-research-feed`가
     5분마다 조용히 실패하고 있었다.
   - `sync-research-feed` Edge Function 코드를 커밋만 하고 **배포한 적이
     없었다** (`supabase functions deploy` 안 함) → 404. `supabase login` +
     `supabase link` + `supabase functions deploy sync-research-feed`로 해결.
   - `external_id`에 부분 유니크 인덱스(`where external_id is not null`)를
     썼더니 PostgREST의 `upsert(..., {onConflict})`가 `ON CONFLICT` 타겟을
     추론 못 함 → 마이그레이션 035로 일반 유니크 인덱스로 교체.
   세 가지 다 고친 뒤 수동 트리거로 `breaking: 200건`, `research_cards: 7건`
   업서트 성공, Feed.tsx에 리서치 카드 7개 실제 렌더링까지 스크린샷으로
   확인. **"마이그레이션 파일을 썼다"와 "Edge Function을 배포했다"는
   각각 별도로 확인해야 하는 단계라는 걸 이번에 배웠다** — 둘 다 코드
   작성만으로는 안 끝난다.
4. `Feed.tsx`에 `ResearchCard` 컴포넌트와 인터리브 로직 추가 (기존 뉴스 카드
   UI는 유지하되 데이터 소스만 sync 결과로 교체).
5. 번역 관련 코드 제거: **완료.** `translate-article` 함수,
   `Feed.tsx`/`Community.tsx`의 온디맨드 번역 상태(`translatingId`,
   `translateArticle`, `waitForTranslation`, 두 개의 번역 버튼),
   `WF01_news_pipeline.json` 전부 제거. `translation_status`/`title_ko`/
   `summary_ko` 컬럼과 타입은 그대로 뒀다 — `collect-news`가 아직
   Finnhub 기사를 미번역 상태로 계속 넣고 있어서, 지금은 그 기사들이
   원문 제목만 보이고 번역할 방법이 없다. 6번(컬럼 정리)과 7번
   (collect-news 대체 여부)이 정리될 때까지는 의도된 상태다.
6. `news_articles` 컬럼 정리 마이그레이션: **부분 완료.**
   `translate_requested_at`/`translation_error`(마이그레이션 034)는
   삭제 — `translate-article` 삭제 과정에서 `compute-trending`에도
   독립된 Gemini 자동 번역 블록이 숨어 있던 걸 발견해서 같이 제거했다
   (트렌딩 계산 로직 자체는 그대로 둠). `translation_status`/`title_ko`/
   `summary_ko`/`translated_at`은 `collect-news`가 계속 쓰고 있어서
   남겨뒀다 — 7번이 정리되기 전까지는 컬럼 자체가 살아있는 게 맞다.
7. 실사용 데이터로 카덴스/품질 확인 후 `collect-news`/`collect-social`을
   `breaking_item` 소스로 얼마나 대체할지 결정: **아직 미결.** 이 결정은
   문서에 적힌 대로 실사용 데이터가 전제 조건인데 아직 실제 서비스 전
   단계라 판단 근거가 없다. 지금 상태(Finnhub/Reddit 기사는 원문 언어
   그대로 노출, 번역 재시도 경로 없음)로 계속 두고, 실사용 데이터가
   쌓이면 그때 다시 본다.
8. (1~7 안정화 후) `/api/analyze` 라우트 + `analysis_requests` 테이블 +
   `Shop.tsx`의 `analysis_light`/`analysis_deep` 아이템 + `TickerDetail.tsx`의
   분석 요청 버튼. `depth=light`부터 먼저 붙이고, `depth=deep`(유료 모델 호출)
   은 그 다음이다 — 포인트 기반 온디맨드 분석은 배치 파이프라인이 안정된
   뒤에 얹는다.
9. `/api/sectors`, `/api/sectors/{slug}` + `/api/themes/{slug}`의 `etfs`
   필드 추가, aimyticker `Sectors.tsx` 화면. 종목/ETF 콘텐츠가 어느 정도
   쌓인 뒤(섹터당 테마가 최소 몇 개는 있어야 드릴다운이 의미 있음)에 붙이는
   게 자연스럽다 — 8번과 순서를 바꿔도 무방하다.

## 열린 질문

- ~~`research_gateway`를 어디에 상시 배포할지~~ 해결: GCP e2-micro +
  Cloudflare Tunnel (`docs/deploy_research_gateway.md`).
- breaking_item(Toss 랭킹)은 이제 인프로세스 스케줄러로 5분마다 갱신된다.
  다만 `research_card`(content_snapshot, candidate_gap 기반)는 여전히
  온디맨드 파일럿 스크립트 실행 위주라 상시 갱신 루프가 없다 — 딥 분석
  콘텐츠까지 "계속 흐르는" 카덴스로 만들려면 candidate 파이프라인도
  스케줄러에 잡으로 추가해야 한다 (지금은 범위 밖).
- breaking_item에 이미지/썸네일이 필요한지, 필요하면 어디서 가져올지.
- `translation_unlimited_until` 같은 Shop 과금 필드가 번역 레이어 제거 후에도
  의미가 있는지 — 번역이 무료/자동이 되므로 유료 아이템으로서는 폐기 대상에
  가깝다. `analysis_request`가 이 자리를 대신할 새 과금 축이다.
- `POST /api/analyze` 요청 남용 방지: 사용자당 동시 요청 수, 같은 티커 재요청
  쿨다운을 어디서 강제할지 (Supabase 쪽 vs `research_gateway` 쪽).
- "분석 중" 상태의 체감 대기 시간 — flash-lite 티어라도 멀티에이전트 파이프라인
  실행 시간이 몇 분 단위일 수 있어, `TickerDetail.tsx`에서 폴링/푸시 알림 중
  뭘 쓸지 정해야 한다.
- 국내+해외 겸용 섹터셋을 실제로 몇 개, 어떤 이름으로 정의할지 — 앤트위키의
  19개(국내 개별종목 기준)를 그대로 쓸 수 없고, 미국 종목/ETF까지 포함하는
  섹터 분류표를 별도로 확정해야 한다.
- `analysis_light`/`analysis_deep` 포인트 가격을 구체적으로 얼마로 잡을지 —
  `ticker_slot_5`(2,000P), `notif_boost_30`(1,500P) 대비 상대적 난이도로
  가늠은 되지만 실제 숫자는 비용 실측(Toss 호출량, flash-lite 토큰량) 후에
  정해야 한다.
