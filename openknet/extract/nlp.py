"""
NLP-based entity extraction.

Two backends — both run on CPU, no GPU required:

GLiNER  (preferred)
    Schema-free NER: given arbitrary entity type labels, finds matching spans.
    Uses a bi-encoder BERT-small architecture — fast on CPU (~20–100 ms/chunk).
    Install: pip install gliner           (openknet[nlp])
    Model:   urchade/gliner_small-v2.1    (50 MB, downloaded on first use)

spaCy   (fallback)
    Classic NER with fixed label set (ORG, PERSON, PRODUCT, GPE …).
    Good for general text; cannot detect custom domain entities.
    Install: pip install spacy && python -m spacy download en_core_web_sm

Selection:
    OPENKNET_NLP_BACKEND=auto    → GLiNER if available, else spaCy, else disabled
    OPENKNET_NLP_BACKEND=gliner  → GLiNER only
    OPENKNET_NLP_BACKEND=spacy   → spaCy only
    OPENKNET_NLP_BACKEND=regex   → disabled (schema pipeline only)
"""
from __future__ import annotations
import hashlib
from typing import Any

from loguru import logger

from ..config import settings


# ---------------------------------------------------------------------------
# GLiNER extractor
# ---------------------------------------------------------------------------

class GLiNERExtractor:
    """
    Zero-shot NER using GLiNER.
    Can detect any entity type described in plain English — no schema required.

    Example entity types: ["software component", "error code", "incident ID",
                           "person", "product name", "organization"]
    """

    def __init__(self, model: str | None = None, threshold: float | None = None) -> None:
        self._model = None
        self._model_name = model or settings.gliner_model
        self._threshold = threshold if threshold is not None else settings.gliner_threshold

        if not settings.gliner_enabled:
            return
        try:
            from gliner import GLiNER
            self._model = GLiNER.from_pretrained(self._model_name)
            logger.info(f"GLiNER loaded: {self._model_name} (threshold={self._threshold})")
        except Exception as exc:
            logger.debug(f"GLiNER not available: {exc}")

    @property
    def available(self) -> bool:
        return self._model is not None

    def extract(self, text: str, project_id: str, entity_types: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Extract entities using GLiNER zero-shot NER.

        Args:
            text:         Input text to scan.
            project_id:   Used to generate deterministic entity IDs.
            entity_types: Labels to detect. Defaults to a broad general set
                          if not provided. Pass schema-derived labels for best precision.
        """
        if not self._model:
            return []

        labels = entity_types or [
            "software component", "error code", "incident ID",
            "product name", "organization", "person", "team",
            "database", "service", "error message",
        ]

        try:
            hits = self._model.predict_entities(
                text, labels, threshold=self._threshold
            )
        except Exception as exc:
            logger.warning(f"GLiNER inference error: {exc}")
            return []

        seen: dict[tuple, dict] = {}
        for hit in hits:
            # Map GLiNER label to a clean entity type
            etype = _clean_label(hit["label"])
            name = hit["text"].strip()
            if not name:
                continue
            key = (etype, name.lower())
            if key not in seen:
                eid = "ent_" + hashlib.sha1(
                    f"{project_id}||{etype}||{name.lower()}".encode()
                ).hexdigest()[:12]
                seen[key] = {
                    "id": eid,
                    "project_id": project_id,
                    "name": name,
                    "type": etype,
                    "source": "gliner",
                    "score": round(hit.get("score", 1.0), 3),
                }
        return list(seen.values())


def _clean_label(label: str) -> str:
    """Convert 'software component' → 'SoftwareComponent'."""
    return "".join(w.capitalize() for w in label.split())


# ---------------------------------------------------------------------------
# spaCy extractor
# ---------------------------------------------------------------------------

class SpacyExtractor:
    """
    spaCy NER with fixed label set.
    Best for general text; less useful for domain-specific entities.
    """

    LABEL_MAP: dict[str, str] = {
        "ORG": "Organization", "PRODUCT": "Product", "PERSON": "Person",
        "GPE": "Location", "EVENT": "Incident", "WORK_OF_ART": "Document",
        "MONEY": "Financial", "PERCENT": "Metric",
    }

    def __init__(self, model: str | None = None) -> None:
        self._nlp = None
        model = model or settings.spacy_model
        try:
            import spacy
            self._nlp = spacy.load(model)
            logger.info(f"spaCy loaded: {model}")
        except Exception as exc:
            logger.debug(f"spaCy not available: {exc}")

    @property
    def available(self) -> bool:
        return self._nlp is not None

    def extract(self, text: str, project_id: str) -> list[dict[str, Any]]:
        if not self._nlp:
            return []
        doc = self._nlp(text)
        seen: dict[tuple, dict] = {}
        for ent in doc.ents:
            etype = self.LABEL_MAP.get(ent.label_, ent.label_)
            key = (etype, ent.text.lower())
            if key not in seen:
                eid = "ent_" + hashlib.sha1(
                    f"{project_id}||{etype}||{ent.text.lower()}".encode()
                ).hexdigest()[:12]
                seen[key] = {
                    "id": eid,
                    "project_id": project_id,
                    "name": ent.text,
                    "type": etype,
                    "source": "spacy",
                }
        return list(seen.values())


# ---------------------------------------------------------------------------
# Unified NLP extractor — selects backend based on config
# ---------------------------------------------------------------------------

class NLPExtractor:
    """
    Facade that selects and wraps the best available NLP backend.

    Priority (OPENKNET_NLP_BACKEND=auto):
        GLiNER (if gliner_enabled=true and package installed)
          ↓
        spaCy (if package + model installed)
          ↓
        Disabled (returns [])
    """

    def __init__(self) -> None:
        self._gliner: GLiNERExtractor | None = None
        self._spacy: SpacyExtractor | None = None
        self._backend = "none"
        self._setup()

    def _setup(self) -> None:
        backend = settings.nlp_backend

        if backend in ("auto", "gliner"):
            g = GLiNERExtractor()
            if g.available:
                self._gliner = g
                self._backend = "gliner"
                return

        if backend in ("auto", "spacy"):
            s = SpacyExtractor()
            if s.available:
                self._spacy = s
                self._backend = "spacy"
                return

        if backend != "regex":
            logger.debug(
                f"NLP backend '{backend}': no packages available, "
                "using schema-only extraction."
            )

    @property
    def available(self) -> bool:
        return self._backend != "none"

    @property
    def backend(self) -> str:
        return self._backend

    def extract(
        self,
        text: str,
        project_id: str,
        entity_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract entities using the active backend."""
        if self._gliner:
            return self._gliner.extract(text, project_id, entity_types)
        if self._spacy:
            return self._spacy.extract(text, project_id)
        return []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_extractor: NLPExtractor | None = None


def get_nlp_extractor() -> NLPExtractor:
    global _extractor
    if _extractor is None:
        _extractor = NLPExtractor()
    return _extractor
