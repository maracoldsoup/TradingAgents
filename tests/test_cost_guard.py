import pytest

from tradingagents.cost_guard import assess_low_cost_config, config_from_env, merge_env


@pytest.mark.unit
def test_low_cost_guard_passes_local_ollama_preset():
    result = assess_low_cost_config({
        "llm_provider": "ollama",
        "quick_think_llm": "qwen3:latest",
        "deep_think_llm": "qwen3:latest",
        "max_debate_rounds": 0,
        "max_risk_discuss_rounds": 0,
        "parallel_analysts": False,
        "checkpoint_enabled": True,
    })

    assert result.status == "pass"
    assert result.score == 100
    assert result.passed is True
    assert "provider:ollama:keyless_local" in result.findings


@pytest.mark.unit
def test_low_cost_guard_fails_expensive_parallel_default_shape():
    result = assess_low_cost_config({
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.4-mini",
        "deep_think_llm": "gpt-5.5",
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "parallel_analysts": True,
        "checkpoint_enabled": False,
    })

    assert result.status == "fail"
    assert any(finding.startswith("model:deep:expensive") for finding in result.findings)
    assert "parallel_analysts:true:burst_rpm_risk" in result.findings
    assert any("MAX_DEBATE_ROUNDS=0" in rec for rec in result.recommendations)


@pytest.mark.unit
def test_low_cost_guard_does_not_treat_gemini_as_mini():
    result = assess_low_cost_config({
        "llm_provider": "google",
        "quick_think_llm": "gemini-3.5-flash",
        "deep_think_llm": "gemini-2.5-pro",
        "max_debate_rounds": 0,
        "max_risk_discuss_rounds": 0,
        "parallel_analysts": False,
        "checkpoint_enabled": True,
    })

    assert result.status == "fail"
    assert any(finding == "model:deep:expensive:gemini-2.5-pro" for finding in result.findings)
    assert not any(finding == "model:deep:low_cost:gemini-2.5-pro" for finding in result.findings)


@pytest.mark.unit
def test_low_cost_guard_accepts_google_flash_lite_pilot():
    result = assess_low_cost_config({
        "llm_provider": "google",
        "quick_think_llm": "gemini-3.1-flash-lite",
        "deep_think_llm": "gemini-3.1-flash-lite",
        "google_thinking_level": "minimal",
        "max_debate_rounds": 0,
        "max_risk_discuss_rounds": 0,
        "parallel_analysts": False,
        "checkpoint_enabled": True,
    })

    assert result.status == "pass"
    assert "provider:google:low_cost_models" in result.findings
    assert result.recommendations == []


@pytest.mark.unit
def test_low_cost_guard_local_only_rejects_google_flash_lite_pilot():
    result = assess_low_cost_config({
        "local_only": True,
        "llm_provider": "google",
        "quick_think_llm": "gemini-3.1-flash-lite",
        "deep_think_llm": "gemini-3.1-flash-lite",
        "google_thinking_level": "minimal",
        "max_debate_rounds": 0,
        "max_risk_discuss_rounds": 0,
        "parallel_analysts": False,
        "checkpoint_enabled": True,
    })

    assert result.status == "fail"
    assert "local_only:google:external_provider_blocked" in result.findings


@pytest.mark.unit
def test_config_from_env_maps_tradingagents_env_names():
    config = config_from_env({
        "TRADINGAGENTS_LLM_PROVIDER": "google",
        "TRADINGAGENTS_QUICK_THINK_LLM": "gemini-3.1-flash-lite",
        "TRADINGAGENTS_DEEP_THINK_LLM": "gemini-3.1-flash-lite",
        "TRADINGAGENTS_GOOGLE_THINKING_LEVEL": "minimal",
        "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "0",
        "TRADINGAGENTS_MAX_RISK_ROUNDS": "0",
        "TRADINGAGENTS_PARALLEL_ANALYSTS": "false",
        "TRADINGAGENTS_CHECKPOINT_ENABLED": "true",
    })

    assert config["llm_provider"] == "google"
    assert config["max_debate_rounds"] == 0
    assert config["max_risk_discuss_rounds"] == 0
    assert config["parallel_analysts"] is False
    assert config["checkpoint_enabled"] is True


@pytest.mark.unit
def test_merge_env_file_values_override_shell_values(tmp_path):
    env_file = tmp_path / ".env.lowcost"
    env_file.write_text("TRADINGAGENTS_LLM_PROVIDER=ollama\n", encoding="utf-8")

    merged = merge_env({"TRADINGAGENTS_LLM_PROVIDER": "google"}, env_file)

    assert merged["TRADINGAGENTS_LLM_PROVIDER"] == "ollama"
