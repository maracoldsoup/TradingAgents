"""Low-cost configuration checks for staged TradingAgents pilots."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOW_COST_PROVIDERS = {"ollama", "openai_compatible"}
KEYLESS_PROVIDERS = {"ollama"}
LOCAL_BACKEND_HINTS = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal")
LOW_COST_MODEL_HINTS = (
    "flash-lite",
    "flash",
    "mini",
    "small",
    "nano",
    "haiku",
    "qwen",
    "llama",
    "mistral",
    "gemma",
    "phi",
)
EXPENSIVE_MODEL_HINTS = (
    "pro",
    "opus",
    "sonnet",
    "gpt-5.5",
    "gpt-5",
    "gpt-4",
    "o3",
    "o4",
    "reasoning",
)


@dataclass(frozen=True)
class CostGuardResult:
    status: str
    score: int
    findings: list[str]
    recommendations: list[str]
    config: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "warn"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "passed": self.passed,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "config": self.config,
        }


def _bool_from_env(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_from_env(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def config_from_env(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    return {
        "local_only": _bool_from_env(env.get("TRADINGAGENTS_LOCAL_ONLY"), False),
        "llm_provider": env.get("TRADINGAGENTS_LLM_PROVIDER", "openai").lower(),
        "quick_think_llm": env.get("TRADINGAGENTS_QUICK_THINK_LLM", ""),
        "deep_think_llm": env.get("TRADINGAGENTS_DEEP_THINK_LLM", ""),
        "backend_url": env.get("TRADINGAGENTS_LLM_BACKEND_URL") or env.get("OLLAMA_BASE_URL", ""),
        "google_thinking_level": env.get("TRADINGAGENTS_GOOGLE_THINKING_LEVEL", ""),
        "openai_reasoning_effort": env.get("TRADINGAGENTS_OPENAI_REASONING_EFFORT", ""),
        "anthropic_effort": env.get("TRADINGAGENTS_ANTHROPIC_EFFORT", ""),
        "max_debate_rounds": _int_from_env(env.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS"), 1),
        "max_risk_discuss_rounds": _int_from_env(env.get("TRADINGAGENTS_MAX_RISK_ROUNDS"), 1),
        "parallel_analysts": _bool_from_env(env.get("TRADINGAGENTS_PARALLEL_ANALYSTS"), True),
        "checkpoint_enabled": _bool_from_env(env.get("TRADINGAGENTS_CHECKPOINT_ENABLED"), False),
    }


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merge_env(env: Mapping[str, str], env_file: Path | None = None) -> dict[str, str]:
    merged = dict(env)
    if env_file:
        merged.update(load_env_file(env_file))
    return merged


def _has_hint(value: Any, hints: tuple[str, ...]) -> bool:
    lowered = str(value or "").lower()
    for hint in hints:
        if hint in {"mini", "small", "nano", "pro", "o3", "o4"}:
            pattern = rf"(?:^|[-_:./]){re.escape(hint)}(?:$|[-_:./])"
            if re.search(pattern, lowered):
                return True
        elif hint in lowered:
            return True
    return False


def _is_local_backend(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(hint in lowered for hint in LOCAL_BACKEND_HINTS)


def assess_low_cost_config(config: Mapping[str, Any]) -> CostGuardResult:
    local_only = bool(config.get("local_only", False))
    provider = str(config.get("llm_provider") or "").lower()
    quick_model = str(config.get("quick_think_llm") or "")
    deep_model = str(config.get("deep_think_llm") or "")
    backend_url = str(config.get("backend_url") or "")
    max_debate = int(config.get("max_debate_rounds") or 0)
    max_risk = int(config.get("max_risk_discuss_rounds") or 0)
    parallel = bool(config.get("parallel_analysts", False))
    checkpoint = bool(config.get("checkpoint_enabled", False))
    google_thinking = str(config.get("google_thinking_level") or "").lower()
    openai_effort = str(config.get("openai_reasoning_effort") or "").lower()
    anthropic_effort = str(config.get("anthropic_effort") or "").lower()

    score = 100
    findings: list[str] = []
    recommendations: list[str] = []

    provider_is_local = provider in KEYLESS_PROVIDERS or (
        provider in LOW_COST_PROVIDERS and _is_local_backend(backend_url)
    )

    if local_only and not provider_is_local:
        score -= 45
        findings.append(f"local_only:{provider or 'missing'}:external_provider_blocked")
        recommendations.append("Use ollama or a localhost openai_compatible backend for local-only pilots.")

    if provider in KEYLESS_PROVIDERS:
        findings.append(f"provider:{provider}:keyless_local")
    elif provider in LOW_COST_PROVIDERS and _is_local_backend(backend_url):
        findings.append(f"provider:{provider}:local_backend")
    elif provider == "google" and (
        _has_hint(quick_model, LOW_COST_MODEL_HINTS)
        and _has_hint(deep_model, LOW_COST_MODEL_HINTS)
    ):
        findings.append("provider:google:low_cost_models")
    else:
        score -= 25
        findings.append(f"provider:{provider or 'missing'}:paid_or_unknown")
        recommendations.append("Use ollama or a localhost openai_compatible backend for free pilots.")

    for label, model in (("quick", quick_model), ("deep", deep_model)):
        if not model:
            score -= 10
            findings.append(f"model:{label}:missing")
            recommendations.append(f"Set TRADINGAGENTS_{label.upper()}_THINK_LLM for reproducible pilot cost.")
            continue
        if _has_hint(model, EXPENSIVE_MODEL_HINTS) and not _has_hint(model, LOW_COST_MODEL_HINTS):
            penalty = 30 if label == "deep" else 15
            score -= penalty
            findings.append(f"model:{label}:expensive:{model}")
            recommendations.append(f"Replace {label} model with a local small model for pilots.")
        elif _has_hint(model, LOW_COST_MODEL_HINTS):
            findings.append(f"model:{label}:low_cost:{model}")
        else:
            score -= 8
            findings.append(f"model:{label}:unknown_cost:{model}")

    if max_debate > 0:
        score -= min(max_debate * 10, 30)
        findings.append(f"debate_rounds:{max_debate}:adds_llm_calls")
        recommendations.append("Set TRADINGAGENTS_MAX_DEBATE_ROUNDS=0 for screening and content-pilot runs.")
    else:
        findings.append("debate_rounds:0")

    if max_risk > 0:
        score -= min(max_risk * 10, 30)
        findings.append(f"risk_rounds:{max_risk}:adds_llm_calls")
        recommendations.append("Set TRADINGAGENTS_MAX_RISK_ROUNDS=0 for screening and content-pilot runs.")
    else:
        findings.append("risk_rounds:0")

    if parallel:
        score -= 10
        findings.append("parallel_analysts:true:burst_rpm_risk")
        recommendations.append("Set TRADINGAGENTS_PARALLEL_ANALYSTS=false on free or rate-limited tiers.")
    else:
        findings.append("parallel_analysts:false")

    if checkpoint:
        findings.append("checkpoint_enabled:true")
    else:
        score -= 5
        findings.append("checkpoint_enabled:false:rerun_risk")
        recommendations.append("Set TRADINGAGENTS_CHECKPOINT_ENABLED=true to avoid paying again after interruptions.")

    if provider == "google" and google_thinking not in {"", "minimal", "low"}:
        score -= 10
        findings.append(f"google_thinking:{google_thinking}:may_add_cost")
        recommendations.append("Use TRADINGAGENTS_GOOGLE_THINKING_LEVEL=minimal during pilots.")
    if provider == "openai" and openai_effort not in {"", "low"}:
        score -= 10
        findings.append(f"openai_reasoning_effort:{openai_effort}:may_add_cost")
        recommendations.append("Use TRADINGAGENTS_OPENAI_REASONING_EFFORT=low during pilots.")
    if provider == "anthropic" and anthropic_effort not in {"", "low"}:
        score -= 10
        findings.append(f"anthropic_effort:{anthropic_effort}:may_add_cost")
        recommendations.append("Use TRADINGAGENTS_ANTHROPIC_EFFORT=low during pilots.")

    score = max(0, min(100, score))
    if score >= 80:
        status = "pass"
    elif score >= 60:
        status = "warn"
    else:
        status = "fail"

    return CostGuardResult(
        status=status,
        score=score,
        findings=findings,
        recommendations=sorted(set(recommendations)),
        config={
            "local_only": local_only,
            "llm_provider": provider,
            "quick_think_llm": quick_model,
            "deep_think_llm": deep_model,
            "backend_url": backend_url,
            "google_thinking_level": google_thinking,
            "openai_reasoning_effort": openai_effort,
            "anthropic_effort": anthropic_effort,
            "max_debate_rounds": max_debate,
            "max_risk_discuss_rounds": max_risk,
            "parallel_analysts": parallel,
            "checkpoint_enabled": checkpoint,
        },
    )
