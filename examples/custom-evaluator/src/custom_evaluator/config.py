"""Configuration schema for UnitTestEvaluator — validated at construction time, per the
plugin development guideline that every evaluator declares and validates its own config
(docs/architecture/09-engineering-standards.md §11)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UnitTestEvaluatorConfig(BaseModel):
    working_directory: str = "."
    test_path: str = "tests"
    pytest_args: list[str] = Field(default_factory=list)
    min_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    timeout_seconds: float = Field(default=120.0, gt=0)
