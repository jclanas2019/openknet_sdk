import pytest
from openknet import OpenKNet, EntityResult, RankResponse, AskResponse, PathResponse


def test_imports():
    """SDK symbols are importable from the top-level package."""
    from openknet import OpenKNet, OpenKNetError, ProjectNotFoundError
    from openknet.sdk import BuildResponse, IngestResponse, StatsResponse


def test_client_repr():
    knet = OpenKNet("test-project")
    assert "test-project" in repr(knet)
    assert "initialized=False" in repr(knet)


def test_entity_result_model():
    e = EntityResult(
        id="ent_abc",
        name="AuthService",
        type="Component",
        mention_count=5,
        score=2.5,
        degree=10,
    )
    assert e.name == "AuthService"
    assert e.score == 2.5


def test_rank_response_model():
    r = RankResponse(
        project="p",
        query="q",
        total_matching=3,
        results=[
            EntityResult(id="x", name="A", type="T", mention_count=1, score=1.0, degree=2)
        ],
    )
    assert len(r.results) == 1
    assert r.results[0].name == "A"


def test_path_response_model():
    from openknet import PathResult
    pr = PathResponse(
        project="p",
        source="A",
        target="B",
        found=True,
        paths=[PathResult(nodes=["A", "B"], relations=["causes"], confidence=0.75, length=1)],
    )
    assert pr.found
    assert pr.paths[0].relations == ["causes"]
