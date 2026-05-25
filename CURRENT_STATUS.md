# OpenKNet — Current Status

> Last updated: v2.0.0 (openknet/__init__.py, pyproject.toml, README — all consistent)

This document is the single source of truth for what is implemented,
what is tested, and what is still planned. We publish it because
"production-grade" without a status page is marketing, not documentation.

## Implemented and tested (v2.0.0)

All items below have integration tests and are covered by the CI pipeline.

### Core pipeline
- [x] Document ingestion: TXT, MD, RST, PDF, DOCX, HTML
- [x] Files up to 100 MB (configurable)
- [x] SHA-256 deduplication (re-ingesting the same file is a no-op)
- [x] Sentence-aware chunking with configurable overlap
- [x] Schema-driven entity extraction (regex, word-boundary, case-insensitive)
- [x] Schema-driven relation extraction (trigger keywords + type co-occurrence)
- [x] Evidence records linking every relation to its source chunk
- [x] Full build (clear + reprocess all chunks)
- [x] Incremental build (only new chunks since last build)
- [x] Entity deduplication (fuzzy string matching, skips numeric identifiers)
- [x] Graph versioning (snapshot per build, configurable retention)

### Ranking
- [x] BM25 Okapi (`rank-bm25`, installed by default)
- [x] TF-IDF fallback (`scikit-learn`)
- [x] Pure-Python IDF fallback (zero extra deps)
- [x] Batch score computation with per-query cache
- [x] In-process `ProjectIndex` (rebuilt after each build, O(1) on cache hit)
- [ ] Semantic ranking with `sentence-transformers` *(optional extra — works, not default)*

### Snippet retrieval
- [x] SQLite FTS5 with Porter ASCII stemmer
- [x] PostgreSQL functional GIN index on `to_tsvector`
- [x] Language-agnostic (searches by entity name, not query tokens)

### Storage
- [x] SQLite async via `aiosqlite` (zero config)
- [x] PostgreSQL async via `asyncpg` with GIN + `pg_trgm` indexes
- [x] Idempotent `migrate` command for index creation
- [x] Alembic migration engine (`alembic upgrade head`, `alembic revision --autogenerate`)
- [x] `init_db()` create_all for bootstrap; Alembic for existing DB evolution

### SDK
- [x] `OpenKNet` async client with context manager
- [x] `OpenKNet.create()` sync factory
- [x] All methods: `ingest`, `build`, `rank`, `ask`, `path`, `stats`, `entities`, `snapshots`, `ingest_errors`, `submit_feedback`
- [x] Sync wrappers for all async methods (Jupyter-compatible)
- [x] Pydantic response models for all operations
- [x] Typed exception hierarchy

### API
- [x] FastAPI async with CORS middleware
- [x] All endpoints: projects, build, rank, ask, path, stats, errors, snapshots, feedback, backup, API keys
- [x] Background build (fire-and-forget) + sync build
- [x] Incremental build via `?incremental=true`
- [x] `GET /health` with DB latency and cache backend
- [x] `GET /metrics` (Prometheus, optional extra)

### Authentication
- [x] API key middleware (header or query param)
- [x] Role-based access: reader / writer / admin
- [x] Project-scoped keys
- [x] Key creation and revocation via API
- [x] Configurable `/metrics` authentication (`OPENKNET_METRICS_PUBLIC`)
- [x] Version consistency: `__version__ == "2.0.0"` in `__init__.py`, `pyproject.toml`, README

### LangGraph
- [x] `ReflectiveAskGraph` (reflection loop, confidence-gated)
- [x] `RootCauseGraph` (structured incident triage)
- [x] `make_tools()` (4 LangChain tools for ReAct agents)
- [x] Custom node factories: `make_reflect_node`, `make_synthesize_node`, `make_root_cause_node`
- [x] Auto-init LLM from `OPENKNET_LLM_PROVIDER` env var

### LLM providers
- [x] Anthropic Claude (via `langchain-anthropic`)
- [x] Ollama local models (via `langchain-ollama`) — CPU, zero cost, zero data egress
- [x] OpenAI (via `langchain-openai`)
- [x] Soft connectivity check for Ollama (warns if model not pulled, doesn't crash)

### NLP extraction
- [x] GLiNER zero-shot NER (optional extra, CPU, ~50 MB model)
- [x] spaCy NER (optional extra, standard label set)
- [x] Auto-selection: GLiNER → spaCy → disabled

### Operations
- [x] ARQ background worker (optional extra, requires Redis)
- [x] Redis cache for `ProjectIndex` (optional extra, in-memory fallback)
- [x] SQLite and PostgreSQL backup utilities
- [x] Auto-backup before build (`OPENKNET_BACKUP_ON_BUILD=true`)
- [x] Ingest error tracking (failed documents stored in DB, queryable via API)
- [x] Prometheus metrics (optional extra)
- [x] Structured JSON logging (`OPENKNET_LOG_JSON=true`)
- [x] Circuit breaker config (failure threshold + timeout, applied to DB calls)

### Developer experience
- [x] `install.sh` — automated install, self-check, 61-test suite, smoke test
- [x] `examples/quickstart.py` — executable end-to-end demo
- [x] GitHub Actions CI (Python 3.10–3.13, lint, install.sh --ci)
- [x] 61 tests: unit + integration (chunker, extraction, SDK, API, LangGraph nodes)
- [x] Docker + docker-compose (SQLite default, PostgreSQL profile)

---

## Planned (not yet implemented)

| Feature | Priority | Notes |
|---------|----------|-------|
| LLM-based relation extraction during build | High | Per-chunk LLM calls via Ollama during `build()` |
| Entity disambiguation / coreference | High | "the service" → "AuthService" |
| pgvector / Chroma integration | Medium | For projects with >50k chunks |
| Neo4j / Memgraph adapter | Low | Current BFS is adequate to ~100k entities |
| Temporal validity of relations | Medium | `valid_from`/`valid_to` fields on relations |
| Human-in-the-loop relation review | Medium | UI/API for approving/rejecting extracted relations |
| Conflict detection | Low | Flag contradictory relations |
| Multi-language seed terms | Medium | Non-English schema support |
| Streaming build progress | Low | SSE endpoint for build progress |
| Schema validation CLI | Low | `openknet validate-schema schema.yaml` |
| Web UI | Not planned | API + CLI only |

---

## Scale: what has been tested

| Dimension | Tested | Expected limit (untested) |
|-----------|--------|--------------------------|
| Documents per project | 3 | ~10,000 (SQLite), unlimited (PG) |
| Chunks per project | 28 | ~500,000 (SQLite), unlimited (PG) |
| Entities per project | 41 | ~100,000 |
| Relations per project | 181 | ~1,000,000 |
| File size | up to 7 KB | 100 MB (config limit) |
| Concurrent API requests | 1 | depends on worker count + pool |

For projects beyond ~10k documents, PostgreSQL + ARQ workers + Redis are strongly recommended.

---

## Extraction quality (measured on example support domain)

| Metric | Value | Notes |
|--------|-------|-------|
| Precision (correct relations / extracted) | ~85–90% | With well-designed schema and technical docs |
| Recall (found / all real relations) | ~60–75% | Misses implicit relations without trigger keywords |
| Entity precision | ~95%+ | Seed terms are specific identifiers |
| Entity recall | ~70–80% | Entities not in seed_terms are missed (GLiNER improves this) |

These are estimates based on the example support domain. Your domain will vary.  
Precision is high because the pattern matcher only fires on explicit trigger keywords.  
Recall improves significantly with GLiNER (`OPENKNET_GLINER_ENABLED=true`) for entity detection,  
and will improve for relations when LLM-based extraction ships in v2.1.

---

## Benchmark (measured on Apple M2, Python 3.12, SQLite, BM25)

| Operation | Value | Notes |
|-----------|-------|-------|
| Build (28 chunks, 41 entities) | ~240 ms | Full build including dedup |
| rank() — cold (first call, index build) | ~235 ms | Fits BM25 on all chunks |
| rank() — hot (cached index) | **3 ms** | O(1) from in-memory cache |
| ask() | ~9 ms | rank + FTS5 snippet retrieval |
| path() | ~30 ms | BFS to depth 4, 41 entities |

*Hot-path latency is the relevant number for production: the index is built once
after each build and all subsequent queries are served from memory.*
