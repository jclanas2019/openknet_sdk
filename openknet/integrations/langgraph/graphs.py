"""
Pre-built LangGraph graphs for OpenKNet.

LLM provider is resolved automatically from config (OPENKNET_LLM_PROVIDER)
or can be overridden by passing `llm=` explicitly.

    # Auto-init from OPENKNET_LLM_PROVIDER env var
    graph = ReflectiveAskGraph(project="support")

    # Explicit Anthropic
    from langchain_anthropic import ChatAnthropic
    graph = ReflectiveAskGraph(project="support", llm=ChatAnthropic(...))

    # Explicit Ollama
    graph = ReflectiveAskGraph(project="support", llm=get_llm("ollama", "mistral"))
"""
from __future__ import annotations
from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes import (
    ask_node, make_reflect_node, make_root_cause_node,
    make_synthesize_node, path_node, should_reflect,
)
from .state import KNetState, RootCauseState


def _resolve_llm(llm: Any | None) -> Any:
    """Return *llm* as-is, or auto-initialize from config if None."""
    if llm is not None:
        return llm
    from ...llm.providers import get_llm
    return get_llm()


# ---------------------------------------------------------------------------
# ReflectiveAskGraph
# ---------------------------------------------------------------------------

class ReflectiveAskGraph:
    """
    Reflection loop for open-ended knowledge-graph Q&A.

    Flow:
        START → ask → evaluate confidence
                         ├─ (≥ threshold or max iter) → synthesize → END
                         └─ (< threshold) → reflect (LLM) → ask → …

    Args:
        project:        OpenKNet project name.
        llm:            LangChain chat model. If None, auto-initialized from
                        OPENKNET_LLM_PROVIDER (defaults to Anthropic).
        max_iterations: Hard cap on reflection cycles. Default 3.

    Supported providers (set via env or pass llm= explicitly):

        # Anthropic Claude (default)
        OPENKNET_LLM_PROVIDER=anthropic
        OPENKNET_LLM_MODEL=claude-sonnet-4-20250514

        # Local Ollama (zero cost, runs on CPU)
        OPENKNET_LLM_PROVIDER=ollama
        OPENKNET_OLLAMA_MODEL=llama3.2

        # OpenAI
        OPENKNET_LLM_PROVIDER=openai
        OPENKNET_LLM_MODEL=gpt-4o-mini

    Example::

        # Ollama — no API key, runs 100% locally
        import os; os.environ["OPENKNET_LLM_PROVIDER"] = "ollama"
        graph = ReflectiveAskGraph(project="support")
        result = await graph.run("what components cause login failures?")
    """

    def __init__(
        self,
        project: str,
        llm: Any | None = None,
        max_iterations: int = 3,
    ) -> None:
        self.project = project
        self.llm = _resolve_llm(llm)
        self.max_iterations = max_iterations
        self._graph = self._build()

    def _build(self):
        g = StateGraph(KNetState)
        g.add_node("ask",        ask_node)
        g.add_node("reflect",    make_reflect_node(self.llm))
        g.add_node("synthesize", make_synthesize_node(self.llm))
        g.add_edge(START, "ask")
        g.add_conditional_edges("ask", should_reflect,
            {"reflect": "reflect", "synthesize": "synthesize"})
        g.add_edge("reflect", "ask")
        g.add_edge("synthesize", END)
        return g.compile()

    async def run(self, question: str, **kwargs) -> KNetState:
        return await self._graph.ainvoke({
            "project": self.project, "question": question,
            "current_query": question, "iteration": 0,
            "max_iterations": self.max_iterations,
            "reflection_notes": [], "paths": [], "snippets": [],
            "entities": [], "rank_results": [], "confidence": 0.0,
            "final_answer": None, "reasoning": None, **kwargs,
        })

    def run_sync(self, question: str, **kwargs) -> KNetState:
        from ...sdk.client import _run_sync
        return _run_sync(self.run(question, **kwargs))

    @property
    def graph(self):
        return self._graph


# ---------------------------------------------------------------------------
# RootCauseGraph
# ---------------------------------------------------------------------------

class RootCauseGraph:
    """
    Incident root-cause analysis using the knowledge graph + LLM reasoning.

    Flow:
        START → ask → path → root_cause (LLM) → END

    Args:
        project: OpenKNet project name.
        llm:     LangChain chat model. If None, auto-initialized from config.

    Example::

        # Use local Llama via Ollama (no API cost)
        graph = RootCauseGraph(project="support",
                               llm=get_llm("ollama", "llama3.2"))
        result = await graph.run(symptom="error 503", affected_product="Portal X")
        print(result["root_cause_entity"])
        print(result["remediation"])
    """

    def __init__(self, project: str, llm: Any | None = None) -> None:
        self.project = project
        self.llm = _resolve_llm(llm)
        self._graph = self._build()

    def _build(self):
        g = StateGraph(RootCauseState)
        g.add_node("ask",        ask_node)
        g.add_node("path",       path_node)
        g.add_node("root_cause", make_root_cause_node(self.llm))
        g.add_edge(START, "ask")
        g.add_edge("ask", "path")
        g.add_edge("path", "root_cause")
        g.add_edge("root_cause", END)
        return g.compile()

    async def run(self, symptom: str, affected_product: str | None = None) -> RootCauseState:
        return await self._graph.ainvoke({
            "project": self.project, "question": symptom,
            "symptom": symptom, "affected_product": affected_product,
            "current_query": symptom, "iteration": 0, "max_iterations": 1,
            "reflection_notes": [], "paths": [], "snippets": [],
            "entities": [], "rank_results": [], "confidence": 0.0,
            "final_answer": None, "reasoning": None,
            "root_cause_entity": None, "impact_summary": None, "remediation": None,
        })

    def run_sync(self, symptom: str, affected_product: str | None = None) -> RootCauseState:
        from ...sdk.client import _run_sync
        return _run_sync(self.run(symptom, affected_product))

    @property
    def graph(self):
        return self._graph
