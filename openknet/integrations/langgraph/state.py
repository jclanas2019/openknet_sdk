from __future__ import annotations

from typing import Annotated
from typing_extensions import TypedDict

from ...sdk.models import EntityResult, PathResult


def _append(existing: list, new: list) -> list:
    """Reducer: append new items to existing list."""
    return (existing or []) + (new or [])


# ---------------------------------------------------------------------------
# Shared graph state
# ---------------------------------------------------------------------------

class KNetState(TypedDict, total=False):
    # ---- Input ----
    project: str
    question: str                          # original user question

    # ---- Working state ----
    current_query: str                     # may be refined by the reflect node
    entities: list[str]                    # entity names from latest rank
    rank_results: list[EntityResult]       # full EntityResult objects
    snippets: list[str]                    # supporting text chunks
    paths: list[PathResult]               # graph paths found

    # ---- Reflection ----
    iteration: int                         # current reflection loop count
    max_iterations: int                    # cap on reflection cycles (default 3)
    reflection_notes: Annotated[list[str], _append]  # one note per iteration
    confidence: float                      # 0-1 estimate of answer quality

    # ---- Output ----
    final_answer: str | None
    reasoning: str | None                  # LLM chain-of-thought (optional)


# ---------------------------------------------------------------------------
# Specialized state for root-cause analysis
# ---------------------------------------------------------------------------

class RootCauseState(KNetState, total=False):
    symptom: str                           # e.g. "error 503"
    affected_product: str | None           # e.g. "Portal X"
    root_cause_entity: str | None          # resolved root cause entity name
    impact_summary: str | None
    remediation: str | None
