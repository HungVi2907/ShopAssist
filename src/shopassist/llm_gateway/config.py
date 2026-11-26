"""Load and validate gateway configuration without contacting providers."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from shopassist.llm_gateway.schema_ids import ALL_SCHEMA_IDS, EXPERIMENTAL_SCHEMA_IDS, PRODUCTION_SCHEMA_IDS, TASK_SCHEMA_IDS

ROOT = Path(__file__).resolve().parents[3]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
Name = Annotated[str, Field(min_length=1, pattern=r"^[a-zA-Z0-9_.:/-]+$")]
SCHEMAS = dict(PRODUCTION_SCHEMA_IDS)
PROVIDERS = {
    "gemini": ({"GEMINI_API_KEY", "GEMINI_API_KEY_2"}, "generativelanguage.googleapis.com", ""),
    "openrouter": ({"OPENROUTER_API_KEY"}, "openrouter.ai", "/api/v1"),
    "groq": ({"GROQ_API_KEY"}, "api.groq.com", "/openai/v1"),
}


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_GATEWAY_", env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True)
    enabled: bool = False
    config_path: Path = Path("config/llm_gateway.yaml")
    auto_failover: bool = True
    allow_paid_models: bool = False
    max_attempts_per_task: int = Field(default=2, ge=1, le=2)
    max_attempts_per_route: int = Field(default=1, ge=1, le=1)
    attempt_timeout_seconds: Positive = 25
    query_deadline_seconds: Positive = 30
    recommendation_deadline_seconds: Positive = 45
    judge_deadline_seconds: Positive = 30
    default_cooldown_seconds: Annotated[float, Field(gt=0, le=900, allow_inf_nan=False)] = 60
    telemetry_enabled: bool = True
    telemetry_dir: Path = Path("data/interim/llm_gateway")
    log_prompts: bool = False
    log_responses: bool = False

    @model_validator(mode="after")
    def forbid_content_logging(self):
        if self.log_prompts or self.log_responses:
            raise ValueError("Content logging is disabled")
        return self


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Limits(Model):
    requests_per_minute: PositiveInt | None = None
    tokens_per_day: PositiveInt | None = None
    max_in_flight: PositiveInt | None = None
    cost_per_day_usd: Positive | None = None


class Provider(Model):
    kind: Literal["gemini", "openrouter", "groq"]
    credential_env: str
    endpoint: str
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def check_endpoint(self):
        credentials, host, path = PROVIDERS[self.kind]
        url = urlsplit(self.endpoint)
        if self.credential_env not in credentials or url.scheme != "https" or url.hostname != host or url.path.rstrip("/") != path or url.username or url.password or url.query or url.fragment or url.port not in (None, 443):
            raise ValueError("Invalid provider endpoint or credential reference")
        return self


class Approval(Model):
    status: Literal["pending", "approved"]
    evidence_ref: Name | None = None


class Cost(Model):
    classification: Literal["unknown", "free", "paid"] = Field(alias="class")
    evidence_ref: Name | None = None
    input_per_million_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    output_per_million_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class Options(Model):
    max_output_tokens: PositiveInt
    context_limit_tokens: PositiveInt | None = None
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] | None = None
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    reported_model_aliases: list[Name] = Field(default_factory=list)


class Route(Model):
    provider: Name
    model: Name
    structured_mode: Literal["gemini_schema", "json_schema", "json_object"]
    schema_ids: list[Name] = Field(min_length=1)
    enabled: bool
    approval: Approval
    cost: Cost
    options: Options

    @model_validator(mode="after")
    def check_approval(self):
        if self.enabled and (self.approval.status != "approved" or not self.approval.evidence_ref or self.cost.classification == "unknown" or not self.cost.evidence_ref):
            raise ValueError("Enabled route lacks approval or cost evidence")
        if self.enabled and self.cost.classification == "paid" and (self.cost.input_per_million_usd is None or self.cost.output_per_million_usd is None):
            raise ValueError("Paid route requires pricing")
        return self


class Profile(Model):
    schema_id: Name
    route_ids: list[Name] = Field(min_length=1)
    allow_paid: bool = False


class Task(Model):
    profiles: dict[Name, Profile]


class RouteEvidence(Model):
    """Verified operator-maintained evidence record for one route and task."""

    route_id: Name
    task: Literal["query_understanding", "recommendation_generation", "llm_judge"]
    provider: Name
    endpoint: str
    model: Name
    schema_id: Name
    structured_mode: Literal["gemini_schema", "json_schema", "json_object"]
    status: Literal["valid", "rejected", "revoked"]
    approval: Literal["approved", "rejected"]
    cost_class: Literal["free", "paid"]
    input_per_million_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    output_per_million_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    artifact_ref: Name
    artifact_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    valid_until: datetime

    @field_validator("valid_until", mode="before")
    @classmethod
    def parse_valid_until(cls, value):
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def check_validity(self):
        if self.valid_until.tzinfo is None or self.valid_until <= datetime.now(timezone.utc):
            raise ValueError("Route evidence is expired or lacks a timezone")
        return self


class RoutingConfig(Model):
    _evidence_expiry: dict[str, datetime] = PrivateAttr(default_factory=dict)
    version: Literal[1]
    providers: dict[Name, Provider]
    routes: dict[Name, Route]
    tasks: dict[Literal["query_understanding", "recommendation_generation", "llm_judge"], Task]

    @model_validator(mode="after")
    def check_references(self, info: ValidationInfo):
        if set(self.tasks) != set(SCHEMAS):
            raise ValueError("All task definitions are required")
        for route in self.routes.values():
            if route.provider not in self.providers:
                raise ValueError("Unknown provider reference")
            kind = self.providers[route.provider].kind
            if (kind == "gemini") != (route.structured_mode == "gemini_schema"):
                raise ValueError("Incompatible structured mode")
            if kind != "groq" and route.options.reasoning_effort is not None:
                raise ValueError("Unsupported reasoning option")
            if not set(route.schema_ids) <= ALL_SCHEMA_IDS:
                raise ValueError("Unknown schema")
            if route.enabled and route.cost.classification == "paid" and self.providers[route.provider].limits.cost_per_day_usd is None:
                raise ValueError("Paid route requires cost limit")
        for task_name, task in self.tasks.items():
            if "default" not in task.profiles:
                raise ValueError("Missing default profile")
            for profile in task.profiles.values():
                if profile.schema_id not in TASK_SCHEMA_IDS[task_name] or len(set(profile.route_ids)) != len(profile.route_ids):
                    raise ValueError("Invalid task schema or duplicate route")
                identities = set()
                for route_id in profile.route_ids:
                    if route_id not in self.routes:
                        raise ValueError("Unknown route reference")
                    route = self.routes[route_id]
                    if profile.schema_id not in route.schema_ids:
                        raise ValueError("Incompatible route schema")
                    identity = (route.provider, route.model)
                    if identity in identities:
                        raise ValueError("Duplicate provider and model")
                    identities.add(identity)
        for route_id, route in self.routes.items():
            if route.approval.status != "approved":
                continue
            evidence_dir = (info.context or {}).get("evidence_dir")
            if evidence_dir is None:
                raise ValueError("Approved route requires verified evidence")
            references = {route.approval.evidence_ref, route.cost.evidence_ref}
            if None in references:
                raise ValueError("Approval and cost evidence are required")
            for reference in references:
                evidence_path = (evidence_dir / reference).resolve()
                if not evidence_path.is_relative_to(evidence_dir.resolve()) or not evidence_path.is_file():
                    raise ValueError("Evidence reference is unavailable")
                with evidence_path.open("r", encoding="utf-8") as stream:
                    evidence = RouteEvidence.model_validate(yaml.load(stream, Loader=UniqueSafeLoader))
                self._evidence_expiry[route_id] = min(
                    self._evidence_expiry.get(route_id, evidence.valid_until), evidence.valid_until
                )
                artifact_path = (evidence_dir / evidence.artifact_ref).resolve()
                if (
                    not artifact_path.is_relative_to(evidence_dir.resolve())
                    or not artifact_path.is_file()
                    or hashlib.sha256(artifact_path.read_bytes()).hexdigest() != evidence.artifact_sha256
                ):
                    raise ValueError("Route evidence artifact is unavailable or changed")
                bindings = [
                    (task_name, profile.schema_id)
                    for task_name, task in self.tasks.items()
                    for profile in task.profiles.values()
                    if route_id in profile.route_ids
                ]
                provider = self.providers[route.provider]
                if (
                    not bindings
                    or any(binding != (evidence.task, evidence.schema_id) for binding in bindings)
                    or evidence.route_id != route_id
                    or evidence.provider != route.provider
                    or evidence.endpoint != provider.endpoint
                    or evidence.model != route.model
                    or set(route.schema_ids) != {evidence.schema_id}
                    or evidence.structured_mode != route.structured_mode
                    or evidence.status != "valid"
                    or evidence.approval != "approved"
                    or evidence.cost_class != route.cost.classification
                    or evidence.input_per_million_usd != route.cost.input_per_million_usd
                    or evidence.output_per_million_usd != route.cost.output_per_million_usd
                ):
                    raise ValueError("Route evidence does not match configuration")
        return self


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("Invalid or duplicate configuration key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


class GatewayConfigurationError(ValueError):
    """Safe configuration error without input values."""


def load_gateway_config(settings: GatewaySettings) -> RoutingConfig | None:
    if not settings.enabled:
        return None
    path = settings.config_path
    if not path.is_absolute():
        path = ROOT / path
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.load(stream, Loader=UniqueSafeLoader)
        return RoutingConfig.model_validate(data, context={"evidence_dir": path.parent})
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError, TypeError):
        raise GatewayConfigurationError("Invalid or unavailable gateway configuration") from None
