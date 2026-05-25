from __future__ import annotations
from collections import deque
from typing import Any


def bfs_paths(
    source_entities: list[Any],
    target_ids: set[str],
    adjacency: dict[str, list[Any]],
    entity_map: dict[str, Any],
    max_depth: int = 4,
) -> list[dict[str, Any]]:
    """
    Breadth-first search for all simple paths from any source entity to any
    target entity, up to *max_depth* hops.

    Returns paths sorted by (confidence desc, length asc).
    """
    results: list[dict[str, Any]] = []

    for src in source_entities:
        # (current_node_id, path_so_far_as_relations, visited_ids)
        queue: deque[tuple[str, list[Any], frozenset[str]]] = deque()
        queue.append((src.id, [], frozenset({src.id})))

        while queue:
            node_id, path_rels, visited = queue.popleft()

            if len(path_rels) >= max_depth:
                continue

            for rel in adjacency.get(node_id, []):
                if rel.target_id in visited:
                    continue  # no cycles
                new_path = path_rels + [rel]
                new_visited = visited | {rel.target_id}

                if rel.target_id in target_ids:
                    # Reconstruct node names
                    node_names: list[str] = []
                    if new_path:
                        first = entity_map.get(new_path[0].source_id)
                        node_names.append(first.name if first else "?")
                    for r in new_path:
                        tgt = entity_map.get(r.target_id)
                        node_names.append(tgt.name if tgt else "?")

                    path_confidence = min(
                        (r.confidence for r in new_path), default=1.0
                    )
                    evidence_ids = [
                        ev.id for r in new_path for ev in (r.evidence or [])
                    ]

                    results.append(
                        {
                            "nodes": node_names,
                            "relations": [r.type for r in new_path],
                            "confidence": round(path_confidence, 4),
                            "length": len(new_path),
                            "evidence_ids": evidence_ids,
                        }
                    )
                else:
                    queue.append((rel.target_id, new_path, new_visited))

    # Best paths first
    results.sort(key=lambda x: (-x["confidence"], x["length"]))
    return results
