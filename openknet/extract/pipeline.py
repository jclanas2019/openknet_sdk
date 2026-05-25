from __future__ import annotations
import hashlib
import re
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("||".join(parts).encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


# ---------------------------------------------------------------------------
# Compiled pattern cache
# ---------------------------------------------------------------------------

_CompiledEntityPatterns = list[tuple[str, str, re.Pattern]]   # (type, canonical, regex)
_CompiledRelPatterns = list[tuple[str, str, str, list[re.Pattern]]]  # (rtype, src_t, tgt_t, triggers)


class ExtractionPipeline:
    """
    Schema-driven extraction using pre-compiled regex patterns.

    Entity extraction:
      - For each entity type, compile one pattern per seed_term / alias.
      - A term match anywhere in the chunk text creates (or reuses) that entity.

    Relation extraction:
      - For each relation definition, check if any trigger keyword appears in
        the chunk; if so, create a relation for every (source, target) entity
        pair of the correct types co-occurring in the same chunk.
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self._entity_patterns: _CompiledEntityPatterns = self._compile_entities()
        self._relation_patterns: _CompiledRelPatterns = self._compile_relations()

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------

    def _compile_entities(self) -> _CompiledEntityPatterns:
        result: _CompiledEntityPatterns = []
        for etype, edef in (self.schema.get("entities") or {}).items():
            edef = edef or {}
            seed_terms = list(edef.get("seed_terms", []))
            aliases = list(edef.get("aliases", []))
            # Only include the type name itself as a term when no seed_terms are defined,
            # so that generic words like "Error" don't match inside "error 503".
            if not seed_terms and not aliases:
                seed_terms = [etype]
            terms: list[str] = seed_terms + aliases
            for term in dict.fromkeys(t for t in terms if t):  # deduplicate, preserve order
                pat = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.I)
                result.append((etype, term, pat))
        return result

    def _compile_relations(self) -> _CompiledRelPatterns:
        result: _CompiledRelPatterns = []
        for rtype, rdef in (self.schema.get("relations") or {}).items():
            rdef = rdef or {}
            src_t = rdef.get("source", "")
            tgt_t = rdef.get("target", "")
            triggers: list[str] = rdef.get(
                "triggers", [rtype.replace("_", " "), rtype]
            )
            pats = [
                re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.I)
                for t in triggers
                if t
            ]
            result.append((rtype, src_t, tgt_t, pats))
        return result

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract_entities(self, text: str, project_id: str) -> list[dict[str, Any]]:
        """Return deduplicated entity dicts found in *text*."""
        seen: dict[tuple[str, str], dict] = {}
        for etype, canonical, pat in self._entity_patterns:
            if pat.search(text):
                key = (etype, canonical.lower())
                if key not in seen:
                    seen[key] = {
                        "id": _id("ent", project_id, etype, canonical.lower()),
                        "project_id": project_id,
                        "name": canonical,
                        "type": etype,
                    }
        return list(seen.values())

    def extract_relations(
        self,
        chunk_text: str,
        chunk_id: str,
        entities: list[dict[str, Any]],
        project_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Given entities already found in this chunk, produce (relations, evidence).

        Relations are deduplicated by (source_id, rtype, target_id); evidence
        is one record per (relation, chunk) pair.
        """
        by_type: dict[str, list[dict]] = {}
        for e in entities:
            by_type.setdefault(e["type"], []).append(e)

        relations: list[dict] = []
        evidence: list[dict] = []
        seen_rels: set[tuple[str, str, str]] = set()
        seen_evs: set[tuple[str, str]] = set()

        for rtype, src_t, tgt_t, trigger_pats in self._relation_patterns:
            if not any(p.search(chunk_text) for p in trigger_pats):
                continue
            for src in by_type.get(src_t, []):
                for tgt in by_type.get(tgt_t, []):
                    if src["id"] == tgt["id"]:
                        continue
                    rel_key = (src["id"], rtype, tgt["id"])
                    rel_id = _id("rel", project_id, src["id"], rtype, tgt["id"])
                    if rel_key not in seen_rels:
                        seen_rels.add(rel_key)
                        relations.append(
                            {
                                "id": rel_id,
                                "project_id": project_id,
                                "source_id": src["id"],
                                "type": rtype,
                                "target_id": tgt["id"],
                                "confidence": 0.75,
                            }
                        )
                    ev_key = (rel_id, chunk_id)
                    if ev_key not in seen_evs:
                        seen_evs.add(ev_key)
                        evidence.append(
                            {
                                "id": _id("ev", rel_id, chunk_id),
                                "relation_id": rel_id,
                                "chunk_id": chunk_id,
                                "quote": _norm(chunk_text[:500]),
                                "method": "pattern",
                                "confidence": 0.75,
                            }
                        )

        return relations, evidence
