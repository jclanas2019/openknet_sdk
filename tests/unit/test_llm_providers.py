"""
Tests for the LLM provider factory.
Does NOT require any API key or running Ollama — tests config resolution only.
"""
import pytest
from openknet.llm.providers import get_llm_info, _DEFAULTS


def test_defaults_exist():
    assert "anthropic" in _DEFAULTS
    assert "ollama" in _DEFAULTS
    assert "openai" in _DEFAULTS


def test_get_llm_info_returns_dict():
    info = get_llm_info()
    assert "provider" in info
    assert "model" in info


def test_get_llm_info_ollama_includes_url(monkeypatch):
    from openknet.config import settings
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "llm_model", "")
    info = get_llm_info()
    assert info["provider"] == "ollama"
    assert "ollama_url" in info


def test_unknown_provider_raises():
    with pytest.raises(RuntimeError, match="Unknown LLM provider"):
        from openknet.llm.providers import get_llm
        get_llm(provider="unknown_provider_xyz")


def test_ollama_missing_package_raises_import_error(monkeypatch):
    """If langchain-ollama is not installed, ImportError with helpful message."""
    import sys
    # Temporarily hide the package
    original = sys.modules.get("langchain_ollama")
    sys.modules["langchain_ollama"] = None  # type: ignore
    sys.modules["langchain_community"] = None  # type: ignore
    try:
        from openknet.llm.providers import _ollama
        with pytest.raises(ImportError, match="langchain-ollama"):
            _ollama("llama3.2", 0.0)
    finally:
        if original is not None:
            sys.modules["langchain_ollama"] = original
        else:
            sys.modules.pop("langchain_ollama", None)
        sys.modules.pop("langchain_community", None)


def test_gliner_config_defaults():
    from openknet.config import settings
    assert settings.gliner_model == "urchade/gliner_small-v2.1"
    assert 0.0 < settings.gliner_threshold < 1.0


def test_nlp_extractor_returns_empty_when_disabled(monkeypatch):
    from openknet.config import settings
    monkeypatch.setattr(settings, "nlp_backend", "regex")
    # Reset singleton
    import openknet.extract.nlp as nlp_mod
    nlp_mod._extractor = None
    extractor = nlp_mod.get_nlp_extractor()
    assert extractor.backend == "none"
    result = extractor.extract("AuthService causes error 503", "proj1")
    assert result == []
    nlp_mod._extractor = None  # cleanup


def test_clean_label():
    from openknet.extract.nlp import _clean_label
    assert _clean_label("software component") == "SoftwareComponent"
    assert _clean_label("error code") == "ErrorCode"
    assert _clean_label("person") == "Person"
