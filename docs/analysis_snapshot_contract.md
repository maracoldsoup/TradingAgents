# Analysis Snapshot Contract

`analysis_snapshot.json` is the compact handoff file for UI, replay, and future
video/war-room rendering. It is written next to `complete_report.md` whenever a
report tree is saved.

## Location

```text
reports/<ticker>_<timestamp>/analysis_snapshot.json
```

Related files in the same report tree:

```text
complete_report.md
content_snapshot.json
1_analysts/*.md
2_research/*.md
3_trading/trader.md
4_risk/*.md
5_portfolio/decision.md
5_portfolio/signal.json
```

## Core Shape

```json
{
  "schema_version": 1,
  "artifact": "analysis_snapshot",
  "ticker": "005930.KS",
  "asset_type": "stock",
  "market_adapter": "KR",
  "trade_date": "2026-07-07",
  "generated_at": "2026-07-07T11:17:11",
  "instrument_context": "Company: ...",
  "signal": {
    "schema_version": 1,
    "rating": "Hold",
    "action": "Hold",
    "bias": "neutral",
    "score": 0,
    "source": "portfolio_manager"
  },
  "source_flags": {
    "naver_news": true,
    "opendart": true,
    "naver_datalab": true,
    "fred": true,
    "polymarket": true,
    "yfinance": false,
    "reddit": true,
    "stocktwits": true
  },
  "files": {
    "complete_report": "complete_report.md",
    "signal": "5_portfolio/signal.json",
    "snapshot": "analysis_snapshot.json",
    "content_snapshot": "content_snapshot.json"
  },
  "agents": [],
  "debates": {},
  "ui": {},
  "content": {
    "snapshot_file": "content_snapshot.json",
    "audience": "beginner",
    "supports": ["stock", "etf", "theme", "crypto"]
  }
}
```

## Intended UI Use

- Use `signal` for the top-level verdict badge.
- Use `agents` to render the analyst rooms/cards in order.
- Use `source_flags` to show which data feeds actually influenced the run.
- Use `files` to lazy-load full markdown only when the user opens a panel.
- Use `debates` for room intensity, timeline sizing, or replay pacing.
- Use `ui.recommended_view` as the default rendering mode.
- Use `content.snapshot_file` for beginner-facing card/news/video rendering.

## Content Snapshot

`content_snapshot.json` is a no-LLM publishing handoff generated from the same
final state. It is intentionally conservative: it never invents ETF holdings,
theme constituents, or missing price levels.

Core shape:

```json
{
  "schema_version": 1,
  "artifact": "content_snapshot",
  "ticker": "SMH",
  "asset_type": "etf",
  "market_adapter": "US",
  "content_type": "etf",
  "audience": "beginner",
  "presentation": {
    "tone": "antwiki_like"
  },
  "cards": [],
  "visuals": [],
  "composition_data": {
    "profile_type": "etf",
    "holdings": [{"ticker": "NVDA", "name": "NVIDIA", "weight_pct": 20.1}],
    "sectors": [{"name": "Semiconductors", "weight_pct": 65.0}],
    "countries": [{"name": "United States", "weight_pct": 80.0}]
  },
  "market_data": {
    "source": "toss_securities_openapi",
    "snapshot_file": ".pilot/toss_market/AAPL.json",
    "coverage": {"prices": true, "candles": {"AAPL": true}},
    "candle_count": 60,
    "metrics": {
      "latest_close": 313.32,
      "return_1d_pct": 1.2,
      "return_5d_pct": -0.8,
      "return_20d_pct": 4.1,
      "high_60d": 330.0,
      "low_60d": 280.0,
      "volume_vs_20d_avg": 1.4
    }
  },
  "publish_gate": {
    "status": "blocked",
    "reasons": ["required_visual_data_missing:etf_top_holdings"]
  }
}
```

Publishing rules:

- ETF content requires holdings, sector allocation, and country allocation visuals.
- Theme content requires a value-chain map and representative names.
- Incomplete `signal.levels` hides the price ladder, but does not block a stock article.
- Cards are explanatory content blocks, not investment advice.
- If `market_data` is present and contains candles for the ticker, `price_trend`
  and `volume_change` visuals can be marked `ready`.
- `composition_data` carries normalized ETF/theme rows for UI rendering. The UI
  must not scrape card text to infer holdings, sector weights, or theme members.
- `market_data.metrics` is derived only from attached candle rows and should be
  treated as display data, not a trading recommendation.

Toss read-only market snapshots can be collected without an LLM:

```bash
python scripts/collect_toss_market_snapshot.py \
  --env-file .env \
  --candle-count 60 \
  005930.KS AAPL

python scripts/run_content_pilot.py \
  --limit 20 \
  --output-dir .pilot/content_with_market \
  --market-snapshot-dir .pilot/toss_market
```

The resulting `toss_market_snapshot` artifact contains stock info, current
prices, daily candles, optional USD/KRW FX, market calendars, rate-limit headers,
and endpoint errors. It must not include account, asset, order, buy, sell, or
transfer data.

Structured profile pilots can generate stock/ETF/theme snapshots without an LLM:

```bash
python scripts/run_profile_content_pilot.py \
  --profiles docs/examples/content_profiles.sample.json \
  --output-dir .pilot/profiles \
  --market-snapshot-dir .pilot/toss_market
```

`--profiles` may point to a single JSON file or a directory of direct child
profile JSON files. Directory mode is the preferred local batch path for 20-30
candidate stock/ETF/theme profiles.

Stock profile inputs:

- `profile_type: "stock"`
- `ticker`, `name`, optional `exchange`, `country`, `currency`
- optional `sector`, `industry`, `description`
- `business_lines`: rows with `name` and optional `weight_pct`
- `regions`: rows with `name` and optional `weight_pct`
- optional `products`, `peers`, `catalysts`, `risks`
- If no market snapshot is attached, price/volume visuals stay `needs_data`.

ETF profile inputs:

- `profile_type: "etf"`
- `ticker`, `name`, optional `issuer`, `benchmark`, `expense_ratio_pct`, `aum`
- `holdings`: rows with `ticker` or `name`, plus optional `weight_pct`, `sector`, `country`
- `sectors`: rows with `name` and `weight_pct`
- `countries`: rows with `name` and `weight_pct`

Local ETF CSV/JSON imports can create the same profile shape without an LLM:

```bash
python scripts/import_etf_profile.py \
  --holdings docs/examples/etf_holdings/demo_global_ai_holdings.csv \
  --ticker DEMOIMPORT \
  --name "CSV 임포트 AI ETF 데모" \
  --issuer "Demo Asset" \
  --currency USD \
  --as-of 2026-07-09 \
  --source docs/examples/etf_holdings/demo_global_ai_holdings.csv \
  --output .pilot/imported_profiles/demo_imported_etf.json
```

The importer recognizes common holding columns such as `Ticker`, `Symbol`,
`Name`, `Weight (%)`, `Sector`, and `Country`, then derives sector and country
allocation by summing holding weights.

Theme profile inputs:

- `profile_type: "theme"`
- `ticker`, `name`, optional `description`
- `value_chain`: rows with `stage`, optional `domestic_names`, `global_names`, `metrics`
- `domestic_names` and/or `global_names`
- optional `catalysts`, `risks`

Local theme CSV/JSON imports can create the same profile shape without an LLM:

```bash
python scripts/import_theme_profile.py \
  --theme-map docs/examples/theme_maps/demo_ai_semiconductor_theme.csv \
  --ticker KR-AI-SEMI-CSV \
  --name "CSV AI 반도체 테마" \
  --description "CSV에서 가져온 AI 반도체 밸류체인입니다." \
  --as-of 2026-07-09 \
  --source docs/examples/theme_maps/demo_ai_semiconductor_theme.csv \
  --output .pilot/imported_profiles/demo_imported_theme.json
```

The importer recognizes common theme-map columns such as `Stage`,
`Description`, `Scope`, `Ticker`, `Name`, `Role`, `Market`, `Country`,
`Catalysts`, `Risks`, and `Metrics`, then groups rows into value-chain stages
with domestic/global representative names.

The sample file is schema-only demo data and must not be published as market data.

Static content previews can be rendered locally:

```bash
python scripts/render_content_preview.py \
  --input-dir .pilot/content_with_market \
  --output .pilot/preview/index.html

python scripts/render_content_preview.py \
  --input-dir .pilot/local/profiles \
  --output .pilot/preview/profiles.html \
  --title "TradingAgents Stock ETF Theme Profile Preview"
```

The profile preview renders stock business/region/product composition, ETF
holdings, sector/country allocation, theme value chains, and domestic/global
representative names from `composition_data`.

## Next Steps

1. Render the report index for easy ticker selection:

   ```bash
   python scripts/render_war_room.py --index reports
   ```

   This writes `reports/war_room_index.html`, discovers saved report folders,
   backfills snapshots when needed, and generates each folder's `war_room.html`.

2. Render one standalone local viewer directly:

   ```bash
   python scripts/render_war_room.py reports/005930.KS_20260707_111711
   ```

   This writes `war_room.html` into the report directory. If the report was
   created before `analysis_snapshot.json` existed, the renderer backfills a
   best-effort snapshot from the markdown report tree and `signal.json`.

3. Open `war_room_index.html` or a specific `war_room.html` in a browser.
4. Add a replay timeline from message/tool logs.
5. Export the replay as a vertical short once the viewer is stable.
