# OpenKNet v2.0

[![Tests](https://github.com/your-org/openknet/actions/workflows/tests.yml/badge.svg)](https://github.com/your-org/openknet/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-orange.svg)](https://github.com/astral-sh/ruff)

**Production-grade Knowledge Network Mining framework.**

Transforms unstructured text documents into a queryable, evidence-backed knowledge graph.
Provides a typed Python SDK, a full REST API, a CLI, and a LangGraph integration for
LLM-powered reflection and root-cause analysis — all running on SQLite or PostgreSQL.

```
Documents (TXT, MD, PDF, DOCX, HTML)
        ↓  ingest
    Chunks (800 chars, overlapping, FTS-indexed)
        ↓  build
  Entities ─── Relations ─── Evidence
        ↓  rank / ask / path
    Answers + Graph paths + Supporting snippets
        ↓  (optional)
  LangGraph reflection · root-cause · ReAct agents
```

> **Package name:** `openknet` (install and import as `openknet`)  
> **Repo name:** `openknet_sdk` (the SDK is the primary interface)  
> **Command:** `openknet` (installed by `pip install -e .`)  
> **Current status:** see [CURRENT_STATUS.md](CURRENT_STATUS.md) for what is implemented vs planned.

---

## Table of contents

1. [Installation](#installation)
2. [Quick start (5 commands)](#quick-start)
3. [SDK — complete reference](#sdk)
   - [Client construction](#client-construction)
   - [ingest()](#ingest)
   - [build()](#build)
   - [rank()](#rank)
   - [ask()](#ask)
   - [path()](#path)
   - [stats()](#stats)
   - [entities()](#entities)
   - [snapshots()](#snapshots)
   - [ingest\_errors()](#ingest_errors)
   - [submit\_feedback()](#submit_feedback)
   - [Response models](#response-models)
   - [Exceptions](#exceptions)
   - [Sync wrappers](#sync-wrappers)
   - [Jupyter / notebook usage](#jupyter--notebook-usage)
4. [CLI — complete reference](#cli)
5. [HTTP API — complete reference](#http-api)
6. [LangGraph integration](#langgraph-integration)
   - [ReflectiveAskGraph](#reflectiveaskg raph)
   - [RootCauseGraph](#rootcausegraph)
   - [ReAct agent tools](#react-agent-tools)
   - [Custom nodes](#custom-nodes)
   - [LLM providers](#llm-providers)
7. [Authentication & RBAC](#authentication--rbac)
8. [Schema format](#schema-format)
9. [Configuration reference](#configuration-reference)
10. [PostgreSQL setup](#postgresql-setup)
11. [Docker](#docker)
12. [Ranking — BM25 / TF-IDF / Semantic](#ranking)
13. [Full-text search](#full-text-search)
14. [Incremental builds](#incremental-builds)
15. [Entity deduplication](#entity-deduplication)
16. [Graph versioning](#graph-versioning)
17. [Feedback loop](#feedback-loop)
18. [Background workers (ARQ)](#background-workers-arq)
19. [Metrics (Prometheus)](#metrics-prometheus)
20. [Backup & recovery](#backup--recovery)
21. [NLP extraction — GLiNER / spaCy](#nlp-extraction)
22. [Semantic search](#semantic-search)
23. [Architecture](#architecture)
24. [Extending](#extending)
25. [Testing](#testing)
26. [Version analysis — v0 → v1 → v2](#version-analysis)
27. [Roadmap](#roadmap)

---

## Current status

OpenKNet v2.0 is a **framework in active development**, not a finished product.
The core pipeline (ingest → build → rank → ask → path) is stable and tested.
Several advanced features are optional extras that require additional packages.

**What works today (61 tests, CI-verified):**
- Full pipeline with SQLite (zero config) and PostgreSQL
- BM25 ranking with in-memory cache (3 ms hot-path latency)
- Language-agnostic snippet retrieval (Spanish question → English snippets)
- Typed Python SDK with async + sync interfaces
- FastAPI REST API with authentication and Prometheus metrics
- LangGraph integration: ReflectiveAsk, RootCause, ReAct tools
- Ollama support for 100% local LLM inference (no API key)
- GLiNER zero-shot NER, spaCy NER (both CPU, no GPU required)

**What is not yet implemented:**
- LLM-based relation extraction during build
- Entity coreference resolution ("the service" → "AuthService")
- pgvector / Neo4j / Memgraph backends
- Temporal validity of relations

Full list in [CURRENT_STATUS.md](CURRENT_STATUS.md).

---

## Installation

```bash
# Clone
git clone https://github.com/your-org/openknet.git && cd openknet

# Automated install (creates .venv, runs tests, smoke test)
chmod +x install.sh && ./install.sh

# Or manual
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Extras

```bash
pip install -e ".[postgres]"    # PostgreSQL async driver
pip install -e ".[langgraph]"   # LangGraph + Claude (Anthropic)
pip install -e ".[ollama]"      # Local LLM via Ollama
pip install -e ".[nlp]"         # GLiNER + spaCy NER
pip install -e ".[semantic]"    # Dense retrieval (sentence-transformers)
pip install -e ".[redis]"       # Redis cache
pip install -e ".[worker]"      # ARQ background tasks
pip install -e ".[metrics]"     # Prometheus /metrics endpoint
pip install -e ".[all,langgraph,nlp,dev]"  # Everything
```

---

## Quick start

```bash
# 1 — create project
openknet init support --schema examples/support/schema.yaml

# 2 — ingest documents
openknet ingest examples/support/docs --project support

# 3 — build the knowledge graph
openknet build --project support

# 4 — query
openknet ask "what components cause login failures?" --project support

# 5 — serve the API
openknet serve   # → http://localhost:8000/docs
```

---

## SDK

The SDK is the primary way to integrate OpenKNet into other Python programs.
All methods return Pydantic models. Both async and sync interfaces are provided.

### Client construction

```python
from openknet import OpenKNet
```

#### `OpenKNet(project)` — basic constructor

```python
knet = OpenKNet("support")
# Project must already exist in the DB (created via init or initialize())
```

#### `await OpenKNet.open(project, schema=None)` — async context manager *(recommended)*

Creates the project if it does not exist, then yields the client.
Releases resources on exit.

```python
async with OpenKNet.open("support", schema="schema.yaml") as knet:
    await knet.ingest("docs/")
    await knet.build()
    result = await knet.ask("what failed?")
```

Parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `project` | `str` | Project name (created if missing) |
| `schema` | `str \| Path \| None` | Path to schema YAML. Omit if project already exists. |

#### `OpenKNet.create(project, schema=None)` — sync factory

```python
# Synchronous — creates project and returns initialized client
knet = OpenKNet.create("support", schema="schema.yaml")
```

#### `await knet.initialize(schema=None)` — explicit init

```python
knet = OpenKNet("support")
await knet.initialize(schema="schema.yaml")
# knet._initialized is now True
```

---

### ingest()

Reads documents from a file or directory and splits them into chunks.
Skips files already ingested (deduplication by SHA-256 hash).
Supported formats: **TXT, MD, RST, PDF, DOCX, HTML**.

```python
result: IngestResponse = await knet.ingest(path)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path` | required | File or directory |

**Returns** `IngestResponse`:

```python
result.project           # str  — project name
result.documents_added   # int  — new documents this call
result.documents_total   # int  — total documents in project
result.chunks_added      # int  — new chunks this call
result.chunks_total      # int  — total chunks in project
result.skipped_oversized # int  — files skipped (exceeded max_file_size_mb)
```

**Example:**

```python
async with OpenKNet.open("support", schema="schema.yaml") as knet:
    # Ingest a directory
    r = await knet.ingest("docs/")
    print(f"Added {r.documents_added} docs, {r.chunks_added} chunks")

    # Ingest a single file
    r = await knet.ingest("report.pdf")

    # Ingest multiple paths in sequence (dedup prevents re-processing)
    for folder in ["docs/", "runbooks/", "incidents/"]:
        await knet.ingest(folder)
```

---

### build()

Extracts entities and relations from all ingested chunks and persists the
knowledge graph. Also deduplicates entities and saves a version snapshot.

```python
result: BuildResponse = await knet.build(incremental=False)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `incremental` | `bool` | `False` | Only process chunks not yet in a previous build |

**Returns** `BuildResponse`:

```python
result.project           # str
result.entities          # int  — total entities in graph
result.relations         # int  — total relations
result.evidence          # int  — total evidence records
result.chunks_processed  # int  — chunks processed this build
result.mode              # str  — "full" or "incremental"
result.dedup_merges      # int  — entities merged by deduplication (full only)
```

**Full vs incremental:**

```python
# Full rebuild — clears graph, processes all 10 000 chunks
await knet.build()

# Incremental — only processes the 50 new chunks since last build
await knet.build(incremental=True)
```

When to use each:
- **Full**: after schema changes, after deduplication threshold changes, first build
- **Incremental**: adding new documents to a live project without downtime

---

### rank()

Ranks knowledge-graph entities by relevance to a free-text query using
BM25 / TF-IDF / semantic scoring (best available backend).

```python
result: RankResponse = await knet.rank(query, limit=10)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | Free-text query |
| `limit` | `int` | `10` | Max entities to return (1–100) |

**Returns** `RankResponse`:

```python
result.project         # str
result.query           # str
result.results         # list[EntityResult]
result.total_matching  # int — entities with score > 0
result.ranker          # str — active backend: "bm25"|"tfidf"|"fallback"|"semantic"
```

Each `EntityResult`:

```python
entity.id            # str   — stable hash-based ID
entity.name          # str   — canonical name (e.g. "AuthService")
entity.type          # str   — entity type from schema (e.g. "Component")
entity.mention_count # int   — how often it appears across all chunks
entity.score         # float — relevance score
entity.degree        # int   — number of relations (graph centrality)
```

**Example:**

```python
resp = await knet.rank("database timeout", limit=5)

for entity in resp.results:
    print(f"{entity.name:20s}  {entity.type:12s}  score={entity.score:.3f}  degree={entity.degree}")

# AuthService          Component    score=2.619  degree=20
# DatabaseCluster      Component    score=2.430  degree=20
# error 503            Error        score=2.219  degree=6
```

---

### ask()

Asks a natural-language question.
Returns ranked entities, supporting text snippets retrieved via FTS,
and a summary answer string.

The snippet retrieval is **language-agnostic**: it searches by the names
of the ranked entities (English), so questions in Spanish, French, or any
other language correctly retrieve English-language evidence.

```python
result: AskResponse = await knet.ask(question, limit=5)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `question` | `str` | required | Natural-language question (any language) |
| `limit` | `int` | `5` | Max entities to include (1–20) |

**Returns** `AskResponse`:

```python
result.project   # str
result.question  # str — original question
result.answer    # str — "Related entities: X, Y, Z.\n\nSupporting evidence:\n..."
result.entities  # list[str] — entity names in rank order
result.snippets  # list[str] — up to 5 supporting text chunks (≤400 chars each)
result.results   # list[EntityResult] — full scored results
```

**Examples:**

```python
# English
resp = await knet.ask("what components cause error 503?")
print(resp.answer)
print("\nSnippets:")
for s in resp.snippets:
    print(f"  — {s[:120]}...")

# Spanish — works because snippets are retrieved by entity name, not query tokens
resp = await knet.ask("qué componentes causan errores de inicio de sesión?")
print(resp.entities)    # ['AuthService', 'error 503', 'SessionStore', ...]
print(len(resp.snippets))  # 3-5 English snippets

# Portuguese
resp = await knet.ask("quais componentes causam falhas de autenticação?")
```

---

### path()

Finds relationship paths between two named entities using breadth-first search
on the knowledge graph. Paths are sorted by confidence (desc) then length (asc).

```python
result: PathResponse = await knet.path(source, target, max_depth=4)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | required | Source entity name (case-insensitive) |
| `target` | `str` | required | Target entity name |
| `max_depth` | `int` | `4` | Max hops (1–6) |

**Returns** `PathResponse`:

```python
result.project  # str
result.source   # str
result.target   # str
result.found    # bool
result.paths    # list[PathResult]
```

Each `PathResult`:

```python
path.nodes        # list[str]   — ["AuthService", "Portal X"]
path.relations    # list[str]   — ["causes"]
path.confidence   # float       — min confidence along the path
path.length       # int         — number of hops
path.evidence_ids # list[str]   — IDs of supporting evidence records
```

**Example:**

```python
resp = await knet.path("AuthService", "error 503")

if resp.found:
    for path in resp.paths:
        chain = " → ".join(
            f"{n} --[{r}]-->" for n, r in zip(path.nodes, path.relations)
        ) + f" {path.nodes[-1]}"
        print(f"  {chain}  (confidence={path.confidence:.0%}, hops={path.length})")
# AuthService --[causes]--> error 503  (confidence=75%, hops=1)

# Multi-hop example
resp = await knet.path("ACME", "error 503", max_depth=4)
for path in resp.paths[:3]:
    print(" → ".join(path.nodes))
# ACME → INC-1001 → AuthService → error 503
```

---

### stats()

Returns project statistics including entity/relation counts, last build info,
and the active ranker backend.

```python
result: StatsResponse = await knet.stats()
```

**Returns** `StatsResponse`:

```python
result.project          # str
result.ranker_backend   # str  — "bm25"|"tfidf"|"fallback"|"semantic"|"not_built"
result.documents        # int
result.chunks           # int
result.entities         # int
result.relations        # int
result.evidence         # int
result.ingest_errors    # int  — count of documents that failed to ingest
result.last_build       # BuildInfo | None

result.last_build.status       # str   — "done"|"failed"|"running"
result.last_build.mode         # str   — "full"|"incremental"
result.last_build.started_at   # str   — ISO datetime
result.last_build.finished_at  # str | None
```

**Example:**

```python
s = await knet.stats()
print(f"Project '{s.project}':")
print(f"  {s.documents} docs, {s.chunks} chunks")
print(f"  {s.entities} entities, {s.relations} relations, {s.evidence} evidence")
print(f"  Ranker: {s.ranker_backend}")
print(f"  Last build: {s.last_build.status} ({s.last_build.mode})"
      if s.last_build else "  Never built")

if s.ingest_errors > 0:
    print(f"  ⚠  {s.ingest_errors} documents failed to ingest")
    errors = await knet.ingest_errors()
    for e in errors:
        print(f"    {e['path']}: {e['error_type']} — {e['message'][:60]}")
```

---

### entities()

Returns all entities in the project, optionally filtered by type.

```python
result: list[EntityResult] = await knet.entities(entity_type=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity_type` | `str \| None` | `None` | Filter by type (e.g. `"Component"`) |

**Example:**

```python
# All entities
all_ents = await knet.entities()

# Filter by type
components = await knet.entities(entity_type="Component")
errors     = await knet.entities(entity_type="Error")

for e in components:
    print(f"{e.name:20s}  mentions={e.mention_count}  degree={e.degree}")
```

---

### snapshots()

Returns the list of graph version snapshots saved after each build.

```python
result: list[dict] = await knet.snapshots()
```

Each snapshot dict:

```python
{
    "id": 3,
    "entities": 41,
    "relations": 181,
    "evidence": 409,
    "schema_hash": "a3f14e29",    # SHA-256 prefix of schema at build time
    "created_at": "2026-05-25T04:00:01"
}
```

**Example:**

```python
snaps = await knet.snapshots()
print(f"{len(snaps)} snapshots:")
for s in snaps:
    print(f"  #{s['id']}  {s['created_at'][:16]}  "
          f"entities={s['entities']}  relations={s['relations']}")
```

---

### ingest\_errors()

Returns documents that failed to ingest, with error details.

```python
result: list[dict] = await knet.ingest_errors()
```

Each error dict:

```python
{
    "path": "/docs/corrupted.pdf",
    "error_type": "PdfReadError",
    "message": "EOF marker not found",
    "occurred_at": "2026-05-25T03:45:12"
}
```

---

### submit\_feedback()

Records user feedback on entity relevance for a given query.
Useful for building a training signal to tune ranker weights.

```python
result: dict = await knet.submit_feedback(entity_id, query, rating, comment=None)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity_id` | `str` | Entity ID from `EntityResult.id` |
| `query` | `str` | The query that surfaced this entity |
| `rating` | `int` | 1 (irrelevant) to 5 (perfect match) |
| `comment` | `str \| None` | Optional free-text comment |

**Example:**

```python
resp = await knet.rank("login failure")
for entity in resp.results[:3]:
    # Record feedback for top results
    await knet.submit_feedback(
        entity_id=entity.id,
        query="login failure",
        rating=5 if "auth" in entity.name.lower() else 2,
    )
```

---

### Response models

All models are importable from `openknet` or `openknet.sdk.models`.

```python
from openknet import (
    OpenKNet,
    EntityResult,
    IngestResponse,
    BuildResponse,
    RankResponse,
    AskResponse,
    PathResponse,
    PathResult,
    StatsResponse,
)
from openknet.sdk.models import BuildInfo
```

#### EntityResult

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Stable deterministic ID (`ent_<sha1>`) |
| `name` | `str` | Canonical entity name |
| `type` | `str` | Entity type from schema |
| `mention_count` | `int` | Occurrences across all chunks |
| `score` | `float` | Relevance score (BM25/TF-IDF composite) |
| `degree` | `int` | Total relations (graph centrality) |

#### PathResult

| Field | Type | Description |
|-------|------|-------------|
| `nodes` | `list[str]` | Entity names along the path |
| `relations` | `list[str]` | Relation types between nodes |
| `confidence` | `float` | Minimum confidence along the path |
| `length` | `int` | Number of hops |
| `evidence_ids` | `list[str]` | IDs of supporting evidence |

#### StatsResponse

| Field | Type | Description |
|-------|------|-------------|
| `project` | `str` | |
| `ranker_backend` | `str` | `"bm25"` · `"tfidf"` · `"fallback"` · `"semantic"` · `"not_built"` |
| `documents` | `int` | |
| `chunks` | `int` | |
| `entities` | `int` | |
| `relations` | `int` | |
| `evidence` | `int` | |
| `ingest_errors` | `int` | Failed ingest count |
| `last_build` | `BuildInfo \| None` | `.status` · `.mode` · `.started_at` · `.finished_at` |

---

### Exceptions

```python
from openknet.sdk.exceptions import (
    OpenKNetError,            # base class
    ProjectNotFoundError,     # project doesn't exist in the store
    ProjectNotInitializedError,
    IngestError,              # all documents failed
    BuildError,               # build step raised an exception
    SchemaError,              # invalid YAML schema
)
```

**Handling errors:**

```python
from openknet import OpenKNet
from openknet.sdk.exceptions import ProjectNotFoundError, BuildError

async def safe_build(project_name: str) -> None:
    try:
        async with OpenKNet.open(project_name, schema="schema.yaml") as knet:
            await knet.ingest("docs/")
            result = await knet.build()
            print(f"Built: {result.entities} entities")

    except ProjectNotFoundError:
        print("Project not found — initialise it first")

    except BuildError as exc:
        print(f"Build failed: {exc}")
        # Inspect ingest errors
        knet = OpenKNet(project_name)
        errors = await knet.ingest_errors()
        for e in errors:
            print(f"  Failed: {e['path']} — {e['message']}")
```

---

### Sync wrappers

Every async method has a `_sync` variant that runs the coroutine in a new
event loop (or a thread if a loop is already running — compatible with
Jupyter notebooks).

```python
from openknet import OpenKNet

knet = OpenKNet.create("support", schema="schema.yaml")

ingest = knet.ingest_sync("docs/")
build  = knet.build_sync()
rank   = knet.rank_sync("login error", limit=5)
ask    = knet.ask_sync("what failed?")
paths  = knet.path_sync("AuthService", "error 503")
stats  = knet.stats_sync()
```

---

### Jupyter / notebook usage

```python
# In a Jupyter cell — sync wrappers work inside running event loops
from openknet import OpenKNet

knet = OpenKNet.create("support", schema="examples/support/schema.yaml")
knet.ingest_sync("examples/support/docs")
build = knet.build_sync()

print(f"Entities: {build.entities}, Relations: {build.relations}")
print(f"Ranker: {knet.stats_sync().ranker_backend}")

# Explore the graph
components = knet.rank_sync("authentication component")
for e in components.results[:5]:
    print(f"{e.name:20s} score={e.score:.2f} degree={e.degree}")

# Ask in any language
esp = knet.ask_sync("¿qué componentes causan errores de autenticación?")
print(esp.answer)
for snippet in esp.snippets:
    print(f"\n  [{snippet[:200]}]")
```

---

## CLI

```
openknet [--version] [--log-level LEVEL] COMMAND [ARGS]
```

All commands output JSON, making them easy to pipe with `jq`.

### Project management

```bash
# Create project (schema is required on first init)
openknet init my-project --schema schema.yaml

# Update schema without losing data
openknet init my-project --schema updated_schema.yaml

# List all projects
openknet projects

# Show statistics
openknet stats --project my-project

# List graph version snapshots
openknet snapshots --project my-project

# List ingest failures
openknet errors --project my-project
```

### Ingestion & build

```bash
# Ingest a directory (recursive, all supported formats)
openknet ingest /path/to/docs --project my-project

# Ingest a single file
openknet ingest report.pdf --project my-project

# Full build
openknet build --project my-project

# Incremental build (only new chunks since last build)
openknet build --project my-project --incremental

# Manual entity deduplication
openknet deduplicate --project my-project --threshold 0.85
```

### Querying

```bash
# Rank entities
openknet rank "database failure" --project my-project --limit 10

# Ask a question (any language)
openknet ask "qué componentes causan errores?" --project my-project

# Find paths between entities
openknet path "AuthService" "error 503" --project my-project --max-depth 4

# Pipe with jq
openknet rank "login error" --project support | jq '.results[0]'
openknet ask "what failed?" --project support | jq '{answer: .answer, entities: .entities}'
openknet path AuthService "error 503" --project support | jq '.paths[0].nodes'
```

### Ops & administration

```bash
# Apply DB migrations (idempotent)
openknet migrate

# Create a database backup
openknet backup --label before-migration

# Create API key
openknet key-create --name "ci-pipeline" --role writer --project my-project
openknet key-create --name "global-admin" --role admin

# Start API server
openknet serve --host 0.0.0.0 --port 8000 --workers 4

# Start ARQ background worker (requires Redis)
openknet worker
```

### Full command reference

| Command | Key options | Description |
|---------|-------------|-------------|
| `init` | `--schema PATH` | Create / update project |
| `ingest PATH` | `--project` | Ingest documents |
| `build` | `--project`, `--incremental` | Build graph |
| `rank QUERY` | `--project`, `--limit N` | Rank entities |
| `ask QUESTION` | `--project`, `--limit N` | Ask question |
| `path SRC TGT` | `--project`, `--max-depth N` | Find paths |
| `stats` | `--project` | Project statistics |
| `projects` | | List all projects |
| `snapshots` | `--project` | Graph version history |
| `errors` | `--project` | Ingest failures |
| `deduplicate` | `--project`, `--threshold F` | Merge near-duplicate entities |
| `migrate` | | Apply DB migrations |
| `backup` | `--label STR` | Create backup |
| `key-create` | `--name`, `--role`, `--project` | Create API key |
| `serve` | `--host`, `--port`, `--workers`, `--reload` | HTTP API |
| `worker` | | ARQ background worker |

---

## HTTP API

```bash
openknet serve --port 8000
# Interactive docs: http://localhost:8000/docs
```

Authentication (when `OPENKNET_REQUIRE_AUTH=true`):

```bash
curl -H "X-API-Key: ok_..." http://localhost:8000/rank?project=support&query=error
# or
curl "http://localhost:8000/rank?project=support&query=error&api_key=ok_..."
```

### Meta

#### `GET /health`

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "version": "2.0.0",
  "db": { "ok": true, "latency_ms": 1.2 },
  "cache": "memory",
  "auth": false,
  "llm": { "provider": "anthropic", "model": "claude-sonnet-4-20250514" }
}
```

#### `GET /metrics`

Prometheus metrics endpoint (requires `pip install openknet[metrics]`).

Access control is configurable:

```env
# Public (default) — Prometheus can scrape without a key
OPENKNET_METRICS_PUBLIC=true

# Protected — requires API key like any other endpoint
# Recommended when the API is exposed to the internet
OPENKNET_METRICS_PUBLIC=false
```

```bash
curl http://localhost:8000/metrics
# openknet_build_duration_seconds_bucket{...}
# openknet_entities_total{project="support"} 41.0
```

### Projects

#### `GET /projects`

```bash
curl http://localhost:8000/projects
# [{"name": "support", "id": "proj_abc", "created_at": "2026-05-25T..."}]
```

#### `POST /projects/{name}`

```bash
curl -X POST "http://localhost:8000/projects/my-project?schema_path=/path/to/schema.yaml"
# {"project": "my-project", "created": true}
```

#### `GET /projects/{name}/stats`

```bash
curl http://localhost:8000/projects/support/stats
```

```json
{
  "project": "support",
  "ranker_backend": "bm25",
  "documents": 3,
  "chunks": 28,
  "entities": 41,
  "relations": 181,
  "evidence": 409,
  "ingest_errors": 0,
  "last_build": {
    "status": "done",
    "mode": "full",
    "started_at": "2026-05-25T04:00:01",
    "finished_at": "2026-05-25T04:00:01.592"
  }
}
```

#### `GET /projects/{name}/errors`

```bash
curl http://localhost:8000/projects/support/errors
# [{"path": "/docs/bad.pdf", "error_type": "PdfReadError", "message": "..."}]
```

#### `GET /projects/{name}/snapshots`

```bash
curl http://localhost:8000/projects/support/snapshots
# [{"id": 2, "entities": 41, "relations": 181, "schema_hash": "a3f1", "created_at": "..."}]
```

### Build

#### `POST /projects/{name}/build`

| Query param | Default | Description |
|-------------|---------|-------------|
| `sync` | `false` | Block until build completes |
| `incremental` | `false` | Only process new chunks |

```bash
# Async (background)
curl -X POST "http://localhost:8000/projects/support/build"
# {"project": "support", "status": "build started", "incremental": false}

# Synchronous (blocks)
curl -X POST "http://localhost:8000/projects/support/build?sync=true"
# {"project": "support", "entities": 41, "relations": 181, ...}

# Incremental
curl -X POST "http://localhost:8000/projects/support/build?incremental=true&sync=true"
```

#### `POST /projects/{name}/deduplicate`

```bash
curl -X POST "http://localhost:8000/projects/support/deduplicate?threshold=0.85"
# {"project": "support", "merges": 2, "threshold": 0.85}
```

### Query

#### `GET /rank`

```bash
curl "http://localhost:8000/rank?project=support&query=login+error&limit=5"
```

```json
{
  "project": "support",
  "query": "login error",
  "ranker": "bm25",
  "total_matching": 35,
  "results": [
    {
      "entity": {"id": "ent_a32a", "name": "error 503", "type": "Error", "mention_count": 7},
      "score": 2.6196,
      "degree": 6
    }
  ]
}
```

#### `GET /ask`

```bash
curl "http://localhost:8000/ask?project=support&question=what+causes+login+errors"
```

```json
{
  "project": "support",
  "question": "what causes login errors",
  "answer": "Related entities: error 503, AuthService, SessionStore.\n\nSupporting evidence:\n...",
  "entities": ["error 503", "AuthService", "SessionStore"],
  "snippets": [
    "AuthService causes error 503 when JWT validation path encounters a null pointer...",
    "Portal X depends on AuthService for every login flow..."
  ],
  "results": [...]
}
```

```bash
# Works in Spanish
curl "http://localhost:8000/ask?project=support&question=qu%C3%A9+causa+error+503"
# Returns same entities and English snippets
```

#### `GET /path`

```bash
curl "http://localhost:8000/path?project=support&source=AuthService&target=error+503"
```

```json
{
  "project": "support",
  "source": "AuthService",
  "target": "error 503",
  "found": true,
  "paths": [
    {
      "nodes": ["AuthService", "error 503"],
      "relations": ["causes"],
      "confidence": 0.75,
      "length": 1,
      "evidence_ids": ["ev_083832", "ev_9518ce"]
    }
  ]
}
```

### Feedback

#### `POST /feedback`

```bash
curl -X POST "http://localhost:8000/feedback?\
project=support&entity_id=ent_a32a&query=login+error&rating=5"
# {"project": "support", "recorded": true}
```

### Backup

#### `POST /backup`

```bash
curl -X POST "http://localhost:8000/backup?label=before-migration"
# {"path": ".openknet/backups/openknet_20260525_040000_before-migration.db", "size_kb": 48.3}
```

#### `GET /backup/list`

```bash
curl http://localhost:8000/backup/list
# [{"name": "openknet_20260525_040000_before-migration.db", "size_kb": 48.3}]
```

### API Key management

#### `POST /keys`

```bash
curl -X POST "http://localhost:8000/keys?name=dashboard&role=reader&project=support" \
  -H "X-API-Key: $ADMIN_KEY"
```

```json
{
  "key": "ok_3xY7Kj...",
  "id": "a3f14e29",
  "role": "reader",
  "note": "Store this key — it is not shown again."
}
```

#### `GET /keys`

```bash
curl http://localhost:8000/keys -H "X-API-Key: $ADMIN_KEY"
```

#### `DELETE /keys/{id}`

```bash
curl -X DELETE http://localhost:8000/keys/a3f14e29 -H "X-API-Key: $ADMIN_KEY"
# {"revoked": "a3f14e29"}
```

---

## LangGraph integration

```bash
pip install -e ".[langgraph]"
```

### ReflectiveAskGraph

Evaluates answer confidence and iteratively refines the search query via LLM
until confidence is sufficient or `max_iterations` is reached.

```
START → ask_node → evaluate confidence
                     ├─ (≥ 0.55 OR max iter) → synthesize_node → END
                     └─ (< 0.55) → reflect_node → ask_node → …
```

```python
from openknet.integrations.langgraph import ReflectiveAskGraph

# Auto-init LLM from OPENKNET_LLM_PROVIDER env var
graph = ReflectiveAskGraph(project="support", max_iterations=3)
result = await graph.run("what components are responsible for login failures?")

# Final answer synthesized by LLM
print(result["final_answer"])

# Intermediate reflection steps
for note in result["reflection_notes"]:
    print(f"  Reflected: {note}")

# All evidence gathered
print(f"Entities: {result['entities']}")
print(f"Confidence: {result['confidence']:.0%}")
print(f"Snippets: {len(result['snippets'])}")

# Graph paths found
for path in result["paths"]:
    print(" → ".join(path.nodes))
```

**State fields:**

| Field | Type | Description |
|-------|------|-------------|
| `question` | `str` | Original user question |
| `current_query` | `str` | Current (possibly refined) query |
| `entities` | `list[str]` | Entity names found |
| `rank_results` | `list[EntityResult]` | Full rank results |
| `snippets` | `list[str]` | Supporting text chunks |
| `paths` | `list[PathResult]` | Graph paths found |
| `iteration` | `int` | Current reflection cycle |
| `confidence` | `float` | Answer quality estimate (0–1) |
| `reflection_notes` | `list[str]` | LLM query refinements |
| `final_answer` | `str` | Synthesized answer |
| `reasoning` | `str` | How the answer was reached |

---

### RootCauseGraph

Structured incident triage: collects evidence, traverses dependency paths,
produces root-cause / impact / remediation in JSON format.

```
START → ask_node → path_node → root_cause_node → END
```

```python
from openknet.integrations.langgraph import RootCauseGraph

graph = RootCauseGraph(project="support")
result = await graph.run(symptom="error 503", affected_product="Portal X")

print(result["root_cause_entity"])  # "AuthService"
print(result["impact_summary"])     # "Portal X unavailable for all ACME users"
print(result["remediation"])        # "Roll back AuthService to v2.3.1"
print(result["confidence"])         # 0.87
print(result["final_answer"])       # full structured report

# Dependency paths found
for path in result["paths"]:
    print(" → ".join(path.nodes), "via", path.relations)
```

**RootCauseState extra fields:**

| Field | Type | Description |
|-------|------|-------------|
| `symptom` | `str` | Error or failure description |
| `affected_product` | `str \| None` | Product/service affected |
| `root_cause_entity` | `str` | Identified root cause |
| `impact_summary` | `str` | Who/what is affected |
| `remediation` | `str` | Recommended actions |

---

### ReAct agent tools

Give an LLM agent direct access to the knowledge graph:

```python
from openknet.integrations.langgraph import make_tools
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

tools = make_tools("support")   # returns 4 LangChain tools
agent = create_react_agent(llm, tools)

result = await agent.ainvoke({
    "messages": [HumanMessage(
        "What caused INC-1001 and which component should be rolled back?"
    )]
})
print(result["messages"][-1].content)
```

Available tools:

| Tool | Signature | Description |
|------|-----------|-------------|
| `rank_entities` | `(query, limit=10)` | Rank entities by relevance |
| `ask_knowledge_graph` | `(question)` | Ask and return evidence-backed answer |
| `find_path` | `(source_entity, target_entity)` | Find dependency chains |
| `get_project_stats` | `()` | Return graph statistics |

---

### Custom nodes

Build your own graph using the individual node functions:

```python
from openknet.integrations.langgraph.nodes import (
    rank_node,                # retrieval, no LLM
    ask_node,                 # retrieval + FTS, no LLM
    path_node,                # graph traversal, no LLM
    make_reflect_node,        # factory(llm) → async node
    make_synthesize_node,     # factory(llm) → async node
    make_root_cause_node,     # factory(llm) → async node
    should_reflect,           # conditional edge (confidence threshold)
)
from openknet.integrations.langgraph.state import KNetState, RootCauseState

# Example: ask + path + synthesize (no reflection loop)
from langgraph.graph import StateGraph, START, END

llm = get_llm()   # or ChatAnthropic(...) / ChatOllama(...)

g = StateGraph(KNetState)
g.add_node("ask",        ask_node)
g.add_node("path",       path_node)
g.add_node("synthesize", make_synthesize_node(llm))

g.add_edge(START, "ask")
g.add_edge("ask", "path")
g.add_edge("path", "synthesize")
g.add_edge("synthesize", END)

graph = g.compile()
result = await graph.ainvoke({
    "project": "support",
    "question": "what causes error 503?",
    "current_query": "error 503",
    "iteration": 0, "max_iterations": 0,
    "reflection_notes": [], "paths": [], "snippets": [],
    "entities": [], "rank_results": [], "confidence": 0.0,
    "final_answer": None, "reasoning": None,
})
```

---

### LLM providers

Configure via environment variables — no code changes required.

#### Anthropic (default)

```bash
export OPENKNET_LLM_PROVIDER=anthropic
export OPENKNET_LLM_MODEL=claude-sonnet-4-20250514  # or claude-haiku-4-5
export ANTHROPIC_API_KEY=sk-ant-...
```

#### Ollama (local, zero cost, CPU)

```bash
# Install Ollama: https://ollama.com
ollama pull llama3.2
ollama serve   # starts on http://localhost:11434

export OPENKNET_LLM_PROVIDER=ollama
export OPENKNET_OLLAMA_MODEL=llama3.2   # or mistral, gemma2, phi3, etc.
export OPENKNET_OLLAMA_BASE_URL=http://localhost:11434
```

Good models for knowledge-graph tasks on CPU:

| Model | Size | Best for |
|-------|------|----------|
| `llama3.2` | 2 GB | General QA, reflection |
| `mistral` | 4 GB | Reasoning, root-cause |
| `gemma2:9b` | 5 GB | Structured JSON output |
| `phi3:mini` | 2 GB | Fast inference, simple tasks |
| `nomic-embed-text` | 270 MB | Embeddings (semantic search) |

If Ollama is not running when the graph initialises, OpenKNet logs a clear warning:
`"Ollama not reachable at http://localhost:11434. Start it with: ollama serve"`

#### OpenAI

```bash
export OPENKNET_LLM_PROVIDER=openai
export OPENKNET_LLM_MODEL=gpt-4o-mini
export OPENAI_API_KEY=sk-...
```

#### Override at call site

```python
from openknet.integrations.langgraph import get_llm, ReflectiveAskGraph

# Mix providers in the same program
graph_fast  = ReflectiveAskGraph(project="support", llm=get_llm("ollama", "phi3:mini"))
graph_smart = ReflectiveAskGraph(project="support", llm=get_llm("anthropic", "claude-sonnet-4-20250514"))
```

---

## Authentication & RBAC

### Enable

```bash
export OPENKNET_REQUIRE_AUTH=true
export OPENKNET_ADMIN_API_KEY=your-secret-master-key
openknet serve
```

### Create keys

```bash
# Global admin (all projects, all operations)
openknet key-create --name "admin" --role admin

# Project-scoped writer
openknet key-create --name "ci-pipeline" --role writer --project support

# Project-scoped reader
openknet key-create --name "dashboard" --role reader --project support
```

### Use keys

```bash
# Header
curl -H "X-API-Key: ok_3xY7..." "http://localhost:8000/rank?project=support&query=error"

# Query param
curl "http://localhost:8000/rank?project=support&query=error&api_key=ok_3xY7..."

# Python SDK
import os; os.environ["OPENKNET_API_KEY"] = "ok_3xY7..."
```

### Role matrix

| Operation | reader | writer | admin |
|-----------|--------|--------|-------|
| rank / ask / path | ✅ | ✅ | ✅ |
| stats / snapshots | ✅ | ✅ | ✅ |
| ingest / build | ❌ | ✅ | ✅ |
| deduplicate | ❌ | ✅ | ✅ |
| create project | ❌ | ✅ | ✅ |
| backup / migrate | ❌ | ❌ | ✅ |
| manage API keys | ❌ | ❌ | ✅ |

---

## Schema format

```yaml
# schema.yaml

entities:
  # Key = entity type name
  Customer:
    seed_terms: [ACME, Globex, TechCorp]   # text patterns that identify this type
    aliases: [client, account]              # additional synonyms (optional)

  Component:
    seed_terms: [AuthService, BillingService, SessionStore, DatabaseCluster]

  Error:
    seed_terms: [error 503, error 500, timeout, OOM, deadlock]
    # Multi-word phrases are supported and quoted automatically

  Incident:
    seed_terms: [INC-1001, INC-1002, INC-1003]

  Engineer:
    seed_terms: [Alice, Bob, Carol]

  Team:
    seed_terms: [Platform Team, Backend Team, SRE Team]

relations:
  # Key = relation type name
  causes:
    source: Component    # must match an entity type defined above
    target: Error
    triggers:            # keywords that activate this relation
      - causes
      - caused
      - triggering
      - produces

  resolved_by:
    source: Incident
    target: Component
    triggers: [resolved by, mitigated by, fixed by, closed by]

  depends_on:
    source: Product
    target: Component
    triggers: [depends on, backed by, requires, uses]

  owned_by:
    source: Component
    target: Team
    triggers: [owned by, maintained by, managed by]
```

**How extraction works:**
1. Each chunk is scanned for `seed_terms` patterns (case-insensitive, word-boundary anchored).
2. When a `trigger` keyword appears in a chunk **and** both `source` and `target` type entities are also present, a relation is created.
3. Every relation is backed by an `Evidence` record containing the original chunk text — fully auditable.

---

## Configuration reference

All settings via environment variables (prefix `OPENKNET_`) or `.env` file.

```bash
cp .env.example .env
$EDITOR .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| **Storage** | | |
| `OPENKNET_WORKSPACE_ROOT` | `.openknet` | SQLite DB directory |
| `OPENKNET_DATABASE_URL` | *(SQLite)* | Override DB URL (see PostgreSQL section) |
| `OPENKNET_CHUNK_SIZE` | `800` | Target characters per chunk |
| `OPENKNET_CHUNK_OVERLAP` | `150` | Overlap chars between adjacent chunks |
| `OPENKNET_MAX_FILE_SIZE_MB` | `100` | Skip files larger than this |
| `OPENKNET_BUILD_BATCH_SIZE` | `500` | DB flush interval during build |
| **API** | | |
| `OPENKNET_API_HOST` | `0.0.0.0` | Bind address |
| `OPENKNET_API_PORT` | `8000` | HTTP port |
| `OPENKNET_LOG_LEVEL` | `INFO` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |
| `OPENKNET_LOG_JSON` | `false` | JSON structured logging (production) |
| **Auth** | | |
| `OPENKNET_REQUIRE_AUTH` | `false` | Enforce API key on all endpoints |
| `OPENKNET_ADMIN_API_KEY` | *(empty)* | Master key (never stored in DB) |
| **LLM** | | |
| `OPENKNET_LLM_PROVIDER` | `anthropic` | `anthropic` · `ollama` · `openai` |
| `OPENKNET_LLM_MODEL` | *(provider default)* | Model name override |
| `OPENKNET_LLM_TEMPERATURE` | `0.0` | Generation temperature |
| `OPENKNET_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OPENKNET_OLLAMA_MODEL` | `llama3.2` | Default Ollama model |
| `OPENKNET_OLLAMA_TIMEOUT` | `120` | Seconds before timeout (CPU can be slow) |
| **NLP** | | |
| `OPENKNET_NLP_BACKEND` | `auto` | `auto` · `gliner` · `spacy` · `regex` |
| `OPENKNET_GLINER_ENABLED` | `false` | Enable GLiNER NER |
| `OPENKNET_GLINER_MODEL` | `urchade/gliner_small-v2.1` | GLiNER model |
| `OPENKNET_GLINER_THRESHOLD` | `0.5` | Entity detection confidence |
| `OPENKNET_SPACY_MODEL` | `en_core_web_sm` | spaCy model |
| **Semantic** | | |
| `OPENKNET_SEMANTIC_ENABLED` | `false` | Dense retrieval ranking |
| `OPENKNET_SEMANTIC_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |
| **Graph quality** | | |
| `OPENKNET_DEDUP_ENABLED` | `true` | Auto-dedup after full build |
| `OPENKNET_DEDUP_THRESHOLD` | `0.85` | String similarity threshold (0–1) |
| `OPENKNET_VERSIONING_ENABLED` | `true` | Save graph snapshot per build |
| `OPENKNET_MAX_SNAPSHOTS` | `10` | Snapshots to keep (oldest pruned) |
| **Backup** | | |
| `OPENKNET_BACKUP_DIR` | `.openknet/backups` | Backup file directory |
| `OPENKNET_BACKUP_ON_BUILD` | `false` | Auto-backup before each full build |
| **PostgreSQL pool** | | |
| `OPENKNET_PG_POOL_SIZE` | `10` | Min connections to keep open |
| `OPENKNET_PG_MAX_OVERFLOW` | `20` | Extra connections allowed |
| `OPENKNET_PG_POOL_TIMEOUT` | `30` | Seconds to wait for a connection |
| `OPENKNET_PG_POOL_RECYCLE` | `1800` | Recycle connections after N seconds |
| `OPENKNET_PG_ECHO` | `false` | Log all SQL statements |
| **Circuit breaker** | | |
| `OPENKNET_CB_FAILURE_THRESHOLD` | `5` | Open circuit after N consecutive failures |
| `OPENKNET_CB_TIMEOUT_SECONDS` | `60` | Seconds before half-open retry |
| **Redis** | | |
| `OPENKNET_REDIS_URL` | *(empty)* | Redis URL (empty = in-memory cache) |
| **Worker** | | |
| `OPENKNET_WORKER_CONCURRENCY` | `4` | Max concurrent ARQ jobs |

---

## PostgreSQL setup

```bash
# 1. Install driver
pip install -e ".[postgres]"

# 2. Configure (both formats accepted)
export OPENKNET_DATABASE_URL=postgresql://user:pass@localhost:5432/openknet
# or
export OPENKNET_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/openknet

# 3. Create tables + indexes
openknet migrate
```

`migrate` creates automatically:

```sql
-- Full-text search (no extra column needed)
CREATE INDEX ix_chunks_fts_gin
  ON chunks USING GIN (to_tsvector('english', text));

-- Fuzzy entity name matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_entity_name_trgm
  ON entities USING GIN (name gin_trgm_ops);
```

Pool tuning for production:

```env
OPENKNET_PG_POOL_SIZE=20
OPENKNET_PG_MAX_OVERFLOW=40
OPENKNET_PG_POOL_RECYCLE=3600
```

---

## Docker

```bash
# SQLite (zero config)
docker compose up --build

# PostgreSQL
docker compose --profile postgres up --build
```

The `api-pg` service waits for the `db` healthcheck before starting and
connects to `postgresql://openknet:openknet@db:5432/openknet`.

---

## Ranking

Backend is selected automatically at build time and shown in `stats.ranker_backend`.

```
SemanticRanker (sentence-transformers, SEMANTIC_ENABLED=true)
      ↓
BM25 Okapi (rank-bm25, installed by default)
      ↓
TF-IDF (scikit-learn)
      ↓
Pure-Python IDF fallback (always available)
```

**BM25 vs TF-IDF**

TF-IDF scores grow linearly with term frequency — a document mentioning
"error" 50 times scores 5× higher than one mentioning it 10 times. BM25
adds term saturation (`k1=1.5`) so extra repetitions yield diminishing
returns, plus document-length normalisation (`b=0.75`) so short dense
chunks compete fairly with long ones.

All scores are **batch-computed** for the whole corpus per query and
**cached in memory** — repeated queries with the same text are O(1).

---

## Full-text search

Used for snippet retrieval in `ask()`. Searches by **entity name** (not
query tokens) → language-agnostic.

| Backend | Mechanism | Requires |
|---------|-----------|----------|
| SQLite | FTS5 virtual table, Porter ASCII stemmer | automatic |
| PostgreSQL | Functional GIN on `to_tsvector('english', text)` | `openknet migrate` |

Both fall back to a linear scan if FTS fails.

---

## Incremental builds

```bash
openknet build --project support --incremental
```

A `processed_chunks` table tracks which chunks have been included in a build.
Incremental mode processes only chunks not yet in that table — it adds new
entities/relations without touching existing ones.

Full rebuild resets the table and reprocesses everything.

---

## Entity deduplication

```bash
openknet deduplicate --project support --threshold 0.85
```

Uses `difflib.SequenceMatcher` within each entity type. Entities at ≥85%
similarity are merged: the one with fewer mentions gets `canonical_id` set
and is excluded from rank/path queries. Runs automatically after each full
build when `OPENKNET_DEDUP_ENABLED=true`.

---

## Graph versioning

Every successful build saves a `GraphSnapshot` with entity/relation counts
and a hash of the schema. View history:

```bash
openknet snapshots --project support
```

Old snapshots are pruned to keep the last `OPENKNET_MAX_SNAPSHOTS` (default 10).

---

## Feedback loop

```bash
# Via API
curl -X POST "http://localhost:8000/feedback?\
project=support&entity_id=ent_a32a&query=login+error&rating=5"

# Via SDK
await knet.submit_feedback("ent_a32a", query="login error", rating=4,
                            comment="very relevant for auth failures")
```

Stored in `entity_feedback` table — use for tuning ranker signal weights.

---

## Background workers (ARQ)

Offload slow builds to a dedicated process (requires Redis):

```bash
# Start worker
export OPENKNET_REDIS_URL=redis://localhost:6379
openknet worker

# Enqueue from Python
from arq import create_pool
from arq.connections import RedisSettings
from openknet.workers.tasks import enqueue_build

redis = await create_pool(RedisSettings.from_dsn("redis://localhost"))
job_id = await enqueue_build(redis, "support", incremental=True)
```

Available tasks: `build_project`, `ingest_documents`, `deduplicate_project`.

---

## Metrics (Prometheus)

```bash
pip install -e ".[metrics]"
curl http://localhost:8000/metrics
```

| Metric | Type | Labels |
|--------|------|--------|
| `openknet_build_duration_seconds` | Histogram | `project`, `mode` |
| `openknet_ingest_documents_total` | Counter | `project`, `format` |
| `openknet_ingest_errors_total` | Counter | `project`, `error_type` |
| `openknet_entities_total` | Gauge | `project` |
| `openknet_relations_total` | Gauge | `project` |
| `openknet_query_duration_seconds` | Histogram | `operation` |
| `openknet_cache_hits_total` | Counter | `backend` |
| `openknet_cache_misses_total` | Counter | `backend` |
| `openknet_dedup_merges_total` | Counter | `project` |

---

## Backup & recovery

```bash
# Create backup
openknet backup --label before-migration

# List backups
curl http://localhost:8000/backup/list

# Auto-backup before every full build
export OPENKNET_BACKUP_ON_BUILD=true
```

SQLite: `shutil.copy2` to `.openknet/backups/`.
PostgreSQL: `pg_dump | gzip` to `.sql.gz`.
Old backups pruned automatically (keeps last 10).

---

## NLP extraction

GLiNER and spaCy augment the schema-based regex pipeline — both run on CPU
without GPU.

### GLiNER (recommended)

Zero-shot NER: detects any entity type described in plain English.

```bash
pip install gliner
export OPENKNET_GLINER_ENABLED=true
openknet build --project support   # model downloaded on first run (~50 MB)
```

GLiNER detects entities not declared in `seed_terms`:

```python
# schema has no "Engineer" type — GLiNER finds it anyway
# Text: "Alice investigated the AuthService outage on March 12"
# GLiNER: [{"text": "Alice", "type": "Person"}, {"text": "AuthService", ...}]
```

### spaCy (fallback)

```bash
pip install spacy
python -m spacy download en_core_web_sm
export OPENKNET_NLP_BACKEND=spacy
```

Selection order: GLiNER → spaCy → disabled (`OPENKNET_NLP_BACKEND=auto`).

---

## Semantic search

```bash
pip install -e ".[semantic]"
export OPENKNET_SEMANTIC_ENABLED=true
openknet build --project support   # fits embeddings on first build
```

Finds conceptually related entities when keywords don't match exactly:
"authentication failure" retrieves chunks about "login error" and "AuthService".

Sits at the top of the ranking chain: Semantic → BM25 → TF-IDF → fallback.

---

## Benchmarks

Measured on Apple M2, Python 3.12, SQLite, BM25 (3 docs / 28 chunks / 41 entities):

| Operation | Latency | Notes |
|-----------|---------|-------|
| `build()` full | ~240 ms | Includes dedup pass |
| `rank()` cold | ~235 ms | First call: fits BM25, builds index |
| `rank()` hot | **3 ms** | Subsequent calls: in-memory cache hit |
| `ask()` | ~9 ms | rank + FTS5 snippet retrieval |
| `path()` | ~30 ms | BFS depth 4, 41 entities |

The hot-path latency (3 ms) is the production-relevant number. The index is
built once after each `build()` and all subsequent queries are served from
RAM with no DB access.

Run locally:
```bash
python examples/quickstart.py    # end-to-end demo
python -m pytest tests/ -v       # full test suite (61 tests)
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Public surface                             │
│  SDK (OpenKNet)  ·  CLI (openknet)  ·  HTTP API (:8000)          │
└──────────┬────────────────┬──────────────────────────────────────┘
           │                │
  ┌────────▼────────┐  ┌────▼────────────────────────────────────┐
  │  project.py     │  │  integrations/langgraph/                │
  │  (core facade)  │  │  ReflectiveAskGraph · RootCauseGraph    │
  └─┬──┬──┬──┬──────┘  │  make_tools() · custom nodes           │
    │  │  │  │          └────────────────────┬────────────────────┘
 ingest│ rank path                           │
    │  │  │  │                     ┌─────────▼──────────┐
  ┌─▼──┐ ┌▼───────────────────────▼──┐      │           │
  │ingest│ │  search/                  │  llm/providers.py│
  │      │ │  UnifiedRanker            │  Anthropic       │
  │reader│ │  (semantic→BM25→tfidf)   │  Ollama (local)  │
  │chunker│ │  index_cache (RAM/Redis)│  OpenAI          │
  └──────┘ │  fts.py (FTS5 / PG GIN) └──────────────────┘
           │  graph.py (BFS paths)
           └──────────┬────────────
                      │
  ┌───────────────────▼──────────────────────────────────────────┐
  │                        db.py                                  │
  │  SQLite (aiosqlite)  /  PostgreSQL (asyncpg + GIN + trgm)    │
  └──────────────────────────────────────────────────────────────┘
  ┌────────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────┐
  │  auth/     │  │  cache/      │  │  backup/   │  │monitoring│
  │  API keys  │  │  Redis/mem   │  │  sqlite/pg │  │Prometheus│
  │  RBAC      │  │  index cache │  │  pg_dump   │  │metrics   │
  └────────────┘  └──────────────┘  └────────────┘  └──────────┘
  ┌───────────────────────────────────────────────────────────────┐
  │  extract/                                                     │
  │  pipeline.py (regex)  ·  nlp.py (GLiNER → spaCy → disabled)  │
  └───────────────────────────────────────────────────────────────┘
```

---

## Extending

### New document format

```python
# openknet/ingest/readers.py — add a Reader class
class EpubReader:
    EXTENSIONS = {".epub"}
    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() in self.EXTENSIONS
    def read(self, path: Path) -> str:
        # ... parse epub
        return text

_READERS.append(EpubReader())
```

### Custom entity extractor

```python
# openknet/extract/pipeline.py — replace ExtractionPipeline
# Must implement:
#   extract_entities(text, project_id) → list[dict]
#   extract_relations(text, chunk_id, entities, project_id) → (list[dict], list[dict])
```

### Custom ranker

```python
# Subclass UnifiedRanker
class MyRanker(UnifiedRanker):
    def fit(self, corpus): ...
    def scores_for_query(self, query): ...
```

### Custom LangGraph node

```python
from openknet.integrations.langgraph.state import KNetState

async def my_node(state: KNetState) -> dict:
    # read from state, compute something, return partial update
    entities = state["entities"]
    return {"final_answer": f"Found: {', '.join(entities)}"}
```

---

## Testing

```bash
# Install dev extras
pip install -e ".[dev,langgraph]"

# Full suite
pytest tests/ -v

# With coverage
pytest tests/ --cov=openknet --cov-report=html

# Unit only (fast, no DB)
pytest tests/unit/ -v

# Integration only
pytest tests/integration/ -v
```

| File | What it covers |
|------|----------------|
| `tests/unit/test_chunker.py` | Sentence-aware chunking, overlap |
| `tests/unit/test_extraction.py` | Regex entity + relation extraction |
| `tests/unit/test_sdk.py` | SDK models, exceptions, client repr |
| `tests/unit/test_langgraph_nodes.py` | Routing logic, graph nodes (no LLM) |
| `tests/unit/test_llm_providers.py` | LLM factory, Ollama soft-check |
| `tests/integration/test_project.py` | Full pipeline (ingest→build→query) |
| `tests/integration/test_api.py` | All HTTP endpoints |
| `tests/integration/test_sdk_client.py` | SDK async/sync, all methods |

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full feature matrix with ✅ implemented and 🔲 planned items.

**v2.1 priorities** (next release):
- LLM-based relation extraction during build (implicit relations without trigger keywords)
- Coreference resolution ("the service" → "AuthService")
- PostgreSQL integration test suite
- Structured JSON logging with file rotation

**Extraction quality note** — Pattern-based extraction achieves ~85–90% precision and ~60–75% recall on technical documents (runbooks, incident reports). For conversational or narrative text, recall drops. See ROADMAP.md for the planned LLM-based extraction path.

---

## Version analysis

### Metrics

| Metric | v0.1.6 (MVP) | v1.0.0 | v2.0.0 |
|--------|-------------|--------|--------|
| Python files | 6 | 28 | **41** |
| Lines of code | ~600 | ~2,800 | **~4,200** |
| Tests | 0 | 32 | **61** |
| DB tables | 0 (JSON) | 7 | **14** |
| CLI commands | 6 | 10 | **16** |
| API endpoints | 6 | 10 | **22** |
| Optional extras | 0 | 3 | **8** |
| LLM providers | 0 | 1 (Anthropic) | **3 (Anthropic/Ollama/OpenAI)** |

### Production readiness

| Dimension | v0.1.6 | v1.0.0 | v2.0.0 |
|-----------|--------|--------|--------|
| Storage | ❌ JSON | ✅ SQLite async | ✅ SQLite + PostgreSQL pooled |
| Authentication | ❌ None | ❌ None | ✅ API keys + RBAC |
| Observability | ❌ print | ⚠️ Loguru | ✅ Loguru + Prometheus |
| Reliability | ❌ crashes | ⚠️ error handling | ✅ circuit breaker + ingest error tracking |
| Ranking | ❌ string count | ✅ BM25 + TF-IDF | ✅ Semantic → BM25 → TF-IDF chain |
| Builds | ❌ full only | ✅ full + cache | ✅ full + incremental + versioning |
| Entity quality | ❌ no dedup | ❌ no dedup | ✅ GLiNER + fuzzy dedup |
| LLM integration | ❌ none | ✅ Anthropic only | ✅ Anthropic + Ollama + OpenAI |
| Scalability | ❌ single process | ⚠️ async API | ✅ ARQ workers + Redis cache |
| Recovery | ❌ no backup | ❌ no backup | ✅ automated backup + versioning |

### What remains for v3

The two biggest quality improvements that require ML inference:

1. **Schema-free relation extraction** — current relations are triggered by keyword co-occurrence. A relation extraction model (REBEL, or a prompted LLM during build) would find implicit relations: *"Portal X went down after the AuthService deployment"* → `causes(AuthService, Portal X downtime)` without the word "causes". This is now straightforward with the Ollama integration — the build pipeline can call a local LLM per-chunk. The tradeoff is build time (~100ms/chunk on CPU).

2. **Entity disambiguation** — "Apple" the company and "Apple" the fruit are the same entity if both appear in the same project. A disambiguation step (embeddings + context) would separate them. The deduplication system already handles morphological variants (`AuthService` / `Auth Service`); full disambiguation requires understanding context.
