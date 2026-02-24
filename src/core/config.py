"""
Configuration management for SAnalysis.

Loads default.yaml, merges with secrets.yaml (if present),
and allows environment variable overrides for API keys.

Thread-safe singleton pattern ensures safe access from
ThreadPoolExecutor workers in the orchestrator.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict.

    - Dicts are merged recursively.
    - Lists in *override* replace those in *base* (not appended).
    - All other types are overridden directly.
    """
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(cfg: dict) -> dict:
    """Override api_keys from environment variables when set."""
    env_map = {
        "REDDIT_CLIENT_ID": ("api_keys", "reddit_client_id"),
        "REDDIT_CLIENT_SECRET": ("api_keys", "reddit_client_secret"),
        "REDDIT_USER_AGENT": ("api_keys", "reddit_user_agent"),
        "FINNHUB_API_KEY": ("api_keys", "finnhub_api_key"),
        "ALPHA_VANTAGE_KEY": ("api_keys", "alpha_vantage_key"),
    }
    for env_var, path in env_map.items():
        value = os.environ.get(env_var)
        if value:
            section = cfg.setdefault(path[0], {})
            section[path[1]] = value
    return cfg


class Config:
    """Thread-safe singleton configuration accessor.

    Usage::

        from src.core.config import get_config
        cfg = get_config()
        threshold = cfg["red_team"]["min_short_float_pct"]
    """

    _instance: Config | None = None
    _lock: threading.Lock = threading.Lock()
    _data: dict[str, Any]

    def __init__(self) -> None:
        self._data = self._load()

    @classmethod
    def instance(cls) -> Config:
        """Return the singleton Config instance (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # Keep legacy classmethod name for backward compatibility
    get = instance

    @classmethod
    def reload(cls) -> Config:
        """Force-reload configuration from disk (thread-safe)."""
        with cls._lock:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Dict-like access
    # ------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """Safely traverse nested keys: cfg.get_nested('red_team', 'min_short_float_pct')."""
        node = self._data
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
                if node is None:
                    return default
            else:
                return default
        return node

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        default_path = _CONFIG_DIR / "default.yaml"
        secrets_path = _CONFIG_DIR / "secrets.yaml"

        if not default_path.exists():
            raise FileNotFoundError(
                f"Default config not found at {default_path}. "
                f"Ensure config/default.yaml exists in the project root."
            )

        with open(default_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        if secrets_path.exists():
            with open(secrets_path, "r", encoding="utf-8") as f:
                secrets = yaml.safe_load(f) or {}
            cfg = _deep_merge(cfg, secrets)
            logger.debug("Merged secrets.yaml into configuration.")

        cfg = _apply_env_overrides(cfg)
        return cfg


def get_config() -> Config:
    """Module-level shortcut for Config.get()."""
    return Config.get()
