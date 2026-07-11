"""Shared runtime resources (RW index + clients), loaded once and reused.

Used by both the MCP server and the web checker so they build the same
sources the same way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from citeguard.crossref import CrossrefClient
from citeguard.openalex import OpenAlexClient
from citeguard.retractionwatch import (
    RW_DUMP_URL,
    HijackedIndex,
    RWIndex,
    download_dump,
    load_dump,
    load_hijacked,
)


@dataclass
class Resources:
    rw_index: RWIndex
    oa_client: OpenAlexClient
    cr_client: CrossrefClient
    hijacked: HijackedIndex | None
    data_dir: Path


_resources: Resources | None = None


def get_resources() -> Resources:
    """Lazy singleton; first call downloads the RW dump (~65 MB, free) if absent."""
    global _resources
    if _resources is None:
        data_dir = Path(os.environ.get("CITEGUARD_DATA_DIR", "data"))
        dump = data_dir / "retraction_watch.csv"
        if not dump.exists():
            download_dump(dump, url=RW_DUMP_URL)
        hijacked_csv = data_dir / "hijacked_journals.csv"
        _resources = Resources(
            rw_index=load_dump(dump),
            oa_client=OpenAlexClient(cache_dir=data_dir / "cache" / "openalex"),
            cr_client=CrossrefClient(cache_dir=data_dir / "cache" / "crossref"),
            hijacked=load_hijacked(hijacked_csv) if hijacked_csv.exists() else None,
            data_dir=data_dir,
        )
    return _resources
