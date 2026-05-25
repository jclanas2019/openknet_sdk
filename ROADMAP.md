# OpenKNet — Roadmap

> This roadmap is updated with each release.  
> Items marked ✅ are **implemented and tested**. Items marked 🔲 are **planned**.  
> See [CURRENT_STATUS.md](CURRENT_STATUS.md) for the detailed feature matrix.

---

## ✅ v2.0.0 — Current release

### Core
- ✅ Document ingestion: TXT, MD, PDF, DOCX, HTML (up to 100 MB per file)
- ✅ Schema-driven entity and relation extraction (regex + word-boundary patterns)
- ✅ Sentence-aware chunking with configurable overlap
- ✅ Full and incremental builds with per-project advisory locks (SQLite + PostgreSQL)
- ✅ Entity deduplication (fuzzy matching, numeric-aware)
- ✅ Graph versioning (snapshots per build, configurable retention)
- ✅ Ingest error tracking (failed documents stored in DB, queryable)

### Storage
- ✅ SQLite async via `aiosqlite` (zero config)
- ✅ PostgreSQL async via `asyncpg` with GIN full-text index and `pg_trgm`
- ✅ Alembic migration setup (`alembic upgrade head`, `alembic revision --autogenerate`)
- ✅ Idempotent `migrate` command (Alembic path for existing DBs, create_all for bootstrap)
- ✅ Automated backup (SQLite copy / `pg_dump`)

### Ranking
- ✅ BM25 Okapi (default, installed)
- ✅ TF-IDF fallback (scikit-learn)
- ✅ Pure-Python IDF fallback (zero deps)
- ✅ Semantic dense retrieval (optional, `sentence-transformers`)
- ✅ Batch score computation with per-query in-memory cache (3 ms hot-path)

### Search
- ✅ SQLite FTS5 with Porter stemmer
- ✅ PostgreSQL tsvector + GIN (functional index, no extra column)
- ✅ Language-agnostic snippet retrieval

### API & SDK
- ✅ FastAPI async REST API with 22 endpoints
- ✅ Typed Python SDK (`OpenKNet` client, Pydantic responses, async + sync)
- ✅ CLI with 16 commands
- ✅ API key authentication with role-based access control (reader/writer/admin)
- ✅ Configurable CORS (`OPENKNET_CORS_ORIGINS`)
- ✅ Configurable `/metrics` auth (`OPENKNET_METRICS_PUBLIC`)
- ✅ Prometheus metrics (optional extra)

### NLP
- ✅ GLiNER zero-shot NER (CPU, optional, `pip install gliner`)
- ✅ spaCy NER fallback (optional, standard label set)

### LangGraph / LLM
- ✅ `ReflectiveAskGraph` (reflection loop with confidence-gated LLM refinement)
- ✅ `RootCauseGraph` (incident triage → root cause + impact + remediation)
- ✅ `make_tools()` — 4 LangChain ReAct tools
- ✅ Multi-provider LLM: Anthropic Claude, Ollama (local CPU), OpenAI
- ✅ Auto-init LLM from `OPENKNET_LLM_PROVIDER` env var

### Operations
- ✅ ARQ background worker (optional, requires Redis)
- ✅ Redis index cache (optional, in-memory fallback)
- ✅ Concurrent build protection (asyncio.Lock + pg_advisory_lock)
- ✅ `install.sh` — automated install, self-check, full test + smoke test

---

## 🔲 v2.1 — Hardening & quality (next)

**Extraction quality**

- 🔲 LLM-based relation extraction during build — call Ollama/Anthropic per-chunk to detect implicit relations without trigger keywords
- 🔲 Relation confidence calibration — replace fixed 0.75 with precision estimates from NLP models
- 🔲 Quantitative extraction benchmarks — precision/recall on a labeled test set

**Entity quality**

- 🔲 Coreference resolution — "the service" / "it" → "AuthService" using spaCy coref or LLM
- 🔲 Alias normalisation — "Auth Svc", "auth-service" → canonical "AuthService"

**Observability**

- 🔲 Structured JSON logging to file with rotation (`OPENKNET_LOG_FILE`)
- 🔲 Request trace ID propagation (OpenTelemetry)
- 🔲 Alert rules for Prometheus (build failure rate, p99 latency)

**Testing**

- 🔲 PostgreSQL integration test suite (currently SQLite only)
- 🔲 Concurrency stress tests (100 concurrent rank queries)
- 🔲 LLM prompt injection tests (validate RootCauseGraph JSON output)

---

## 🔲 v2.2 — Scale & ecosystem

**Storage**

- 🔲 pgvector integration for projects > 50k chunks (replaces numpy in-process embeddings)
- 🔲 Neo4j / Memgraph adapter (for native graph query with Cypher)
- 🔲 Multi-tenant isolation (per-tenant PostgreSQL schema)

**Extraction**

- 🔲 Temporal validity of relations (`valid_from` / `valid_to` on `Relation`)
- 🔲 Conflict detection (flag contradictory relation pairs)
- 🔲 Multi-language extraction (non-English seed terms)

**UX**

- 🔲 Human-in-the-loop review API — approve/reject extracted relations
- 🔲 Schema validation command (`openknet validate-schema`)
- 🔲 `openknet diff` — compare two graph snapshots

---

## Known limitations (will not be v2.x)

These are architectural constraints that require significant redesign:

- **No formal ontology support** — schema is a flat YAML file, not OWL/RDF
- **No real-time graph updates** — all changes require a build pass
- **No web UI** — API + CLI only; community contributions welcome
- **Relation extraction is heuristic** — co-occurrence + keyword trigger, not causal inference
- **Confidence values are routing heuristics** — not calibrated probabilities; see ARCHITECTURE.md

---

## Extraction quality (honest assessment)

Pattern-based extraction (current default) works well when:
- Entity names are specific and unlikely to appear in unrelated contexts (e.g. `INC-1001`, `AuthService`)
- Trigger keywords are unambiguous (e.g. `resolved by`, `depends on`)
- Documents are technical and controlled (runbooks, incident reports, changelogs)

It is less reliable when:
- Entity names are common words (`error`, `service`, `team`)
- Relations are expressed implicitly ("after the deployment, errors appeared" → no trigger keyword)
- Text is conversational, narrative, or multi-language

**GLiNER** (optional extra) substantially improves entity recall for unseen entities by using zero-shot NER, but does not improve relation extraction.

**LLM-based relation extraction** (planned for v2.1) would address the implicit relation problem at the cost of build time (~100 ms/chunk with Ollama llama3.2 on CPU).

For the current pattern-based extractor, a conservative estimate from the example domain:
- Precision (relations that are correct): ~85–90% (few false positives when schema is well-designed)
- Recall (relations that are found): ~60–75% (misses implicit relations)
