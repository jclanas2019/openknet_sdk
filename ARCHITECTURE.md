# OpenKNet — Architecture

## Overview

OpenKNet extracts structured knowledge from text documents and makes it
queryable via a knowledge graph. It is not a RAG system. The distinction:

| RAG | OpenKNet |
|-----|----------|
| Embeds text, retrieves similar chunks | Extracts named entities and typed relations |
| Returns text passages | Returns entities + relations + graph paths + evidence |
| Answer quality depends on semantic similarity | Answer quality depends on schema coverage |
| Works on any text out of the box | Requires a domain schema (`schema.yaml`) |
| Hard to audit "why this answer?" | Every relation points to the source passage |

## Data model

```
Document (1) ──────────────────── (n) Chunk
                                         │
                             ExtractionPipeline
                                    ├── Entity (name, type, mention_count)
                                    ├── Relation (source_id, type, target_id, confidence)
                                    └── Evidence (relation_id, chunk_id, quote)
```

All entity IDs are **deterministic SHA-1 hashes** of `(project_id, type, name.lower())`.
This means the same entity mentioned in two documents gets the same ID and its
`mention_count` accumulates correctly across builds.

## Extraction pipeline

### Current implementation (v2.0): pattern-based

Entity detection is a compiled regex scan:
- For each entity type, every `seed_term` is compiled to `(?<!\w)term(?!\w)` (word-boundary, case-insensitive)
- A chunk that matches the pattern produces an `Entity` record
- The same chunk matching both a `source` and `target` type entity, AND containing a `trigger` keyword, produces a `Relation`

**What this handles well:**
- Named identifiers: `INC-1001`, `AuthService`, `error 503`
- Multi-word terms: `Platform Team`, `depends on`, `resolved by`
- High precision when the schema is domain-specific

**What it does not handle:**
- Entities not in `seed_terms` (use GLiNER optional extra for zero-shot NER)
- Implicit relations without trigger keywords
- Coreference: "the service" after "AuthService" is not resolved
- Temporal validity: relations have no time dimension

### Optional augmentation: GLiNER

When `OPENKNET_GLINER_ENABLED=true`, the GLiNER bi-encoder NER model runs on
each chunk after the regex pass and adds entities not covered by the schema.
GLiNER uses a BERT-small architecture (~50 MB) and runs on CPU in ~20–100 ms
per chunk. No GPU required.

### Optional augmentation: spaCy

When GLiNER is unavailable and `OPENKNET_NLP_BACKEND=spacy`, spaCy NER detects
standard label types (ORG, PRODUCT, PERSON, GPE) and adds them to the entity set.

## Ranking

The `rank()` operation scores entities against a free-text query using three
signals, combined linearly:

```
final_score = name_score + retrieval_score + degree_score + mention_score
```

| Signal | Weight | Source |
|--------|--------|--------|
| `name_score` | 3.0 (exact) / 1.5 (partial) | String match between entity name and query |
| `retrieval_score` | variable | BM25/TF-IDF score over chunks mentioning entity |
| `degree_score` | 0.15 × log(degree) | Graph centrality |
| `mention_score` | 0.08 × log(count) | Corpus frequency |

The retrieval signal is computed with the best available ranker:
`SemanticRanker → BM25Okapi → TFIDFVectorizer → pure-Python IDF fallback`.

Scores are batch-computed once per (query, corpus) pair and cached in the
`ProjectIndex` in-process object. Subsequent calls with the same query are O(1).

## Full-text search

Snippet retrieval in `ask()` uses the DB's native FTS:

- **SQLite**: FTS5 virtual table with Porter ASCII stemmer, populated at ingest time
- **PostgreSQL**: functional GIN index on `to_tsvector('english', text)`, maintained automatically

Critically, `ask()` searches using **entity names** (the result of ranking),
not the user's query tokens. This makes snippet retrieval language-agnostic:
a Spanish question retrieves English snippets because the entity names are
in English.

## Index cache

The `ProjectIndex` is a plain Python object held in a module-level dict.
It is built lazily on the first query after a build and invalidated by any
subsequent build.

```python
@dataclass
class ProjectIndex:
    build_log_id: int       # staleness key
    ranker: UnifiedRanker   # fitted BM25/TF-IDF, with per-query score cache
    entities: list[EntityData]  # name, type, degree, relevant_chunks
```

When Redis is configured (`OPENKNET_REDIS_URL`), the index is serialised with
pickle and stored in Redis so it survives process restarts and is shared across
multiple API workers.

## Database

All persistent state lives in a single SQLAlchemy async engine.

```
projects          → project metadata and schema YAML
documents         → ingested file metadata and SHA-256 hash
chunks            → text segments with char offsets
processed_chunks  → build tracking for incremental mode
entities          → extracted named entities
relations         → typed directed edges between entities
evidence          → relation → chunk binding with quote text
build_logs        → build history with stats and error messages
graph_snapshots   → entity/relation counts per build (versioning)
ingest_errors     → failed document ingestion records
api_keys          → authentication keys with role and project scope
entity_feedback   → user relevance ratings per (entity, query)
```

For SQLite, all FTS lives in a separate `chunks_fts` virtual table.
For PostgreSQL, FTS is a functional GIN index on the `chunks` table —
no extra table required.

## LangGraph integration

The LangGraph graphs wrap SDK calls into stateful nodes. The `KNetState`
TypedDict flows through the graph unchanged except for the fields each
node updates.

```
ReflectiveAskGraph:
  ask_node        → calls knet.ask(), computes confidence score
  should_reflect  → pure function: confidence < threshold AND iteration < max
  reflect_node    → calls LLM to rewrite the query
  synthesize_node → calls LLM to produce final answer from evidence

RootCauseGraph:
  ask_node        → collects evidence for the symptom
  path_node       → runs BFS paths between top entities
  root_cause_node → calls LLM for structured root-cause / impact / remediation
```

The LLM provider is resolved from config at graph construction time:
`OPENKNET_LLM_PROVIDER=ollama|anthropic|openai`.

## What is NOT implemented (v2.0)

The following capabilities are explicitly on the roadmap but not yet available:

| Feature | Status | Notes |
|---------|--------|-------|
| LLM-based relation extraction during build | Planned | Would call LLM per-chunk during `build()` |
| Vector DB integration (pgvector, Chroma) | Planned | Semantic ranker uses in-process numpy |
| Neo4j / Memgraph adapter | Planned | Currently only relational DB |
| Coreference resolution | Planned | "the service" → "AuthService" |
| Temporal validity of relations | Planned | No `valid_from`/`valid_to` on relations |
| Human-in-the-loop review | Planned | No UI for reviewing extracted relations |
| Conflict detection | Planned | No logic to detect contradictory relations |
| Multi-language extraction | Partial | Snippet retrieval is language-agnostic; extraction requires English seed_terms |
| Web UI | Not planned | Only API + CLI in scope |

## Design decisions and their rationale

**Why not Neo4j?** Deployment simplicity. SQLite requires zero extra services
for development; PostgreSQL is available everywhere. The graph is stored in
relational tables and traversed with BFS in Python — adequate for graphs up
to ~100k entities. Neo4j would be warranted at larger scale or if Cypher
queries become necessary.

**Why deterministic IDs?** Hash-based entity IDs mean incremental builds can
add mention counts without querying for existing IDs. The same entity in two
documents always produces the same ID, preventing phantom duplicates.

**Why separate FTS for snippets?** BM25 ranks entities by relevance to a query;
FTS finds text snippets that mention specific entity names. These are different
operations. Using BM25 for snippets would require scoring all chunks for every
query, which is O(entities × chunks). FTS with entity name queries is O(log n).

**Why not store embeddings in the DB?** The semantic ranker stores embeddings
as a numpy array in the in-process `ProjectIndex`. For projects up to ~50k
chunks (≈40 MB of embeddings), this is faster and simpler than pgvector.
Beyond that, a vector DB is the right call.
