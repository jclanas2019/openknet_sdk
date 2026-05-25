"""
Unified ranking engine for OpenKNet.

Priority chain (best available wins at fit() time):
  1. BM25 Okapi  (rank-bm25)  — best retrieval quality; term saturation + length norm
  2. TF-IDF      (scikit-learn) — solid baseline with n-gram support
  3. Pure-Python IDF fallback  — zero extra deps; works everywhere

BM25 vs TF-IDF
--------------
TF-IDF rewards raw term frequency linearly, so a document that mentions
"error" 100 times scores much higher than one that mentions it 10 times.
BM25 adds a saturation curve (k1) so extra repetitions stop helping after
a threshold, plus document-length normalisation (b) so shorter, denser
documents aren't unfairly penalised.  For knowledge-graph entity ranking
both perform similarly on short chunks, but BM25 has a clear edge on
longer runbooks and incident reports.
"""
from __future__ import annotations

import math
import re
from typing import Any, TYPE_CHECKING

from loguru import logger
from ..config import settings

if TYPE_CHECKING:
    from .index_cache import EntityData


# ---------------------------------------------------------------------------
# UnifiedRanker
# ---------------------------------------------------------------------------

class UnifiedRanker:
    """
    Drop-in ranker that auto-selects the best available backend.

    Scores are batch-computed once per (query, corpus) pair and cached
    in memory, so the cost is O(corpus) on the first call and O(1) after.

    Args:
        k1: BM25 term-saturation parameter (default 1.5 — slightly aggressive).
        b:  BM25 length-normalisation parameter (default 0.75 — standard).
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._backend: str = "none"
        self._semantic = None
        # BM25
        self._bm25 = None
        # TF-IDF
        self._vectorizer = None
        self._corpus_matrix = None
        # Pure-Python fallback
        self._idf: dict[str, float] = {}
        # Index structures
        self._texts: list[str] = []
        self._text_idx: dict[str, int] = {}   # text → corpus index (O(1) lookup)
        self._query_cache: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, corpus: list[str]) -> None:
        """Fit the ranker on a list of raw text strings."""
        self._texts = corpus
        self._text_idx = {t: i for i, t in enumerate(corpus)}
        self._query_cache.clear()

        # --- Semantic (sentence-transformers) — highest quality ---
        if settings.semantic_enabled:
            from .semantic import get_semantic_ranker
            sem = get_semantic_ranker()
            if sem.available:
                sem.fit(corpus)
                self._semantic = sem
                self._backend = "semantic"
                logger.debug(f"Semantic ranker fitted on {len(corpus)} docs")
                return

        # --- BM25 (rank-bm25) ---
        try:
            from rank_bm25 import BM25Okapi
            tokenized = [self._tok(t) for t in corpus]
            self._bm25 = BM25Okapi(tokenized, k1=self.k1, b=self.b)
            self._backend = "bm25"
            logger.debug(f"BM25 (k1={self.k1}, b={self.b}) fitted on {len(corpus)} docs")
            return
        except ImportError:
            logger.debug("rank-bm25 not installed; trying scikit-learn TF-IDF")

        # --- TF-IDF (scikit-learn) ---
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vectorizer = TfidfVectorizer(
                max_features=50_000,
                sublinear_tf=True,
                ngram_range=(1, 2),
                min_df=1,
            )
            self._vectorizer.fit(corpus)
            # Pre-transform whole corpus once for fast batch scoring
            self._corpus_matrix = self._vectorizer.transform(corpus)
            self._backend = "tfidf"
            logger.debug(f"TF-IDF fitted on {len(corpus)} docs")
            return
        except ImportError:
            logger.debug("scikit-learn not installed; using pure-Python IDF fallback")

        # --- Pure-Python IDF fallback ---
        n = len(corpus)
        df: dict[str, int] = {}
        for doc in corpus:
            for t in set(self._tok(doc)):
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self._backend = "fallback"
        logger.debug(f"Pure-Python IDF fallback fitted on {len(corpus)} docs")

    # ------------------------------------------------------------------
    # Scoring — public API
    # ------------------------------------------------------------------

    def scores_for_query(self, query: str) -> list[float]:
        """
        Return BM25/TF-IDF scores for *all* corpus documents against *query*.
        Result is cached — repeated calls with the same query are O(1).
        """
        if not self._texts:
            return []
        if query in self._query_cache:
            return self._query_cache[query]

        if self._backend == "semantic" and self._semantic:
            return self._semantic.scores_for_query(query)

        if self._backend == "bm25":
            scores = self._bm25.get_scores(self._tok(query)).tolist()

        elif self._backend == "tfidf":
            qvec = self._vectorizer.transform([query])
            # sparse dot product: (n_docs, vocab) @ (vocab, 1) → (n_docs,)
            scores = (self._corpus_matrix * qvec.T).toarray().ravel().tolist()

        else:
            scores = [self._fallback_score(query, t) for t in self._texts]

        self._query_cache[query] = scores
        return scores

    def score_query(self, query: str, text: str) -> float:
        """Score a single *text* against *query* (uses batch cache — O(1) after first call)."""
        idx = self._text_idx.get(text)
        if idx is None:
            return 0.0
        scores = self.scores_for_query(query)
        return scores[idx] if idx < len(scores) else 0.0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fallback_score(self, query: str, text: str) -> float:
        qtok = self._tok(query)
        dtok = self._tok(text)
        tf: dict[str, int] = {}
        for t in dtok:
            tf[t] = tf.get(t, 0) + 1
        n = len(dtok) or 1
        return sum(
            (tf.get(t, 0) / n) * self._idf.get(t, math.log(2)) for t in qtok
        ) / (len(qtok) or 1)

    @staticmethod
    def _tok(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    @property
    def backend(self) -> str:
        """Which backend is active: 'bm25' | 'tfidf' | 'fallback' | 'none'."""
        return self._backend


# Backward-compatible alias
TFIDFRanker = UnifiedRanker


# ---------------------------------------------------------------------------
# Entity scoring — uses UnifiedRanker
# ---------------------------------------------------------------------------

def score_entity_data(
    entity: "EntityData",
    query: str,
    ranker: UnifiedRanker | None = None,
) -> float:
    """
    Score an EntityData snapshot against a query.
    Combines four signals:
      - Name match  (exact / partial string match in query)
      - BM25/TF-IDF (sum over entity.relevant_chunks — O(mentions))
      - Graph degree (log-scaled centrality)
      - Mention count (log-scaled corpus frequency)
    """
    q = query.lower()
    qtokens = set(re.findall(r"[a-z0-9]+", q))
    name = entity.name.lower()

    if name in q:
        name_score = 3.0
    elif any(t in name for t in qtokens):
        name_score = 1.5
    elif any(t in q for t in name.split()):
        name_score = 0.75
    else:
        name_score = 0.0

    retrieval_score = 0.0
    if ranker:
        for chunk in entity.relevant_chunks:
            retrieval_score += ranker.score_query(query, chunk.text)

    degree_score   = 0.15 * math.log1p(entity.degree)
    mention_score  = 0.08 * math.log1p(entity.mention_count)

    return name_score + retrieval_score + degree_score + mention_score


def score_entity(
    entity: Any,
    query: str,
    chunks: list[Any],
    ranker: UnifiedRanker | None = None,
) -> float:
    """ORM-based scorer — kept for compatibility."""
    q = query.lower()
    qtokens = set(re.findall(r"[a-z0-9]+", q))
    name = entity.name.lower()

    if name in q:
        name_score = 3.0
    elif any(t in name for t in qtokens):
        name_score = 1.5
    elif any(t in q for t in name.split()):
        name_score = 0.75
    else:
        name_score = 0.0

    retrieval_score = 0.0
    if ranker:
        for chunk in chunks:
            if name in chunk.text.lower():
                retrieval_score += ranker.score_query(query, chunk.text)

    degree  = len(entity.source_relations) + len(entity.target_relations)
    return (
        name_score
        + retrieval_score
        + 0.15 * math.log1p(degree)
        + 0.08 * math.log1p(entity.mention_count)
    )
