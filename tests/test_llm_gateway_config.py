import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from shopassist.llm_gateway.config import GatewayConfigurationError, GatewaySettings, ROOT, load_gateway_config


@pytest.fixture
def settings(monkeypatch):
    for name in ("LLM_GATEWAY_ENABLED", "LLM_GATEWAY_CONFIG_PATH", "GEMINI_MODEL", "PHASE12_LLM_MODEL", "PHASE12_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    return GatewaySettings(_env_file=None, enabled=True)


def test_default_config_and_disabled_backup(settings, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_MODEL", "wrong")
    monkeypatch.setenv("PHASE12_LLM_MODEL", "wrong")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    config = load_gateway_config(settings)
    assert config.routes["query_gemini"].model == "gemini-3.5-flash-lite"
    assert config.routes["recommendation_openrouter"].model == "baidu/ernie-5.5-flash-preview:free"
    assert not config.routes["recommendation_groq"].enabled


def test_disabled_does_not_open_yaml(tmp_path):
    settings = GatewaySettings(_env_file=None, enabled=False, config_path=tmp_path / "missing.yaml")
    assert load_gateway_config(settings) is None


def test_missing_and_malformed_yaml(settings, tmp_path):
    settings.config_path = tmp_path / "missing.yaml"
    with pytest.raises(GatewayConfigurationError):
        load_gateway_config(settings)
    settings.config_path.write_text("routes: [", encoding="utf-8")
    with pytest.raises(GatewayConfigurationError):
        load_gateway_config(settings)


@pytest.mark.parametrize("mutation", ["version", "provider", "model", "duplicate", "limit", "enabled", "extra"])
def test_invalid_config(settings, tmp_path, mutation):
    text = (ROOT / "config/llm_gateway.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if mutation == "version":
        data["version"] = 2
    elif mutation == "provider":
        data["providers"]["groq"]["kind"] = "unknown"
    elif mutation == "model":
        data["routes"]["query_gemini"]["model"] = ""
    elif mutation == "duplicate":
        text += "\nroutes: {}\n"
    elif mutation == "limit":
        data["providers"]["groq"]["limits"] = {"max_in_flight": -1}
    elif mutation == "enabled":
        data["routes"]["recommendation_groq"]["enabled"] = True
    else:
        data["routes"]["query_gemini"]["api_key"] = "secret-test-value"
    path = tmp_path / "invalid.yaml"
    path.write_text(text if mutation == "duplicate" else yaml.safe_dump(data), encoding="utf-8")
    settings.config_path = path
    with pytest.raises(GatewayConfigurationError) as exc:
        load_gateway_config(settings)
    assert "secret-test-value" not in str(exc.value)


def test_dotenv_and_secret_exclusion(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_ENABLED", raising=False)
    fixture = tmp_path / "fixture.env"
    fixture.write_text("LLM_GATEWAY_ENABLED=true\nLLM_GATEWAY_MAX_ATTEMPTS_PER_ROUTE=1\nLLM_GATEWAY_LOG_PROMPTS=false\nLLM_GATEWAY_LOG_RESPONSES=false\nGEMINI_API_KEY=secret-test-value\n", encoding="utf-8")
    settings = GatewaySettings(_env_file=fixture)
    assert settings.enabled
    assert load_gateway_config(settings)
    assert "secret-test-value" not in repr(settings)
    assert "secret-test-value" not in settings.model_dump_json()


@pytest.mark.parametrize("kwargs", [{"max_attempts_per_task": 3}, {"default_cooldown_seconds": float("nan")}, {"log_prompts": True}])
def test_invalid_controls(kwargs):
    with pytest.raises(ValidationError):
        GatewaySettings(_env_file=None, **kwargs)


@pytest.fixture
def synthetic_evidence_config(settings, tmp_path):
    """Synthetic evidence exercises validation only and is not live verification."""
    data = yaml.safe_load((ROOT / "config/llm_gateway.yaml").read_text(encoding="utf-8"))
    route = data["routes"]["query_gemini"]
    route["enabled"] = True
    route["approval"] = {"status": "approved", "evidence_ref": "evidence.yaml"}
    route["cost"] = {"class": "free", "evidence_ref": "evidence.yaml"}
    evidence = {
        "route_id": "query_gemini",
        "task": "query_understanding",
        "provider": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com",
        "model": "gemini-3.5-flash-lite",
        "schema_id": "phase8.query.v1",
        "structured_mode": "gemini_schema",
        "status": "valid",
        "approval": "approved",
        "cost_class": "free",
        "artifact_ref": "synthetic-artifact.txt",
        "artifact_sha256": hashlib.sha256(b"synthetic fixture only").hexdigest(),
        "valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    (tmp_path / "synthetic-artifact.txt").write_bytes(b"synthetic fixture only")
    settings.config_path = tmp_path / "gateway.yaml"
    return settings, data, evidence, tmp_path


def write_evidence_fixture(settings, data, evidence, directory):
    settings.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    if evidence is not None:
        (directory / "evidence.yaml").write_text(yaml.safe_dump(evidence), encoding="utf-8")


def test_approved_route_with_matching_synthetic_evidence(synthetic_evidence_config):
    settings, data, evidence, directory = synthetic_evidence_config
    write_evidence_fixture(settings, data, evidence, directory)
    config = load_gateway_config(settings)
    assert config.routes["query_gemini"].enabled
    assert config.routes["query_gemini"].approval.status == "approved"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("route_id", "another_route"),
        ("provider", "another_provider"),
        ("endpoint", "https://other.invalid"),
        ("model", "another-model"),
        ("task", "llm_judge"),
        ("schema_id", "phase14.judge.v1"),
        ("structured_mode", "json_schema"),
        ("status", "revoked"),
        ("approval", "rejected"),
        ("cost_class", "paid"),
        ("valid_until", "2020-01-01T00:00:00Z"),
    ],
)
def test_evidence_mismatch_rejected(synthetic_evidence_config, field, value):
    settings, data, evidence, directory = synthetic_evidence_config
    evidence[field] = value
    write_evidence_fixture(settings, data, evidence, directory)
    with pytest.raises(GatewayConfigurationError):
        load_gateway_config(settings)


def test_changed_model_invalidates_evidence(synthetic_evidence_config):
    settings, data, evidence, directory = synthetic_evidence_config
    data["routes"]["query_gemini"]["model"] = "changed-model"
    write_evidence_fixture(settings, data, evidence, directory)
    with pytest.raises(GatewayConfigurationError):
        load_gateway_config(settings)


def test_changed_evidence_artifact_is_rejected(synthetic_evidence_config):
    settings, data, evidence, directory = synthetic_evidence_config
    write_evidence_fixture(settings, data, evidence, directory)
    (directory / "synthetic-artifact.txt").write_bytes(b"changed")
    with pytest.raises(GatewayConfigurationError):
        load_gateway_config(settings)


@pytest.mark.parametrize("reference", [None, "unknown.yaml", "../outside.yaml"])
def test_missing_or_unknown_evidence(synthetic_evidence_config, reference):
    settings, data, evidence, directory = synthetic_evidence_config
    data["routes"]["query_gemini"]["approval"]["evidence_ref"] = reference
    data["routes"]["query_gemini"]["cost"]["evidence_ref"] = reference
    write_evidence_fixture(settings, data, evidence, directory)
    with pytest.raises(GatewayConfigurationError):
        load_gateway_config(settings)


def test_disabled_pending_routes_load_without_evidence(settings, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-secret")
    monkeypatch.setenv("GEMINI_MODEL", "legacy-override")
    config = load_gateway_config(settings)
    assert all(not route.enabled and route.approval.status == "pending" for route in config.routes.values())
    assert config.routes["query_gemini"].model == "gemini-3.5-flash-lite"


def test_credential_is_not_exposed_by_evidence_error(synthetic_evidence_config, monkeypatch):
    settings, data, evidence, directory = synthetic_evidence_config
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-secret")
    evidence["model"] = "synthetic-secret"
    write_evidence_fixture(settings, data, evidence, directory)
    with pytest.raises(GatewayConfigurationError) as error:
        load_gateway_config(settings)
    assert "synthetic-secret" not in str(error.value)
