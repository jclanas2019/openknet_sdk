"""
LangGraph node functions for OpenKNet.

Every node receives the full KNetState and returns a partial update dict.
Nodes are pure async functions — they do not mutate state in place.
"""
from __future__ import annotations

import math
from typing import Any

from loguru import logger

from ...sdk.client import OpenKNet
from .state import KNetState, RootCauseState


# ---------------------------------------------------------------------------
# Knowledge-graph nodes (no LLM)
# ---------------------------------------------------------------------------

async def rank_node(state: KNetState) -> dict[str, Any]:
    """Rank entities against current_query (or question if not yet refined)."""
    query = state.get("current_query") or state["question"]
    knet = OpenKNet(state["project"])
    resp = await knet.rank(query, limit=10)

    entities = [r.name for r in resp.results]
    confidence = _score_confidence(resp.results, state.get("snippets", []))

    logger.debug(f"[rank_node] iter={state.get('iteration', 0)} "
                 f"entities={entities[:3]} confidence={confidence:.2f}")

    return {
        "current_query": query,
        "rank_results": resp.results,
        "entities": entities,
        "confidence": confidence,
    }


async def ask_node(state: KNetState) -> dict[str, Any]:
    """Ask the question and collect supporting snippets."""
    query = state.get("current_query") or state["question"]
    knet = OpenKNet(state["project"])
    resp = await knet.ask(query, limit=5)

    confidence = _score_confidence(resp.results, resp.snippets)

    logger.debug(f"[ask_node] snippets={len(resp.snippets)} confidence={confidence:.2f}")

    return {
        "rank_results": resp.results,
        "entities": resp.entities,
        "snippets": resp.snippets,
        "confidence": confidence,
    }


async def path_node(state: KNetState) -> dict[str, Any]:
    """
    For each pair of top-2 entities, attempt to find graph paths.
    Merges new paths into existing state.paths.
    """
    entities = state.get("entities", [])
    if len(entities) < 2:
        return {"paths": state.get("paths", [])}

    knet = OpenKNet(state["project"])
    all_paths = list(state.get("paths", []))
    pairs_tried = set()

    for src in entities[:3]:
        for tgt in entities[:3]:
            if src == tgt or (src, tgt) in pairs_tried:
                continue
            pairs_tried.add((src, tgt))
            resp = await knet.path(src, tgt, max_depth=4)
            if resp.found:
                all_paths.extend(resp.paths)

    # Deduplicate by node sequence
    seen: set[tuple] = set()
    unique_paths = []
    for p in all_paths:
        key = tuple(p.nodes)
        if key not in seen:
            seen.add(key)
            unique_paths.append(p)

    unique_paths.sort(key=lambda p: (-p.confidence, p.length))
    logger.debug(f"[path_node] found {len(unique_paths)} paths")
    return {"paths": unique_paths[:10]}


# ---------------------------------------------------------------------------
# LLM nodes (require a `llm` parameter injected at graph build time)
# ---------------------------------------------------------------------------

def make_reflect_node(llm):
    """
    Factory: returns a reflect_node bound to *llm*.

    The node asks the LLM to evaluate current results and produce a
    refined query that is more likely to surface the missing context.
    """
    async def reflect_node(state: KNetState) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        question = state["question"]
        entities = state.get("entities", [])
        snippets = state.get("snippets", [])
        iteration = state.get("iteration", 0)
        notes = state.get("reflection_notes", [])

        evidence_block = "\n---\n".join(snippets[:3]) if snippets else "(none)"
        prior_notes = "\n".join(f"- {n}" for n in notes) if notes else "(first iteration)"

        prompt = f"""You are refining a knowledge graph search.

Original question: {question}
Iteration: {iteration + 1}

Entities found so far: {", ".join(entities) or "none"}
Supporting evidence:
{evidence_block}

Previous reflection notes:
{prior_notes}

The current results are INSUFFICIENT. Analyse what context is missing and write a
single improved search query (under 15 words) that would surface the missing entities
or relationships. Return ONLY the query string, no explanation."""

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        refined = response.content.strip().strip('"')
        note = f"iter {iteration + 1}: refined to '{refined}'"

        logger.debug(f"[reflect_node] {note}")

        return {
            "current_query": refined,
            "iteration": iteration + 1,
            "reflection_notes": [note],   # reducer appends
        }

    return reflect_node


def make_synthesize_node(llm):
    """
    Factory: returns a synthesize_node bound to *llm*.

    Assembles all gathered evidence into a final structured answer.
    """
    async def synthesize_node(state: KNetState) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        question = state["question"]
        entities = state.get("entities", [])
        snippets = state.get("snippets", [])
        paths = state.get("paths", [])
        notes = state.get("reflection_notes", [])

        paths_block = "\n".join(
            f"  {' → '.join(p.nodes)} (via {', '.join(p.relations)})"
            for p in paths[:5]
        ) or "(no paths found)"

        evidence_block = "\n---\n".join(snippets[:5]) or "(no snippets)"

        prompt = f"""You are a knowledge analyst. Answer the question below using only
the evidence provided. Be concise and structured.

Question: {question}

Related entities: {", ".join(entities) or "none"}

Graph paths:
{paths_block}

Supporting evidence:
{evidence_block}

Reflection notes: {"; ".join(notes) or "none"}

Provide:
1. A direct answer to the question
2. The key entities involved and their roles
3. Any caveats or gaps in the available evidence"""

        response = await llm.ainvoke([HumanMessage(content=prompt)])

        logger.debug("[synthesize_node] answer generated")
        return {
            "final_answer": response.content,
            "reasoning": f"Used {len(snippets)} snippets, "
                         f"{len(paths)} paths, "
                         f"{state.get('iteration', 0)} reflection iterations.",
        }

    return synthesize_node


def make_root_cause_node(llm):
    """
    Factory: returns a root_cause_node for incident triage graphs.
    Specialised prompt for root-cause / impact / remediation output.
    """
    async def root_cause_node(state: RootCauseState) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        symptom = state.get("symptom") or state.get("question", "")
        affected = state.get("affected_product", "unknown")
        entities = state.get("entities", [])
        snippets = state.get("snippets", [])
        paths = state.get("paths", [])

        paths_block = "\n".join(
            f"  {' → '.join(p.nodes)} (via {', '.join(p.relations)}, confidence {p.confidence:.0%})"
            for p in paths[:5]
        ) or "(no paths)"
        evidence_block = "\n---\n".join(snippets[:5]) or "(no evidence)"

        prompt = f"""You are a site-reliability engineer performing root-cause analysis.

Symptom: {symptom}
Affected product: {affected}
Entities in knowledge graph: {", ".join(entities)}

Graph paths (component dependency chains):
{paths_block}

Evidence from runbooks / incident reports:
{evidence_block}

Return a JSON object with these keys:
- root_cause: the most likely root-cause component or error
- impact_summary: which products/customers are affected and how
- remediation: recommended immediate actions
- confidence: a float 0-1 for your confidence in this analysis

Return ONLY the JSON, no markdown fences."""

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        import json

        try:
            parsed = json.loads(response.content)
        except Exception:
            parsed = {
                "root_cause": entities[0] if entities else "unknown",
                "impact_summary": response.content[:300],
                "remediation": "Manual investigation required.",
                "confidence": 0.3,
            }

        logger.debug(f"[root_cause_node] root_cause={parsed.get('root_cause')}")
        return {
            "root_cause_entity": parsed.get("root_cause"),
            "impact_summary": parsed.get("impact_summary"),
            "remediation": parsed.get("remediation"),
            "final_answer": (
                f"Root cause: {parsed.get('root_cause')}\n"
                f"Impact: {parsed.get('impact_summary')}\n"
                f"Remediation: {parsed.get('remediation')}"
            ),
            "confidence": float(parsed.get("confidence", 0.5)),
        }

    return root_cause_node


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def should_reflect(state: KNetState) -> str:
    """
    Conditional edge: decide whether to reflect or synthesize.
    Returns 'reflect' or 'synthesize'.
    """
    confidence = state.get("confidence", 0.0)
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 3)

    if iteration >= max_iter:
        logger.debug(f"[router] max iterations ({max_iter}) reached → synthesize")
        return "synthesize"

    threshold = 0.55
    if confidence >= threshold:
        logger.debug(f"[router] confidence {confidence:.2f} ≥ {threshold} → synthesize")
        return "synthesize"

    logger.debug(f"[router] confidence {confidence:.2f} < {threshold} → reflect")
    return "reflect"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_confidence(results: list, snippets: list) -> float:
    """
    Heuristic confidence from rank results and snippets.
    Combines: top-score magnitude, entity-type diversity, snippet presence.
    """
    if not results:
        return 0.0

    scores = [r.score for r in results]
    top = scores[0]
    score_signal = min(top / 5.0, 1.0)

    types = {r.type for r in results[:5]}
    diversity = min(len(types) / 3.0, 1.0)

    snippet_signal = 1.0 if snippets else 0.3

    return round(score_signal * 0.5 + diversity * 0.3 + snippet_signal * 0.2, 3)
