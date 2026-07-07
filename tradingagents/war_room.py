"""Standalone war-room viewer generation for analysis snapshots."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from tradingagents.graph.signal_processing import normalize_trade_signal
from tradingagents.reporting import build_analysis_snapshot


def load_snapshot(report_dir: str | Path) -> dict[str, Any]:
    """Load ``analysis_snapshot.json`` from a report directory."""
    report_path = Path(report_dir)
    snapshot_path = report_path / "analysis_snapshot.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"analysis_snapshot.json not found in {report_path}. "
            "Run a fresh analysis or save reports with the current code first."
        )
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def render_war_room(
    report_dir: str | Path,
    output_path: str | Path | None = None,
    backfill_snapshot: bool = True,
) -> Path:
    """Write a self-contained ``war_room.html`` for a saved report tree."""
    report_path = Path(report_dir)
    try:
        snapshot = load_snapshot(report_path)
    except FileNotFoundError:
        if not backfill_snapshot:
            raise
        snapshot = build_snapshot_from_report_tree(report_path)
        (report_path / "analysis_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    output = Path(output_path) if output_path else report_path / "war_room.html"
    output.write_text(build_war_room_html(snapshot), encoding="utf-8")
    return output


def render_war_room_index(
    reports_root: str | Path,
    output_path: str | Path | None = None,
    render_rooms: bool = True,
) -> Path:
    """Write an index page for choosing among report folders."""
    root = Path(reports_root)
    items = []
    for report_path in discover_report_dirs(root):
        snapshot_path = report_path / "analysis_snapshot.json"
        if snapshot_path.exists():
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        else:
            snapshot = build_snapshot_from_report_tree(report_path)
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if render_rooms:
            render_war_room(report_path)
        signal = snapshot.get("signal") or {}
        items.append(
            {
                "ticker": snapshot.get("ticker") or report_path.name,
                "trade_date": snapshot.get("trade_date") or "",
                "generated_at": snapshot.get("generated_at") or "",
                "rating": signal.get("rating") or "N/A",
                "action": signal.get("action") or "N/A",
                "bias": signal.get("bias") or "unknown",
                "score": signal.get("score"),
                "adapter": snapshot.get("market_adapter") or "N/A",
                "source_count": sum(1 for enabled in (snapshot.get("source_flags") or {}).values() if enabled),
                "summary": (snapshot.get("ui") or {}).get("summary") or "",
                "room_href": (report_path.relative_to(root) / "war_room.html").as_posix(),
                "report_href": (report_path.relative_to(root) / "complete_report.md").as_posix(),
                "folder": report_path.name,
            }
        )

    output = Path(output_path) if output_path else root / "war_room_index.html"
    output.write_text(build_war_room_index_html(items), encoding="utf-8")
    return output


def discover_report_dirs(reports_root: str | Path) -> list[Path]:
    """Return report directories under a reports root, newest-looking first."""
    root = Path(reports_root)
    if not root.exists():
        raise FileNotFoundError(f"reports root not found: {root}")
    report_dirs = [
        path
        for path in root.iterdir()
        if path.is_dir()
        and ((path / "complete_report.md").exists() or (path / "analysis_snapshot.json").exists())
    ]
    return sorted(report_dirs, key=lambda path: path.name, reverse=True)


def build_snapshot_from_report_tree(report_dir: str | Path) -> dict[str, Any]:
    """Best-effort snapshot builder for report folders created before snapshots."""
    report_path = Path(report_dir)
    ticker = _ticker_from_report_dir(report_path)
    trade_date = _trade_date_from_report_dir(report_path)
    final_decision = _read_text(report_path / "5_portfolio" / "decision.md")
    signal_path = report_path / "5_portfolio" / "signal.json"
    if signal_path.exists():
        trade_signal = json.loads(signal_path.read_text(encoding="utf-8"))
    elif final_decision:
        trade_signal = normalize_trade_signal(final_decision)
    else:
        trade_signal = None

    final_state = {
        "asset_type": "stock",
        "trade_date": trade_date,
        "market_report": _read_text(report_path / "1_analysts" / "market.md"),
        "sentiment_report": _read_text(report_path / "1_analysts" / "sentiment.md"),
        "news_report": _read_text(report_path / "1_analysts" / "news.md"),
        "fundamentals_report": _read_text(report_path / "1_analysts" / "fundamentals.md"),
        "investment_debate_state": {
            "bull_history": _read_text(report_path / "2_research" / "bull.md"),
            "bear_history": _read_text(report_path / "2_research" / "bear.md"),
            "judge_decision": _read_text(report_path / "2_research" / "manager.md"),
        },
        "trader_investment_plan": _read_text(report_path / "3_trading" / "trader.md"),
        "risk_debate_state": {
            "aggressive_history": _read_text(report_path / "4_risk" / "aggressive.md"),
            "neutral_history": _read_text(report_path / "4_risk" / "neutral.md"),
            "conservative_history": _read_text(report_path / "4_risk" / "conservative.md"),
            "judge_decision": final_decision,
        },
        "final_trade_decision": final_decision,
        "final_trade_signal": trade_signal,
    }
    return build_analysis_snapshot(final_state, ticker)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _ticker_from_report_dir(report_path: Path) -> str:
    name = report_path.name
    if "_" not in name:
        return name
    return name.rsplit("_", 2)[0]


def _trade_date_from_report_dir(report_path: Path) -> str | None:
    parts = report_path.name.rsplit("_", 2)
    if len(parts) < 2:
        return None
    stamp = parts[-2]
    if len(stamp) != 8 or not stamp.isdigit():
        return None
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"


def build_war_room_html(snapshot: dict[str, Any]) -> str:
    """Render a standalone HTML page from an analysis snapshot."""
    safe_json = html.escape(json.dumps(snapshot, ensure_ascii=False), quote=False)
    title = html.escape(f"{snapshot.get('ticker', 'Analysis')} War Room")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --ink: #f5efe3;
      --paper: #0f1117;
      --panel: #171b24;
      --panel-2: #202637;
      --line: #384052;
      --muted: #aeb6c8;
      --green: #4dd28a;
      --red: #ff6b72;
      --gold: #f4b84a;
      --cyan: #54c7ec;
      --violet: #a988ff;
      --shadow: rgba(0, 0, 0, 0.28);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 22% 12%, rgba(84,199,236,0.14), transparent 30%),
        radial-gradient(circle at 80% 0%, rgba(244,184,74,0.10), transparent 28%),
        linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px),
        linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
        var(--paper);
      background-size: auto, auto, 22px 22px, 22px 22px, auto;
    }}

    .app {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: 300px 1fr;
    }}

    aside {{
      border-right: 1px solid var(--line);
      background: rgba(13, 15, 22, 0.94);
      padding: 20px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}

    main {{
      padding: 22px;
      min-width: 0;
    }}

    h1, h2, h3, p {{ margin-top: 0; }}

    h1 {{
      font-size: 24px;
      line-height: 1.08;
      margin-bottom: 8px;
    }}

    h2 {{
      font-size: 15px;
      text-transform: uppercase;
      letter-spacing: 0;
      margin: 0 0 12px;
    }}

    h3 {{
      font-size: 15px;
      margin-bottom: 6px;
    }}

    .muted {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}

    .signal {{
      border: 2px solid var(--line);
      background: linear-gradient(180deg, #1f2635, #161b25);
      padding: 16px;
      box-shadow: 0 18px 44px var(--shadow);
      margin: 18px 0;
    }}

    .signal .rating {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 96px;
      height: 34px;
      border: 2px solid var(--line);
      background: var(--gold);
      color: #15110a;
      font-weight: 800;
      margin-bottom: 10px;
    }}

    .score-row {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-top: 12px;
    }}

    .score-row div {{
      border: 1px solid var(--line);
      background: #111722;
      padding: 8px;
      min-height: 54px;
    }}

    .score-row span {{
      display: block;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 4px;
    }}

    .source-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}

    .source {{
      border: 1px solid var(--line);
      padding: 8px;
      background: #111722;
      font-size: 12px;
      color: var(--muted);
    }}

    .source.on {{ border-left: 6px solid var(--green); }}
    .source.off {{ opacity: 0.48; }}

    .stage {{
      display: grid;
      grid-template-columns: repeat(4, minmax(170px, 1fr));
      gap: 14px;
      align-items: stretch;
    }}

    .zone {{
      margin-bottom: 22px;
    }}

    .card {{
      height: 238px;
      border: 1px solid var(--line);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.055), transparent 26%),
        var(--panel);
      box-shadow: 0 18px 44px var(--shadow);
      padding: 14px;
      position: relative;
      overflow: hidden;
      cursor: pointer;
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }}

    .card:hover {{
      transform: translateY(-3px);
      border-color: var(--accent, var(--cyan));
      background:
        linear-gradient(180deg, rgba(255,255,255,0.075), transparent 28%),
        var(--panel-2);
    }}

    .card::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 5px;
      background: var(--accent, var(--cyan));
    }}

    .agent-top {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }}

    .avatar {{
      width: 40px;
      height: 40px;
      border: 2px solid var(--line);
      background:
        linear-gradient(90deg, transparent 0 8px, rgba(0,0,0,0.22) 8px 10px, transparent 10px),
        linear-gradient(#f4c99a 0 22px, #253043 22px);
      image-rendering: pixelated;
      flex: 0 0 auto;
      position: relative;
    }}

    .avatar::after {{
      content: "";
      position: absolute;
      left: 8px;
      top: 11px;
      width: 5px;
      height: 5px;
      background: var(--line);
      box-shadow: 17px 0 0 var(--line);
    }}

    .team {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}

    .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      padding: 4px 7px;
      margin: 6px 6px 0 0;
      font-size: 12px;
      background: #111722;
      color: var(--ink);
    }}

    .preview {{
      font-size: 13px;
      line-height: 1.48;
      color: #d8deec;
      margin-top: 10px;
      display: -webkit-box;
      -webkit-line-clamp: 6;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    .open-link {{
      position: absolute;
      left: 14px;
      right: 14px;
      bottom: 12px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid rgba(255,255,255,0.08);
      padding-top: 8px;
    }}

    .meters {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 10px;
    }}

    .meter {{
      border: 2px solid var(--line);
      background: var(--panel);
      padding: 12px;
      min-height: 100px;
    }}

    .bar {{
      height: 12px;
      border: 1px solid var(--line);
      background: #111722;
      margin-top: 8px;
      overflow: hidden;
    }}

    .fill {{
      height: 100%;
      background: var(--accent, var(--green));
      width: 0%;
    }}

    .summary {{
      border: 2px solid var(--line);
      background:
        linear-gradient(135deg, rgba(84,199,236,0.16), rgba(244,184,74,0.08)),
        #151a24;
      color: #fff7e8;
      padding: 16px;
      box-shadow: 0 18px 44px var(--shadow);
      margin-bottom: 22px;
    }}

    .summary p {{
      color: #efe2c8;
      line-height: 1.55;
      margin-bottom: 0;
      display: -webkit-box;
      -webkit-line-clamp: 5;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    .links a {{
      color: var(--cyan);
      text-decoration: none;
      border-bottom: 1px solid var(--cyan);
    }}

    @media (max-width: 980px) {{
      .app {{ grid-template-columns: 1fr; }}
      aside {{ position: static; height: auto; border-right: 0; border-bottom: 2px solid var(--line); }}
      .stage {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}

    @media (max-width: 620px) {{
      main, aside {{ padding: 16px; }}
      .stage, .meters, .score-row {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 23px; }}
    }}
  </style>
</head>
<body>
  <script id="snapshot-data" type="application/json">{safe_json}</script>
  <div class="app">
    <aside>
      <h1 id="title"></h1>
      <p class="muted" id="meta"></p>
      <section class="signal">
        <div class="rating" id="rating"></div>
        <p class="muted" id="bias"></p>
        <div class="score-row">
          <div><span>Action</span><strong id="action"></strong></div>
          <div><span>Score</span><strong id="score"></strong></div>
          <div><span>Adapter</span><strong id="adapter"></strong></div>
        </div>
      </section>
      <h2>Sources</h2>
      <div class="source-grid" id="sources"></div>
      <p class="muted links" style="margin-top:16px">
        Open <a href="complete_report.md">complete_report.md</a> for the full report.
        <br>
        Back to <a href="../war_room_index.html">war_room_index.html</a>.
      </p>
    </aside>
    <main>
      <section class="summary">
        <h2>Portfolio Brief</h2>
        <p id="summary"></p>
      </section>
      <section class="zone">
        <h2>Analyst Floor</h2>
        <div class="stage" id="analysts"></div>
      </section>
      <section class="zone">
        <h2>Decision Chain</h2>
        <div class="stage" id="decision-chain"></div>
      </section>
      <section class="zone">
        <h2>Debate Heat</h2>
        <div class="meters" id="debates"></div>
      </section>
    </main>
  </div>
  <script>
    const snapshot = JSON.parse(document.getElementById("snapshot-data").textContent);
    const signal = snapshot.signal || {{}};
    const title = `${{snapshot.ticker || "Analysis"}} Command Room`;
    document.getElementById("title").textContent = title;
    document.getElementById("meta").textContent =
      `${{snapshot.trade_date || "No date"}} · ${{snapshot.asset_type || "asset"}} · ${{snapshot.generated_at || ""}}`;
    document.getElementById("rating").textContent = signal.rating || "N/A";
    document.getElementById("bias").textContent = `Bias: ${{signal.bias || "unknown"}}`;
    document.getElementById("action").textContent = signal.action || "N/A";
    document.getElementById("score").textContent = signal.score ?? "N/A";
    document.getElementById("adapter").textContent = snapshot.market_adapter || "N/A";
    document.getElementById("summary").textContent =
      compact(cleanMarkdown(snapshot.ui?.summary || "No summary available."), 520);

    const accents = ["#2f7d90", "#c48b31", "#6f5aa8", "#2f8f5b", "#b84a4a"];
    const agents = snapshot.agents || [];
    const analystRoot = document.getElementById("analysts");
    const chainRoot = document.getElementById("decision-chain");

    function card(agent, index) {{
      const el = document.createElement("article");
      el.className = "card";
      el.style.setProperty("--accent", accents[index % accents.length]);
      const label = agent.rating || agent.recommendation || agent.action || "Review";
      const preview = compact(cleanMarkdown(agent.preview || "No report preview available."), 360);
      const reportFile = agent.report_file || "";
      if (reportFile) {{
        el.addEventListener("click", () => window.location.href = reportFile);
      }}
      el.innerHTML = `
        <div class="agent-top">
          <div class="avatar" aria-hidden="true"></div>
          <div>
            <h3>${{escapeHtml(agent.name || agent.id || "Agent")}}</h3>
            <div class="team">${{escapeHtml(agent.team || "team")}}</div>
          </div>
        </div>
        <span class="pill">${{escapeHtml(label)}}</span>
        <span class="pill">${{agent.word_count || 0}} words</span>
        <p class="preview">${{escapeHtml(preview)}}</p>
        <div class="open-link">${{reportFile ? "Open source report" : "No source file"}}</div>
      `;
      return el;
    }}

    agents.forEach((agent, index) => {{
      const target = agent.team === "analysts" ? analystRoot : chainRoot;
      target.appendChild(card(agent, index));
    }});

    const sourceRoot = document.getElementById("sources");
    Object.entries(snapshot.source_flags || {{}}).forEach(([name, on]) => {{
      const el = document.createElement("div");
      el.className = `source ${{on ? "on" : "off"}}`;
      el.textContent = name.replaceAll("_", " ");
      sourceRoot.appendChild(el);
    }});

    const debateRoot = document.getElementById("debates");
    const debateEntries = [
      ["Bull Research", snapshot.debates?.research?.bull_word_count || 0, "#2f8f5b"],
      ["Bear Research", snapshot.debates?.research?.bear_word_count || 0, "#b84a4a"],
      ["Aggressive Risk", snapshot.debates?.risk?.aggressive_word_count || 0, "#c48b31"],
      ["Neutral Risk", snapshot.debates?.risk?.neutral_word_count || 0, "#2f7d90"],
      ["Conservative Risk", snapshot.debates?.risk?.conservative_word_count || 0, "#6f5aa8"]
    ];
    const maxWords = Math.max(1, ...debateEntries.map(([, count]) => count));
    debateEntries.forEach(([name, count, color]) => {{
      const el = document.createElement("div");
      el.className = "meter";
      const pct = Math.max(5, Math.round((count / maxWords) * 100));
      el.innerHTML = `
        <h3>${{escapeHtml(name)}}</h3>
        <div class="muted">${{count}} words</div>
        <div class="bar"><div class="fill" style="width:${{pct}}%; background:${{color}}"></div></div>
      `;
      debateRoot.appendChild(el);
    }});

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }}

    function cleanMarkdown(value) {{
      return String(value || "")
        .replace(/```[\\s\\S]*?```/g, " ")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/\\*\\*([^*]+)\\*\\*/g, "$1")
        .replace(/\\*([^*]+)\\*/g, "$1")
        .replace(/#+\\s*/g, "")
        .replace(/\\|/g, " ")
        .replace(/-{3,}/g, " ")
        .replace(/\\s+/g, " ")
        .trim();
    }}

    function compact(value, max) {{
      const text = String(value || "").trim();
      if (text.length <= max) return text;
      return text.slice(0, max - 1).trimEnd() + "...";
    }}
  </script>
</body>
</html>
"""


def build_war_room_index_html(items: list[dict[str, Any]]) -> str:
    """Render an index for choosing report war rooms."""
    safe_json = html.escape(json.dumps(items, ensure_ascii=False), quote=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TradingAgents War Rooms</title>
  <style>
    :root {{
      --bg: #0f1117;
      --panel: #171b24;
      --panel-2: #202637;
      --line: #384052;
      --text: #f5efe3;
      --muted: #aeb6c8;
      --green: #4dd28a;
      --red: #ff6b72;
      --gold: #f4b84a;
      --cyan: #54c7ec;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at 20% 0%, rgba(84,199,236,0.14), transparent 30%),
        radial-gradient(circle at 85% 12%, rgba(244,184,74,0.10), transparent 28%),
        var(--bg);
    }}
    .wrap {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 28px;
    }}
    header {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 18px;
      align-items: end;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 32px;
      letter-spacing: 0;
    }}
    .muted {{ color: var(--muted); }}
    .controls {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) repeat(3, 150px);
      gap: 10px;
      margin-bottom: 16px;
    }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #111722;
      color: var(--text);
      padding: 11px 12px;
      font-size: 14px;
      outline: none;
    }}
    input:focus, select:focus {{ border-color: var(--cyan); }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 16px;
    }}
    .stat {{
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 12px;
    }}
    .stat span {{
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 5px;
    }}
    .stat strong {{ font-size: 20px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(240px, 1fr));
      gap: 14px;
    }}
    .card {{
      border: 1px solid var(--line);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.055), transparent 28%),
        var(--panel);
      min-height: 218px;
      padding: 15px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      color: inherit;
      text-decoration: none;
      box-shadow: 0 18px 44px rgba(0,0,0,0.24);
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }}
    .card:hover {{
      transform: translateY(-3px);
      border-color: var(--cyan);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.075), transparent 28%),
        var(--panel-2);
    }}
    .top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }}
    .ticker {{
      font-size: 24px;
      font-weight: 850;
      line-height: 1;
    }}
    .date {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 5px;
    }}
    .rating {{
      border: 1px solid var(--line);
      background: var(--gold);
      color: #17120f;
      padding: 6px 9px;
      font-weight: 850;
      min-width: 82px;
      text-align: center;
    }}
    .rating.Buy, .rating.Overweight {{ background: var(--green); }}
    .rating.Sell, .rating.Underweight {{ background: var(--red); color: #fff; }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
    }}
    .chip {{
      border: 1px solid var(--line);
      background: #111722;
      padding: 5px 8px;
      color: var(--muted);
      font-size: 12px;
    }}
    .summary {{
      color: #dbe2ef;
      font-size: 13px;
      line-height: 1.48;
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .empty {{
      display: none;
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }}
    @media (max-width: 980px) {{
      header, .controls {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: repeat(2, 1fr); }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 640px) {{
      .wrap {{ padding: 16px; }}
      .stats, .grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 26px; }}
    }}
  </style>
</head>
<body>
  <script id="rooms-data" type="application/json">{safe_json}</script>
  <div class="wrap">
    <header>
      <div>
        <h1>TradingAgents War Rooms</h1>
        <div class="muted">Choose a ticker, review the latest signal, then open the room.</div>
      </div>
      <div class="muted" id="count"></div>
    </header>

    <section class="controls" aria-label="Report filters">
      <input id="search" type="search" placeholder="Search ticker, date, rating, keyword">
      <select id="rating-filter">
        <option value="">All ratings</option>
        <option>Buy</option>
        <option>Overweight</option>
        <option>Hold</option>
        <option>Underweight</option>
        <option>Sell</option>
      </select>
      <select id="adapter-filter">
        <option value="">All markets</option>
      </select>
      <select id="sort">
        <option value="newest">Newest first</option>
        <option value="ticker">Ticker A-Z</option>
        <option value="score">Score high-low</option>
      </select>
    </section>

    <section class="stats">
      <div class="stat"><span>Total rooms</span><strong id="stat-total">0</strong></div>
      <div class="stat"><span>Visible</span><strong id="stat-visible">0</strong></div>
      <div class="stat"><span>Markets</span><strong id="stat-markets">0</strong></div>
      <div class="stat"><span>Latest date</span><strong id="stat-latest">-</strong></div>
    </section>

    <section class="grid" id="grid"></section>
    <section class="empty" id="empty">No report rooms match the current filters.</section>
  </div>

  <script>
    const rooms = JSON.parse(document.getElementById("rooms-data").textContent);
    const grid = document.getElementById("grid");
    const search = document.getElementById("search");
    const ratingFilter = document.getElementById("rating-filter");
    const adapterFilter = document.getElementById("adapter-filter");
    const sortSelect = document.getElementById("sort");
    const adapters = [...new Set(rooms.map(room => room.adapter).filter(Boolean))].sort();
    adapters.forEach(adapter => {{
      const option = document.createElement("option");
      option.value = adapter;
      option.textContent = adapter;
      adapterFilter.appendChild(option);
    }});

    document.getElementById("stat-total").textContent = rooms.length;
    document.getElementById("stat-markets").textContent = adapters.length;
    document.getElementById("stat-latest").textContent = rooms[0]?.trade_date || "-";
    document.getElementById("count").textContent = `${{rooms.length}} report rooms`;

    [search, ratingFilter, adapterFilter, sortSelect].forEach(el => el.addEventListener("input", render));
    render();

    function render() {{
      const q = clean(search.value).toLowerCase();
      const rating = ratingFilter.value;
      const adapter = adapterFilter.value;
      let visible = rooms.filter(room => {{
        const haystack = clean(`${{room.ticker}} ${{room.trade_date}} ${{room.rating}} ${{room.adapter}} ${{room.summary}} ${{room.folder}}`).toLowerCase();
        return (!q || haystack.includes(q))
          && (!rating || room.rating === rating)
          && (!adapter || room.adapter === adapter);
      }});
      if (sortSelect.value === "ticker") {{
        visible = visible.sort((a, b) => String(a.ticker).localeCompare(String(b.ticker)));
      }} else if (sortSelect.value === "score") {{
        visible = visible.sort((a, b) => Number(b.score ?? -99) - Number(a.score ?? -99));
      }} else {{
        visible = visible.sort((a, b) => String(b.folder).localeCompare(String(a.folder)));
      }}

      document.getElementById("stat-visible").textContent = visible.length;
      document.getElementById("empty").style.display = visible.length ? "none" : "block";
      grid.innerHTML = "";
      visible.forEach(room => grid.appendChild(card(room)));
    }}

    function card(room) {{
      const el = document.createElement("a");
      el.className = "card";
      el.href = room.room_href;
      const ratingClass = String(room.rating || "N/A").replace(/[^A-Za-z]/g, "");
      el.innerHTML = `
        <div class="top">
          <div>
            <div class="ticker">${{escapeHtml(room.ticker)}}</div>
            <div class="date">${{escapeHtml(room.trade_date || "No date")}} · ${{escapeHtml(room.folder || "")}}</div>
          </div>
          <div class="rating ${{ratingClass}}">${{escapeHtml(room.rating || "N/A")}}</div>
        </div>
        <div class="chips">
          <span class="chip">Action ${{escapeHtml(room.action || "N/A")}}</span>
          <span class="chip">Score ${{room.score ?? "N/A"}}</span>
          <span class="chip">${{escapeHtml(room.adapter || "N/A")}}</span>
          <span class="chip">${{room.source_count || 0}} sources</span>
        </div>
        <div class="summary">${{escapeHtml(compact(clean(room.summary), 360))}}</div>
      `;
      return el;
    }}

    function clean(value) {{
      return String(value || "")
        .replace(/```[\\s\\S]*?```/g, " ")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/\\*\\*([^*]+)\\*\\*/g, "$1")
        .replace(/\\*([^*]+)\\*/g, "$1")
        .replace(/#+\\s*/g, "")
        .replace(/\\|/g, " ")
        .replace(/-{3,}/g, " ")
        .replace(/\\s+/g, " ")
        .trim();
    }}

    function compact(value, max) {{
      const text = String(value || "").trim();
      if (text.length <= max) return text;
      return text.slice(0, max - 1).trimEnd() + "...";
    }}

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }}
  </script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a standalone TradingAgents war room.")
    parser.add_argument("report_dir", help="Report directory containing analysis_snapshot.json")
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to <report_dir>/war_room.html",
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="Fail instead of rebuilding analysis_snapshot.json from markdown files.",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Treat the path as a reports root and render war_room_index.html.",
    )
    args = parser.parse_args(argv)
    if args.index:
        output = render_war_room_index(
            args.report_dir,
            args.output,
            render_rooms=not args.no_backfill,
        )
    else:
        output = render_war_room(args.report_dir, args.output, backfill_snapshot=not args.no_backfill)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
