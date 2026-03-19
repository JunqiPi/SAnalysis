"""
Lightweight file-based cache for API responses.

Stores DataFrames as parquet and arbitrary dicts as JSON.
Respects a configurable TTL so stale data is automatically refreshed.

Thread-safety: uses atomic write-then-rename to prevent partial reads
when multiple ThreadPoolExecutor workers access the same cache file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.config import get_config

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Module-level lazy cache for directory path and TTL to avoid
# redundant mkdir syscalls and config lookups per cache operation.
_CACHE_DIR: Path | None = None
_TTL_SECONDS: float | None = None


def _cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        cfg = get_config()
        rel = cfg.get_nested("general", "cache_dir", default="data/cache")
        _CACHE_DIR = _PROJECT_ROOT / rel
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _ttl_seconds() -> float:
    global _TTL_SECONDS
    if _TTL_SECONDS is None:
        cfg = get_config()
        hours = cfg.get_nested("general", "cache_ttl_hours", default=4)
        _TTL_SECONDS = float(hours) * 3600
    return _TTL_SECONDS


def _key_hash(namespace: str, key: str) -> str:
    raw = f"{namespace}::{key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _atomic_write(target: Path, content_bytes: bytes) -> None:
    """Write *content_bytes* to *target* atomically via tmp + rename.

    This prevents concurrent readers from seeing a half-written file.
    """
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    fd_closed = False
    try:
        os.write(fd, content_bytes)
        os.close(fd)
        fd_closed = True
        os.replace(tmp_path, target)  # atomic on POSIX
    except Exception:
        if not fd_closed:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------
# DataFrame cache (parquet)
# ------------------------------------------------------------------

def cache_dataframe(namespace: str, key: str, df: pd.DataFrame) -> None:
    """Persist a DataFrame to local parquet cache (atomic write)."""
    h = _key_hash(namespace, key)
    path = _cache_dir() / f"{namespace}_{h}.parquet"
    meta_path = path.with_suffix(".meta")

    # Serialize to bytes then use _atomic_write (DRY)
    parquet_bytes = df.to_parquet(index=True)
    _atomic_write(path, parquet_bytes)

    # Write metadata sidecar (atomic)
    meta_bytes = json.dumps({"ts": time.time(), "key": key}).encode("utf-8")
    _atomic_write(meta_path, meta_bytes)


def load_cached_dataframe(namespace: str, key: str) -> pd.DataFrame | None:
    """Load a DataFrame from cache if it exists and is fresh."""
    h = _key_hash(namespace, key)
    path = _cache_dir() / f"{namespace}_{h}.parquet"
    meta_path = path.with_suffix(".meta")

    if not path.exists() or not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        age = time.time() - meta.get("ts", 0)
        if age > _ttl_seconds():
            return None
        return pd.read_parquet(path)
    except Exception as exc:
        logger.debug("Cache read failed for %s/%s: %s", namespace, key, exc)
        return None


# ------------------------------------------------------------------
# Dict cache (JSON)
# ------------------------------------------------------------------

def cache_json(namespace: str, key: str, data: Any) -> None:
    """Persist a JSON-serializable object to cache (atomic write)."""
    h = _key_hash(namespace, key)
    path = _cache_dir() / f"{namespace}_{h}.json"
    payload = json.dumps(
        {"ts": time.time(), "key": key, "data": data},
        ensure_ascii=False,
    ).encode("utf-8")
    _atomic_write(path, payload)


def load_cached_json(
    namespace: str,
    key: str,
    ttl_seconds: float | None = None,
) -> Any | None:
    """Load a JSON object from cache if fresh.

    Args:
        ttl_seconds: Override global TTL for this lookup. When None,
                     the global ``cache_ttl_hours`` setting is used.
    """
    h = _key_hash(namespace, key)
    path = _cache_dir() / f"{namespace}_{h}.json"

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Cache JSON read failed for %s/%s: %s", namespace, key, exc)
        return None

    age = time.time() - payload.get("ts", 0)
    ttl = ttl_seconds if ttl_seconds is not None else _ttl_seconds()
    if age > ttl:
        return None

    return payload.get("data")


def clear_cache(namespace: str | None = None) -> int:
    """Remove cache files. If *namespace* given, only clear that prefix.

    Returns the number of files removed.
    """
    cache = _cache_dir()
    count = 0
    pattern = f"{namespace}_*" if namespace else "*"
    for f in cache.glob(pattern):
        if f.suffix in (".parquet", ".json", ".meta", ".tmp"):
            f.unlink(missing_ok=True)
            count += 1
    logger.info("Cleared %d cache files (namespace=%s).", count, namespace or "ALL")
    return count
