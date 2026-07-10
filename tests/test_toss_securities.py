import pytest

from tradingagents.dataflows.toss_securities import (
    DEFAULT_BASE_URL,
    TOKEN_PATH,
    build_headers,
    build_url,
    credential_status,
    is_read_only_path,
    read_only_get,
    read_only_probe,
    token_request_body,
)


def _env():
    return {
        "TOSS_SECURITIES_API_KEY": "tsck_live_1234567890",
        "TOSS_SECURITIES_SECRET_KEY": "tssk_live_abcdefghi",
        "TOSS_SECURITIES_BASE_URL": "https://example.invalid",
    }


@pytest.mark.unit
def test_credential_status_masks_secrets():
    status = credential_status(_env())

    assert status.client_id_present is True
    assert status.client_secret_present is True
    assert status.base_url_present is True
    assert "1234567890" not in status.client_id_hint
    assert "abcdefghi" not in status.client_secret_hint
    assert status.ready_for_probe is True


@pytest.mark.unit
def test_toss_read_only_path_filter_blocks_sensitive_paths():
    assert is_read_only_path("/api/v1/prices") is True
    assert is_read_only_path("/api/v1/stocks") is True
    assert is_read_only_path("/api/v1/stocks/005930/warnings") is True
    assert is_read_only_path("/api/v1/market-indicators/KOSPI/candles") is True
    assert is_read_only_path("/orders") is False
    assert is_read_only_path("/account/balance") is False
    assert is_read_only_path("/api/v1/accounts") is False
    assert is_read_only_path("/portfolio") is False


@pytest.mark.unit
def test_build_url_adds_query_params():
    url = build_url("https://example.invalid/api", "api/v1/prices", {"symbols": "005930"})

    assert url == "https://example.invalid/api/api/v1/prices?symbols=005930"


@pytest.mark.unit
def test_default_base_url_is_official_toss_openapi_server():
    assert build_url("", TOKEN_PATH) == DEFAULT_BASE_URL + TOKEN_PATH


@pytest.mark.unit
def test_token_request_body_uses_client_credentials_form():
    body = token_request_body(_env()).decode("utf-8")

    assert "grant_type=client_credentials" in body
    assert "client_id=tsck_live_1234567890" in body
    assert "client_secret=tssk_live_abcdefghi" in body


@pytest.mark.unit
def test_build_headers_uses_bearer_token():
    headers = build_headers("abc.def")

    assert headers["Authorization"] == "Bearer abc.def"


@pytest.mark.unit
def test_read_only_probe_refuses_order_path_before_network():
    with pytest.raises(ValueError, match="Refusing non-read-only"):
        read_only_probe(env=_env(), path="/orders", timeout=0.01)


@pytest.mark.unit
def test_read_only_get_refuses_order_path_before_network():
    with pytest.raises(ValueError, match="Refusing non-read-only"):
        read_only_get(env=_env(), access_token="token", path="/api/v1/orders", timeout=0.01)


@pytest.mark.unit
def test_read_only_probe_requires_credentials():
    env = _env()
    env.pop("TOSS_SECURITIES_API_KEY")

    with pytest.raises(ValueError, match="client_id/client_secret"):
        read_only_probe(env=env, path="/api/v1/prices", timeout=0.01)
