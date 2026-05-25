from __future__ import annotations

from loguru import logger

from ..config import settings


class SemanticRanker:
    """
    Dense retrieval using sentence-transformers cosine similarity.
    Integrates into UnifiedRanker as an optional top-tier backend.

    Requires: `pip install sentence-transformers`  (openknet[semantic])
    Falls back gracefully if not installed.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = None
        self._embeddings = None
        self._texts: list[str] = []
        self._text_idx: dict[str, int] = {}
        self._query_cache: dict[str, list[float]] = {}
        self._model_name = model or settings.semantic_model

        if not settings.semantic_enabled:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            logger.info(f"Semantic ranker loaded: {self._model_name}")
        except Exception as exc:
            logger.debug(f"sentence-transformers not available ({exc})")

    @property
    def available(self) -> bool:
        return self._model is not None

    def fit(self, corpus: list[str]) -> None:
        if not self._model:
            return
        import numpy as np
        self._texts = corpus
        self._text_idx = {t: i for i, t in enumerate(corpus)}
        self._embeddings = self._model.encode(corpus, normalize_embeddings=True, show_progress_bar=False)
        self._query_cache.clear()
        logger.debug(f"Semantic ranker fitted: {len(corpus)} docs")

    def scores_for_query(self, query: str) -> list[float]:
        if not self._model or self._embeddings is None:
            return [0.0] * len(self._texts)
        if query in self._query_cache:
            return self._query_cache[query]
        import numpy as np
        q_emb = self._model.encode([query], normalize_embeddings=True)
        scores = (self._embeddings @ q_emb[0]).tolist()
        self._query_cache[query] = scores
        return scores

    def score_query(self, query: str, text: str) -> float:
        idx = self._text_idx.get(text)
        if idx is None:
            return 0.0
        return self.scores_for_query(query)[idx]


# Singleton
_semantic: SemanticRanker | None = None


def get_semantic_ranker() -> SemanticRanker:
    global _semantic
    if _semantic is None:
        _semantic = SemanticRanker()
    return _semantic
