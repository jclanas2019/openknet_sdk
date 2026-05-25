"""
LangChain tool wrappers for OpenKNet.

These can be passed directly to any LangChain agent or used standalone
inside a custom LangGraph node.

Example::

    from openknet.integrations.langgraph import make_tools
    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(model="claude-sonnet-4-20250514")
    tools = make_tools("support-demo")
    agent = create_react_agent(llm, tools)
    result = await agent.ainvoke({"messages": [HumanMessage("what caused INC-1001?")]})
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


def make_tools(project: str) -> list:
    """
    Return a list of LangChain tools scoped to *project*.
    All tools are async-compatible.
    """
    from ...sdk.client import OpenKNet

    knet = OpenKNet(project)

    @tool
    async def rank_entities(query: str, limit: int = 10) -> str:
        """
        Rank knowledge-graph entities by relevance to a query.
        Returns a formatted list of entity names, types, and scores.
        """
        resp = await knet.rank(query, limit=limit)
        if not resp.results:
            return "No entities found."
        lines = [
            f"- {r.name} ({r.type}, score={r.score:.2f}, mentions={r.mention_count})"
            for r in resp.results
        ]
        return f"Top entities for '{query}':\n" + "\n".join(lines)

    @tool
    async def ask_knowledge_graph(question: str) -> str:
        """
        Ask an open-ended question to the knowledge graph.
        Returns a summary answer with supporting evidence snippets.
        """
        resp = await knet.ask(question, limit=5)
        return resp.answer

    @tool
    async def find_path(source_entity: str, target_entity: str) -> str:
        """
        Find relationship paths between two entities in the knowledge graph.
        Useful for understanding dependency or causality chains.
        """
        resp = await knet.path(source_entity, target_entity, max_depth=4)
        if not resp.found:
            return f"No path found between '{source_entity}' and '{target_entity}'."
        lines = []
        for p in resp.paths[:5]:
            chain = " → ".join(
                f"{node} --[{rel}]-->"
                for node, rel in zip(p.nodes, p.relations)
            )
            chain += f" {p.nodes[-1]}"
            lines.append(f"- {chain} (confidence={p.confidence:.0%})")
        return f"Paths from '{source_entity}' to '{target_entity}':\n" + "\n".join(lines)

    @tool
    async def get_project_stats() -> str:
        """Return statistics about the current knowledge graph project."""
        s = await knet.stats()
        return (
            f"Project '{s.project}': "
            f"{s.documents} docs, {s.chunks} chunks, "
            f"{s.entities} entities, {s.relations} relations, "
            f"{s.evidence} evidence records."
        )

    return [rank_entities, ask_knowledge_graph, find_path, get_project_stats]
