from datetime import datetime

import pytest

from tradingagents.breaking_feed import build_breaking_items, build_breaking_list_payload


def _rankings_snapshot(**overrides):
    base = {
        "schema_version": 1,
        "artifact": "toss_rankings_snapshot",
        "generated_at": "2026-07-10T09:30:00",
        "market_countries": ["KR", "US"],
        "ranking_types": ["TOP_GAINERS", "TOP_LOSERS"],
        "rankings": {
            "KR": {
                "TOP_GAINERS": [
                    {
                        "rank": 1,
                        "symbol": "005930",
                        "currency": "KRW",
                        "price": {"lastPrice": "56500", "basePrice": "55800", "changeRate": "0.0125"},
                        "tradingVolume": "18432100",
                        "tradingAmount": "1041436650000",
                    },
                ],
                "TOP_LOSERS": [],
            },
            "US": {
                "TOP_GAINERS": [],
                "TOP_LOSERS": [
                    {
                        "rank": 3,
                        "symbol": "TSLA",
                        "currency": "USD",
                        "price": {"lastPrice": "248.5", "basePrice": "251.2", "changeRate": "-0.0107"},
                        "tradingVolume": "342100",
                        "tradingAmount": "44942580",
                    },
                ],
            },
        },
        "ranked_at": {
            "KR": {"TOP_GAINERS": "2026-07-10T09:00:00+09:00", "TOP_LOSERS": None},
            "US": {"TOP_GAINERS": None, "TOP_LOSERS": "2026-07-09T21:00:00-04:00"},
        },
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_build_breaking_items_quotes_toss_ranking_without_recomputing():
    items = build_breaking_items(_rankings_snapshot(), generated_at=datetime(2026, 7, 10, 9, 30))

    by_ticker = {item["ticker"]: item for item in items}
    assert set(by_ticker) == {"005930", "TSLA"}

    kr = by_ticker["005930"]
    assert kr["market"] == "KR"
    assert kr["kind"] == "stock"
    assert kr["notable_mover"] is True
    assert kr["rankings"] == ["TOP_GAINERS"]
    assert "급등" in kr["headline_ko"]
    assert "1위" in kr["headline_ko"]
    assert "+1.25%" in kr["summary_ko"]
    assert "거래대금" in kr["summary_ko"]
    # Our own collection time, not Toss's rankedAt (see build_breaking_items).
    assert kr["published_at"] == "2026-07-10T09:30:00"
    assert kr["id"] == "breaking:KR:005930:2026-07-10"

    us = by_ticker["TSLA"]
    assert us["notable_mover"] is True
    assert "급락" in us["headline_ko"]
    assert "-1.07%" in us["summary_ko"]


@pytest.mark.unit
def test_build_breaking_items_headline_prefers_resolved_stock_name():
    snapshot = _rankings_snapshot(stock_names={
        "KR": {"005930": "삼성전자"},
        "US": {},
    })

    items = build_breaking_items(snapshot, generated_at=datetime(2026, 7, 10, 9, 30))
    by_ticker = {item["ticker"]: item for item in items}

    kr = by_ticker["005930"]
    assert kr["name"] == "삼성전자"
    assert "삼성전자 급등 1위" == kr["headline_ko"]

    # Toss didn't resolve TSLA in this fixture — falls back to the bare
    # symbol rather than fabricating a name.
    us = by_ticker["TSLA"]
    assert us["name"] is None
    assert us["headline_ko"].startswith("TSLA")


@pytest.mark.unit
def test_build_breaking_items_ticker_has_no_fabricated_suffix():
    # Toss rankings don't distinguish KOSPI/KOSDAQ, so we must not guess
    # a .KS/.KQ suffix onto the raw symbol.
    items = build_breaking_items(_rankings_snapshot())
    tickers = {item["ticker"] for item in items}
    assert "005930" in tickers
    assert not any(t.endswith((".KS", ".KQ")) for t in tickers)


@pytest.mark.unit
def test_build_breaking_items_merges_multiple_ranking_memberships():
    snapshot = _rankings_snapshot()
    # Same symbol also shows up in trading-amount leaders.
    snapshot["rankings"]["KR"]["TOP_LOSERS"] = []
    snapshot["rankings"].setdefault("KR", {})["MARKET_TRADING_AMOUNT"] = [
        {"rank": 5, "symbol": "005930", "currency": "KRW",
         "price": {"changeRate": "0.0125"}, "tradingVolume": "18432100", "tradingAmount": "1041436650000"},
    ]

    items = build_breaking_items(snapshot)
    row = next(item for item in items if item["ticker"] == "005930")

    assert set(row["rankings"]) == {"TOP_GAINERS", "MARKET_TRADING_AMOUNT"}
    # TOP_GAINERS still wins the headline over trading-amount ranking.
    assert "급등" in row["headline_ko"]
    assert row["notable_mover"] is True


@pytest.mark.unit
def test_build_breaking_items_handles_missing_price_fields():
    snapshot = _rankings_snapshot()
    snapshot["rankings"]["KR"]["TOP_GAINERS"][0]["price"] = {}
    snapshot["rankings"]["KR"]["TOP_GAINERS"][0]["tradingAmount"] = None

    items = build_breaking_items(snapshot)
    row = next(item for item in items if item["ticker"] == "005930")

    assert row["summary_ko"] == "Toss 랭킹에 등장했습니다."


@pytest.mark.unit
def test_build_breaking_items_rejects_wrong_artifact():
    with pytest.raises(ValueError, match="toss_rankings_snapshot"):
        build_breaking_items({"artifact": "toss_market_snapshot"})


@pytest.mark.unit
def test_build_breaking_list_payload_envelope():
    payload = build_breaking_list_payload(_rankings_snapshot(), generated_at=datetime(2026, 7, 10, 9, 30))

    assert payload["schema_version"] == 1
    assert payload["artifact"] == "service_breaking_list"
    assert payload["count"] == len(payload["items"])
    assert payload["count"] == 2
