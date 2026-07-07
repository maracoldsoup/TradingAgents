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
    "snapshot": "analysis_snapshot.json"
  },
  "agents": [],
  "debates": {},
  "ui": {}
}
```

## Intended UI Use

- Use `signal` for the top-level verdict badge.
- Use `agents` to render the analyst rooms/cards in order.
- Use `source_flags` to show which data feeds actually influenced the run.
- Use `files` to lazy-load full markdown only when the user opens a panel.
- Use `debates` for room intensity, timeline sizing, or replay pacing.
- Use `ui.recommended_view` as the default rendering mode.

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
