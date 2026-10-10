"""Experiment registry and configuration matrix for Phase 8.1 experiments."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from shopassist.llm.config import DEFAULT_GEMINI_MODEL


class ExperimentConfig(BaseModel):
    """Specification for a controlled query-understanding experiment."""

    id: str = Field(description="Unique experiment ID (e.g. 'E0', 'E1-A', 'E2-B').")
    name: str = Field(description="Descriptive human-readable experiment name.")
    variable_changed: str = Field(description="Independent variable being tested.")
    purpose: str = Field(description="Primary engineering or scientific purpose.")
    hypothesis: str = Field(description="Expected outcome or testable hypothesis.")
    prompt_variant: str = Field(default="E1-A", description="Prompt template identifier ('E1-A', 'E1-B', 'E1-C', 'E5-B').")
    schema_version: Literal["v1.0.0", "v2.0.0"] = Field(default="v1.0.0", description="Target Pydantic schema version.")
    temperature: float = Field(default=0.0, description="LLM sampling temperature.")
    apply_rules: bool = Field(default=False, description="Whether to apply deterministic rule-based post-processing.")
    multi_stage: bool = Field(default=False, description="Whether multi-stage extraction is enabled.")
    model: str = Field(default=DEFAULT_GEMINI_MODEL, description="Gemini model identifier.")
    dataset_split: Literal["baseline_50", "dev_15", "heldout_20"] = Field(
        default="dev_15",
        description="Dataset partition to evaluate on.",
    )


class ExperimentRegistry:
    """Central registry containing all Phase 8.1 experiment definitions."""

    EXPERIMENTS: dict[str, ExperimentConfig] = {
        "E0": ExperimentConfig(
            id="E0",
            name="Baseline Audit & Ground-Truth Verification",
            variable_changed="None (Control audit)",
            purpose="Independently verify Phase 8 reported metrics and investigate discrepancies.",
            hypothesis="Soft preferences F1 (66.4%) and exact match (98%) discrepancies stem from narrow exact-match scope and ground-truth labeling quirks.",
            prompt_variant="E1-A",
            schema_version="v1.0.0",
            temperature=0.0,
            apply_rules=False,
            dataset_split="baseline_50",
        ),
        "E1-A": ExperimentConfig(
            id="E1-A",
            name="Existing Prompt (Control)",
            variable_changed="None",
            purpose="Establish exact experimental baseline on development split.",
            hypothesis="Baseline prompt confuses product nouns (e.g. 'running shoes') with qualitative soft preferences.",
            prompt_variant="E1-A",
            schema_version="v1.0.0",
            temperature=0.0,
            apply_rules=False,
            dataset_split="dev_15",
        ),
        "E1-B": ExperimentConfig(
            id="E1-B",
            name="Explicit Extraction Rules Prompt",
            variable_changed="Prompt instructions",
            purpose="Evaluate impact of rigorous definitions separating product type, preferences, hard constraints, and exclusions.",
            hypothesis="Explicit definitions reduce false positive soft preferences without sacrificing hard constraint recall.",
            prompt_variant="E1-B",
            schema_version="v1.0.0",
            temperature=0.0,
            apply_rules=False,
            dataset_split="dev_15",
        ),
        "E1-C": ExperimentConfig(
            id="E1-C",
            name="Few-Shot Exemplars Prompt",
            variable_changed="Prompt exemplars",
            purpose="Improve few-shot in-context learning on edge cases (corrections, foreign currency, exclusions).",
            hypothesis="Targeted few-shot examples improve boundary accuracy and negation handling with moderate token overhead.",
            prompt_variant="E1-C",
            schema_version="v1.0.0",
            temperature=0.0,
            apply_rules=False,
            dataset_split="dev_15",
        ),
        "E2-A": ExperimentConfig(
            id="E2-A",
            name="Temperature 0.0 (Greedy Sampling)",
            variable_changed="Temperature = 0.0",
            purpose="Evaluate deterministic greedy decoding for information extraction.",
            hypothesis="Temperature 0.0 produces highest consistency and lowest hallucination rate.",
            prompt_variant="E1-B",
            schema_version="v1.0.0",
            temperature=0.0,
            apply_rules=False,
            dataset_split="dev_15",
        ),
        "E2-B": ExperimentConfig(
            id="E2-B",
            name="Temperature 0.5 (Intermediate Sampling)",
            variable_changed="Temperature = 0.5",
            purpose="Test moderate sampling randomness on extraction quality.",
            hypothesis="Temperature 0.5 may introduce minor output variance without quality gains for structured extraction.",
            prompt_variant="E1-B",
            schema_version="v1.0.0",
            temperature=0.5,
            apply_rules=False,
            dataset_split="dev_15",
        ),
        "E2-C": ExperimentConfig(
            id="E2-C",
            name="Temperature 1.0 (Default Sampling)",
            variable_changed="Temperature = 1.0",
            purpose="Compare default high-entropy generation against greedy extraction.",
            hypothesis="Temperature 1.0 degrades schema consistency and increases constraint hallucinations.",
            prompt_variant="E1-B",
            schema_version="v1.0.0",
            temperature=1.0,
            apply_rules=False,
            dataset_split="dev_15",
        ),
        "E3": ExperimentConfig(
            id="E3",
            name="Refined Schema v2.0.0",
            variable_changed="Output contract schema",
            purpose="Introduce explicit product_type, exclusions, and strict/inclusive price boundary booleans.",
            hypothesis="Refined schema eliminates semantic ambiguity between product nouns, exclusions, and qualitative preferences.",
            prompt_variant="E1-C",
            schema_version="v2.0.0",
            temperature=0.0,
            apply_rules=False,
            dataset_split="dev_15",
        ),
        "E4": ExperimentConfig(
            id="E4",
            name="Hybrid LLM + Deterministic Business Rules",
            variable_changed="Post-processing validation layer",
            purpose="Apply deterministic price operators, negation conflict resolution, and out-of-domain brand suppression.",
            hypothesis="Deterministic rules fix 100% of boundary and unserviceable brand errors (fixing P8-04 and P8-07) with zero API latency overhead.",
            prompt_variant="E1-C",
            schema_version="v2.0.0",
            temperature=0.0,
            apply_rules=True,
            dataset_split="dev_15",
        ),
        "E5-A": ExperimentConfig(
            id="E5-A",
            name="Single-Stage Direct Extraction (Control)",
            variable_changed="Extraction pipeline architecture",
            purpose="Control baseline for extraction stages.",
            hypothesis="Single-stage provides lowest latency and sufficient performance when prompt and rules are refined.",
            prompt_variant="E1-C",
            schema_version="v2.0.0",
            temperature=0.0,
            apply_rules=True,
            multi_stage=False,
            dataset_split="dev_15",
        ),
        "E5-B": ExperimentConfig(
            id="E5-B",
            name="Logically Staged Extraction (Single-Call CoT)",
            variable_changed="Internal reasoning structure",
            purpose="Evaluate structured 5-stage reasoning instructions within a single API request.",
            hypothesis="Logical staging improves isolation between stages without requiring multiple API calls.",
            prompt_variant="E5-B",
            schema_version="v2.0.0",
            temperature=0.0,
            apply_rules=True,
            multi_stage=False,
            dataset_split="dev_15",
        ),
    }

    @classmethod
    def get(cls, exp_id: str) -> ExperimentConfig:
        if exp_id not in cls.EXPERIMENTS:
            raise KeyError(f"Experiment '{exp_id}' not found in registry.")
        return cls.EXPERIMENTS[exp_id]

    @classmethod
    def list_all(cls) -> list[ExperimentConfig]:
        return list(cls.EXPERIMENTS.values())
