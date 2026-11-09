"""Settings: a tiny, safe loader for ``settings.json``.

Settings decide the run mode (mock / dry_run / live) and which AI provider
to use. The loader is deliberately defensive: if the file is missing, broken,
or has an unknown value, we fall back to the SAFE default (``mock``), so a typo
can never accidentally send anything to a real site.

(Per-task providers, caps, filters and the blocklist arrive in later phases.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "settings.json"

RUN_MODES = ("mock", "dry_run", "live")
AI_PROVIDERS = ("mock", "ollama", "gemini")


@dataclass(frozen=True)
class Settings:
    """Immutable settings object. Defaults are the safest values."""

    run_mode: str = "mock"
    ai_provider: str = "ollama"
    ollama_model: str = "llama3.1:8b"
    embed_model: str = "nomic-embed-text"


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Read ``settings.json`` and return a validated :class:`Settings`.

    Any problem (missing file, invalid JSON, unknown value) falls back to the
    default for that field, never to something riskier.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    defaults = Settings()
    run_mode = raw.get("run_mode")
    ai_provider = raw.get("ai_provider")
    ollama_model = raw.get("ollama_model")
    embed_model = raw.get("embed_model")
    return Settings(
        run_mode=run_mode if run_mode in RUN_MODES else defaults.run_mode,
        ai_provider=ai_provider if ai_provider in AI_PROVIDERS else defaults.ai_provider,
        ollama_model=ollama_model if isinstance(ollama_model, str) and ollama_model else defaults.ollama_model,
        embed_model=embed_model if isinstance(embed_model, str) and embed_model else defaults.embed_model,
    )
