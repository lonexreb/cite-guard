"""Shared cached-GET helper for the OpenAlex and Crossref clients.

Every network call is cached on disk during dev to conserve API credits.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

# ponytail: no TTL — dev cache, wipe data/cache/ by hand when staleness matters.
RETRYABLE = {429, 500, 502, 503, 504}


def cached_json_get(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    cache_dir: Path | None,
    max_retries: int = 3,
    retry_base_seconds: float = 1.0,
) -> dict[str, Any]:
    """GET with disk cache (keyed by url+params) and backoff on 429/5xx.

    Raises httpx.HTTPStatusError on non-retryable errors (incl. 404 —
    callers that expect misses catch it).
    """
    key = hashlib.sha256(
        json.dumps([url, sorted(params.items())]).encode()
    ).hexdigest()
    cache_file = cache_dir / f"{key}.json" if cache_dir else None
    if cache_file is not None and cache_file.exists():
        data: dict[str, Any] = json.loads(cache_file.read_text())
        return data

    attempt = 0
    while True:
        resp = client.get(url, params=params)
        if resp.status_code in RETRYABLE and attempt < max_retries:
            time.sleep(retry_base_seconds * (2**attempt))
            attempt += 1
            continue
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(payload))
        return payload
