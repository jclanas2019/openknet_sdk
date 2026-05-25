"""
LLM provider factory for OpenKNet.

Supported providers
-------------------
anthropic   Claude via Anthropic API — best quality, requires ANTHROPIC_API_KEY
ollama      Local models via Ollama — zero cost, zero data egress, CPU-friendly
openai      GPT via OpenAI API — requires OPENAI_API_KEY

Configuration
-------------
All settings come from openknet.config.settings, overridable per-call:

    OPENKNET_LLM_PROVIDER=ollama
    OPENKNET_LLM_MODEL=llama3.2        # or leave empty for provider default
    OPENKNET_OLLAMA_BASE_URL=http://localhost:11434
    OPENKNET_OLLAMA_MODEL=llama3.2
    OPENKNET_LLM_TEMPERATURE=0.0

Usage
-----
    # Use configured provider
    llm = get_llm()

    # Override provider / model at call site
    llm = get_llm(provider="ollama", model="mistral")
    llm = get_llm(provider="anthropic", model="claude-haiku-4-5")

    # Pass directly to graphs
    graph = ReflectiveAskGraph(project="support", llm=get_llm())
    # Or let the graph auto-init from config
    graph = ReflectiveAskGraph(project="support")
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from ..config import settings


# ---------------------------------------------------------------------------
# Default models per provider
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "ollama":    "llama3.2",
    "openai":    "gpt-4o-mini",
}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    **kwargs: Any,
):
    """
    Return a LangChain chat model for the requested provider.

    Falls back gracefully:
      - anthropic → requires ANTHROPIC_API_KEY
      - ollama    → requires Ollama running locally (no API key needed)
      - openai    → requires OPENAI_API_KEY

    Raises ImportError if the required langchain package is not installed.
    Raises RuntimeError if the provider is unknown.
    """
    provider    = provider    or settings.llm_provider
    temperature = temperature if temperature is not None else settings.llm_temperature

    if provider == "anthropic":
        return _anthropic(model or settings.llm_model, temperature, **kwargs)
    elif provider == "ollama":
        return _ollama(model or settings.llm_model, temperature, **kwargs)
    elif provider == "openai":
        return _openai(model or settings.llm_model, temperature, **kwargs)
    else:
        raise RuntimeError(
            f"Unknown LLM provider: {provider!r}. "
            f"Valid options: 'anthropic', 'ollama', 'openai'"
        )


def get_llm_info() -> dict[str, str]:
    """Return the active provider/model as a dict (useful for /health)."""
    provider = settings.llm_provider
    model = settings.llm_model or _DEFAULTS.get(provider, "unknown")
    extra = {}
    if provider == "ollama":
        extra["ollama_url"] = settings.ollama_base_url
    return {"provider": provider, "model": model, **extra}


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _anthropic(model: str, temperature: float, **kwargs):
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError(
            "langchain-anthropic is not installed. "
            "Run: pip install openknet[langgraph]"
        )
    model = model or _DEFAULTS["anthropic"]
    logger.debug(f"LLM: Anthropic / {model}")
    return ChatAnthropic(model=model, temperature=temperature, **kwargs)


def _ollama(model: str, temperature: float, **kwargs):
    try:
        from langchain_ollama import ChatOllama
        impl = "langchain_ollama"
    except ImportError:
        try:
            # Older langchain community package
            from langchain_community.chat_models import ChatOllama
            impl = "langchain_community"
        except ImportError:
            raise ImportError(
                "langchain-ollama is not installed. "
                "Run: pip install openknet[ollama]"
            )

    model = model or settings.ollama_model or _DEFAULTS["ollama"]
    base_url = settings.ollama_base_url

    logger.debug(f"LLM: Ollama ({impl}) / {model} @ {base_url}")

    # Verify Ollama is reachable (soft check — warn, don't crash)
    _check_ollama(base_url, model)

    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=temperature,
        timeout=settings.ollama_timeout,
        **kwargs,
    )


def _openai(model: str, temperature: float, **kwargs):
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "langchain-openai is not installed. "
            "Run: pip install langchain-openai"
        )
    model = model or _DEFAULTS["openai"]
    logger.debug(f"LLM: OpenAI / {model}")
    return ChatOpenAI(model=model, temperature=temperature, **kwargs)


def _check_ollama(base_url: str, model: str) -> None:
    """Soft connectivity check — logs a warning if Ollama is unreachable."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3) as resp:
            import json
            data = json.loads(resp.read())
            available = [m["name"].split(":")[0] for m in data.get("models", [])]
            model_base = model.split(":")[0]
            if available and model_base not in available:
                logger.warning(
                    f"Ollama model '{model}' not found locally. "
                    f"Available: {available}. "
                    f"Run: ollama pull {model}"
                )
    except (urllib.error.URLError, OSError):
        logger.warning(
            f"Ollama not reachable at {base_url}. "
            f"Start it with: ollama serve"
        )
