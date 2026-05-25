from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENKNET_", env_file=".env", extra="ignore")

    # ---- Storage ----
    workspace_root: Path = Path(".openknet")
    database_url: str = ""
    chunk_size: int = 800
    chunk_overlap: int = 150
    max_file_size_mb: int = 100
    build_batch_size: int = 500

    # ---- API ----
    log_level: str = "INFO"
    log_json: bool = False          # structured JSON logging for production
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ---- Auth ----
    require_auth: bool = False
    admin_api_key: str = ""

    # ---- Metrics ----
    metrics_public: bool = True        # set False to require auth on /metrics
                                       # (protects operational state from internet)

    # ---- CORS ----
    cors_origins: str = "*"        # comma-separated, e.g. "http://localhost:3000,https://app.example.com"
    cors_methods: str = "*"
    cors_headers: str = "*"      # set True in production

    # ---- PostgreSQL pool ----
    pg_pool_size: int = 10
    pg_max_overflow: int = 20
    pg_pool_timeout: int = 30
    pg_pool_recycle: int = 1800
    pg_echo: bool = False

    # ---- Circuit breaker ----
    cb_failure_threshold: int = 5   # open after N consecutive failures
    cb_timeout_seconds: int = 60    # seconds before half-open retry

    # ---- Redis ----
    redis_url: str = ""             # empty = in-memory fallback

    # ---- ARQ worker ----
    worker_concurrency: int = 4

    # ---- NLP ----
    nlp_backend: str = "auto"       # "auto" | "spacy" | "regex"
    spacy_model: str = "en_core_web_sm"

    # ---- Semantic search ----
    semantic_enabled: bool = False  # requires sentence-transformers
    semantic_model: str = "all-MiniLM-L6-v2"

    # ---- LLM provider ----
    llm_provider: str = "anthropic"         # "anthropic" | "ollama" | "openai"
    llm_model: str = ""                     # empty = provider default (see llm/providers.py)
    llm_temperature: float = 0.0
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"          # default Ollama model
    ollama_timeout: int = 120               # seconds (CPU inference can be slow)

    # ---- NLP / GLiNER ----
    gliner_enabled: bool = False            # schema-free NER (CPU-friendly)
    gliner_model: str = "urchade/gliner_small-v2.1"
    gliner_threshold: float = 0.5

    # ---- Deduplication ----
    dedup_enabled: bool = True
    dedup_threshold: float = 0.92   # string similarity 0–1

    # ---- Versioning ----
    versioning_enabled: bool = True
    max_snapshots: int = 10

    # ---- Backup ----
    backup_dir: Path = Path(".openknet/backups")
    backup_on_build: bool = False

    def get_db_url(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+asyncpg://", 1)
            if url.startswith("postgres://"):
                return url.replace("postgres://", "postgresql+asyncpg://", 1)
            return url
        db_path = self.workspace_root / "openknet.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path.resolve()}"


settings = Settings()
