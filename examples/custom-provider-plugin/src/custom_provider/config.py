"""Configuration schema for ClaudeProvider — validated at construction time, per the plugin
development guideline that every provider declares and validates its own config
(docs/architecture/09-engineering-standards.md §11).

The `pricing` table below is illustrative example data, not a live pricing feed — verify
against https://www.anthropic.com/pricing before relying on estimate_cost() for anything real.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    input_cost_per_million_tokens: float
    output_cost_per_million_tokens: float


def _default_pricing() -> dict[str, ModelPricing]:
    return {
        "opus": ModelPricing(input_cost_per_million_tokens=15.0, output_cost_per_million_tokens=75.0),
        "sonnet": ModelPricing(input_cost_per_million_tokens=3.0, output_cost_per_million_tokens=15.0),
        "haiku": ModelPricing(input_cost_per_million_tokens=0.8, output_cost_per_million_tokens=4.0),
    }


class ClaudeProviderConfig(BaseModel):
    default_max_tokens: int = Field(default=1024, gt=0)
    pricing: dict[str, ModelPricing] = Field(default_factory=_default_pricing)
