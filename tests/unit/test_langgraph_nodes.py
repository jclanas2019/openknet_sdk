"""
Node tests that don't require an LLM — covers the routing logic
and the graph-query nodes (rank_node, ask_node, path_node).
"""
import pytest
from openknet.integrations.langgraph.nodes import should_reflect, _score_confidence
from openknet.sdk.models import EntityResult


def _make_entity(score: float, etype: str = "Component") -> EntityResult:
    return EntityResult(id="x", name="X", type=etype, mention_count=1, score=score, degree=2)


def test_should_reflect_low_confidence():
    state = {"confidence": 0.2, "iteration": 0, "max_iterations": 3}
    assert should_reflect(state) == "reflect"


def test_should_synthesize_high_confidence():
    state = {"confidence": 0.9, "iteration": 0, "max_iterations": 3}
    assert should_reflect(state) == "synthesize"


def test_should_synthesize_at_max_iterations():
    state = {"confidence": 0.1, "iteration": 3, "max_iterations": 3}
    assert should_reflect(state) == "synthesize"


def test_score_confidence_no_results():
    assert _score_confidence([], []) == 0.0


def test_score_confidence_with_diverse_types():
    results = [
        _make_entity(3.0, "Component"),
        _make_entity(2.5, "Error"),
        _make_entity(2.0, "Product"),
    ]
    score = _score_confidence(results, ["some snippet"])
    assert score > 0.5


def test_score_confidence_single_type():
    results = [_make_entity(1.0, "Component")] * 5
    score = _score_confidence(results, [])
    # single type + no snippets → lower confidence
    assert score < 0.5


@pytest.mark.asyncio
async def test_rank_node(tmp_project, support_schema, sample_docs):
    from openknet.integrations.langgraph.nodes import rank_node
    from openknet import OpenKNet

    async with OpenKNet.open("lg-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()

    state = {
        "project": "lg-test",
        "question": "login error",
        "current_query": "login error",
    }
    result = await rank_node(state)

    assert "entities" in result
    assert len(result["entities"]) > 0
    assert "confidence" in result


@pytest.mark.asyncio
async def test_path_node(tmp_project, support_schema, sample_docs):
    from openknet.integrations.langgraph.nodes import path_node
    from openknet import OpenKNet

    async with OpenKNet.open("lg-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()

    state = {
        "project": "lg-test",
        "question": "login error",
        "entities": ["AuthService", "error 503"],
        "paths": [],
    }
    result = await path_node(state)
    assert "paths" in result
    assert len(result["paths"]) > 0
