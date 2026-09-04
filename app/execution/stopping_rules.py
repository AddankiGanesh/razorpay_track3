"""Stopping rules — re-exports the canonical implementation."""

from app.execution.stopping import ACTION_MAX_NUDGES, StoppingDecision, evaluate_stopping_rules

__all__ = ["ACTION_MAX_NUDGES", "StoppingDecision", "evaluate_stopping_rules"]
