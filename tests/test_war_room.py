import json

import pytest

from tradingagents.war_room import (
    build_snapshot_from_report_tree,
    build_war_room_html,
    discover_report_dirs,
    load_snapshot,
    render_war_room_index,
    render_war_room,
)


def _snapshot():
    return {
        "schema_version": 1,
        "artifact": "analysis_snapshot",
        "ticker": "005930.KS",
        "asset_type": "stock",
        "market_adapter": "KR",
        "trade_date": "2026-07-07",
        "generated_at": "2026-07-07T11:17:11",
        "signal": {
            "schema_version": 1,
            "rating": "Hold",
            "action": "Hold",
            "bias": "neutral",
            "score": 0,
            "source": "portfolio_manager",
        },
        "source_flags": {
            "naver_news": True,
            "opendart": True,
            "fred": True,
        },
        "files": {
            "complete_report": "complete_report.md",
            "signal": "5_portfolio/signal.json",
            "snapshot": "analysis_snapshot.json",
        },
        "agents": [
            {
                "id": "market",
                "name": "Market Analyst",
                "team": "analysts",
                "status": "completed",
                "report_file": "1_analysts/market.md",
                "word_count": 12,
                "preview": "Price action is unstable.",
                "rating": "Hold",
            },
            {
                "id": "portfolio_manager",
                "name": "Portfolio Manager",
                "team": "portfolio",
                "status": "completed",
                "report_file": "5_portfolio/decision.md",
                "word_count": 20,
                "preview": "Hold and monitor risk.",
                "rating": "Hold",
            },
        ],
        "debates": {
            "research": {"bull_word_count": 100, "bear_word_count": 130},
            "risk": {
                "aggressive_word_count": 80,
                "neutral_word_count": 90,
                "conservative_word_count": 140,
            },
        },
        "ui": {
            "recommended_view": "war_room",
            "summary": "Maintain position and watch the 280000 KRW support.",
        },
    }


@pytest.mark.unit
def test_build_war_room_html_embeds_snapshot():
    html = build_war_room_html(_snapshot())

    assert "<!doctype html>" in html
    assert 'id="snapshot-data"' in html
    assert "005930.KS War Room" in html
    assert "Portfolio Brief" in html
    assert "complete_report.md" in html


@pytest.mark.unit
def test_render_war_room_writes_html(tmp_path):
    (tmp_path / "analysis_snapshot.json").write_text(
        json.dumps(_snapshot()),
        encoding="utf-8",
    )

    out = render_war_room(tmp_path)

    assert out == tmp_path / "war_room.html"
    content = out.read_text(encoding="utf-8")
    assert "Market Analyst" in content
    assert "War Room" in content


@pytest.mark.unit
def test_render_war_room_backfills_missing_snapshot(tmp_path):
    report_dir = tmp_path / "005930.KS_20260707_111711"
    (report_dir / "1_analysts").mkdir(parents=True)
    (report_dir / "2_research").mkdir()
    (report_dir / "3_trading").mkdir()
    (report_dir / "4_risk").mkdir()
    (report_dir / "5_portfolio").mkdir()
    (report_dir / "1_analysts" / "news.md").write_text(
        "Naver News and OpenDART Disclosures confirmed results.",
        encoding="utf-8",
    )
    (report_dir / "2_research" / "manager.md").write_text(
        "**Recommendation**: Hold",
        encoding="utf-8",
    )
    (report_dir / "3_trading" / "trader.md").write_text(
        "**Action**: Hold",
        encoding="utf-8",
    )
    (report_dir / "5_portfolio" / "decision.md").write_text(
        "**Rating**: Hold\n\nMaintain the position.",
        encoding="utf-8",
    )

    out = render_war_room(report_dir)

    snapshot = json.loads((report_dir / "analysis_snapshot.json").read_text(encoding="utf-8"))
    assert out.exists()
    assert snapshot["ticker"] == "005930.KS"
    assert snapshot["trade_date"] == "2026-07-07"
    assert snapshot["signal"]["rating"] == "Hold"
    assert snapshot["source_flags"]["naver_news"] is True
    assert snapshot["source_flags"]["opendart"] is True


@pytest.mark.unit
def test_render_war_room_index_writes_searchable_selector(tmp_path):
    samsung = tmp_path / "005930.KS_20260707_111711"
    nvidia = tmp_path / "NVDA_20260707_081711"
    for report_dir, rating in ((samsung, "Hold"), (nvidia, "Buy")):
        (report_dir / "5_portfolio").mkdir(parents=True)
        (report_dir / "complete_report.md").write_text(
            f"# {report_dir.name}\n\n{rating} report.",
            encoding="utf-8",
        )
        (report_dir / "5_portfolio" / "decision.md").write_text(
            f"**Rating**: {rating}\n\nKeep monitoring.",
            encoding="utf-8",
        )

    out = render_war_room_index(tmp_path)
    content = out.read_text(encoding="utf-8")

    assert out == tmp_path / "war_room_index.html"
    assert "TradingAgents War Rooms" in content
    assert "Search ticker, date, rating, keyword" in content
    assert "005930.KS" in content
    assert "NVDA" in content
    assert (samsung / "analysis_snapshot.json").exists()
    assert (samsung / "war_room.html").exists()
    assert (nvidia / "war_room.html").exists()


@pytest.mark.unit
def test_discover_report_dirs_orders_newest_names_first(tmp_path):
    old_report = tmp_path / "NVDA_20260706_081711"
    new_report = tmp_path / "NVDA_20260707_081711"
    ignored = tmp_path / "notes"
    for path in (old_report, new_report, ignored):
        path.mkdir()
    (old_report / "complete_report.md").write_text("old", encoding="utf-8")
    (new_report / "analysis_snapshot.json").write_text("{}", encoding="utf-8")

    assert discover_report_dirs(tmp_path) == [new_report, old_report]


@pytest.mark.unit
def test_build_snapshot_from_report_tree_parses_ticker_and_signal(tmp_path):
    report_dir = tmp_path / "NVDA_20260707_081711"
    (report_dir / "5_portfolio").mkdir(parents=True)
    (report_dir / "5_portfolio" / "decision.md").write_text(
        "**Rating**: Overweight\n\nKeep a positive bias.",
        encoding="utf-8",
    )

    snapshot = build_snapshot_from_report_tree(report_dir)

    assert snapshot["ticker"] == "NVDA"
    assert snapshot["trade_date"] == "2026-07-07"
    assert snapshot["signal"]["rating"] == "Overweight"


@pytest.mark.unit
def test_load_snapshot_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="analysis_snapshot.json not found"):
        load_snapshot(tmp_path)
