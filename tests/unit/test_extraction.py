from openknet.extract.pipeline import ExtractionPipeline

SCHEMA = {
    "entities": {
        "Customer": {"seed_terms": ["ACME", "Globex"]},
        "Component": {"seed_terms": ["AuthService", "BillingService"]},
        "Error": {"seed_terms": ["error 503", "timeout"]},
    },
    "relations": {
        "causes": {
            "source": "Component",
            "target": "Error",
            "triggers": ["causes", "triggering"],
        }
    },
}


def test_entity_extraction_basic():
    pipeline = ExtractionPipeline(SCHEMA)
    entities = pipeline.extract_entities("ACME reported error 503.", "proj1")
    names = {e["name"] for e in entities}
    assert "ACME" in names
    assert "error 503" in names


def test_entity_extraction_case_insensitive():
    pipeline = ExtractionPipeline(SCHEMA)
    entities = pipeline.extract_entities("authservice is down.", "proj1")
    names = {e["name"] for e in entities}
    assert "AuthService" in names


def test_entity_no_false_positive():
    pipeline = ExtractionPipeline(SCHEMA)
    entities = pipeline.extract_entities("Nothing relevant here.", "proj1")
    assert entities == []


def test_relation_extraction():
    pipeline = ExtractionPipeline(SCHEMA)
    entities = pipeline.extract_entities(
        "AuthService is triggering error 503.", "proj1"
    )
    rels, evs = pipeline.extract_relations(
        "AuthService is triggering error 503.", "chk1", entities, "proj1"
    )
    assert len(rels) == 1
    assert rels[0]["type"] == "causes"
    assert len(evs) == 1


def test_relation_no_trigger():
    pipeline = ExtractionPipeline(SCHEMA)
    entities = pipeline.extract_entities(
        "AuthService and error 503 are mentioned.", "proj1"
    )
    rels, _ = pipeline.extract_relations(
        "AuthService and error 503 are mentioned.", "chk1", entities, "proj1"
    )
    # No trigger word → no relation
    assert rels == []


def test_relation_dedup():
    pipeline = ExtractionPipeline(SCHEMA)
    text = "AuthService causes error 503."
    entities = pipeline.extract_entities(text, "proj1")
    r1, _ = pipeline.extract_relations(text, "chk1", entities, "proj1")
    r2, _ = pipeline.extract_relations(text, "chk1", entities, "proj1")
    assert len(r1) == len(r2) == 1
    assert r1[0]["id"] == r2[0]["id"]
