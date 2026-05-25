# OpenKNet Architecture

OpenKNet is a generalist implementation of the KNetMiner pattern.

## Core thesis

A classic RAG system retrieves text. OpenKNet retrieves text, entities, relations, graph paths and evidence.

## Data model

- Document: original source unit.
- Chunk: retrievable text fragment.
- Entity: normalized domain object.
- Relation: typed edge between entities.
- Evidence: source-backed proof for a relation.
- Path: graph traversal used to explain a candidate answer.

## Current MVP limitations

- Entity extraction is heuristic and schema-hint based.
- Relation extraction is heuristic and lexical-hint based.
- There is no production vector DB in the scaffold yet.
- The answer engine returns structured evidence instead of using an LLM to generate final prose.
- Graph persistence is local JSON, not Neo4j/Memgraph/PostgreSQL.

## Extension points

- Replace `HeuristicExtractor` with an LLM extractor using JSON schema validation.
- Replace `KeywordRetriever` with hybrid BM25 + vector retrieval.
- Replace `JsonStore` with PostgreSQL, Neo4j, Memgraph, Qdrant or OpenSearch adapters.
- Add human-in-the-loop review for proposed relations.
- Add evidence scoring by source reliability, recency and relation type.
