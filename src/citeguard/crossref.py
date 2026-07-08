"""Crossref REST helpers: find editorial notices that update a DOI.

Crossref is free (polite pool via mailto); no credit budgeting needed.
The `update-to` field lives on the *notice*, so we query
/works?filter=updates:{doi} to find notices targeting a work.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from citeguard._http import cached_json_get
from citeguard.status import Signal, Source, StatusKind, Strength, normalize_doi

CROSSREF_BASE = "https://api.crossref.org"

_UPDATE_TYPE_MAP: dict[str, StatusKind] = {
    "retraction": StatusKind.RETRACTED,
    "retracted": StatusKind.RETRACTED,
    "removal": StatusKind.RETRACTED,
    "withdrawal": StatusKind.RETRACTED,
    "correction": StatusKind.CORRECTED,
    "corrigendum": StatusKind.CORRECTED,
    "erratum": StatusKind.CORRECTED,
    "partial_retraction": StatusKind.CORRECTED,
    "expression_of_concern": StatusKind.EXPRESSION_OF_CONCERN,
}
# new_version / new_edition / preprint updates are not editorial flags: skipped.


class CrossrefClient:
    def __init__(
        self,
        mailto: str | None = None,
        transport: httpx.BaseTransport | None = None,
        cache_dir: Path | None = Path("data/cache/crossref"),
        retry_base_seconds: float = 1.0,
    ) -> None:
        self.mailto = mailto or os.environ.get("CITEGUARD_MAILTO")
        self.cache_dir = cache_dir
        self.retry_base_seconds = retry_base_seconds
        self._client = httpx.Client(
            base_url=CROSSREF_BASE, transport=transport, timeout=30.0, follow_redirects=True
        )

    def get_updates_for(self, doi: str) -> list[dict[str, Any]]:
        """All notice works whose update-to targets `doi`."""
        normalized = normalize_doi(doi)
        if normalized is None:
            return []
        params: dict[str, str] = {"filter": f"updates:{normalized}", "rows": "20"}
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            payload = cached_json_get(
                self._client,
                "/works",
                params,
                self.cache_dir,
                retry_base_seconds=self.retry_base_seconds,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            raise
        items: list[dict[str, Any]] = (payload.get("message") or {}).get("items", [])
        return items


def _update_date(entry: dict[str, Any]) -> date | None:
    parts = ((entry.get("updated") or {}).get("date-parts") or [[]])[0]
    if len(parts) >= 3:
        return date(parts[0], parts[1], parts[2])
    if len(parts) == 1 and parts[0]:
        return date(parts[0], 1, 1)
    return None


def crossref_signals(notices: list[dict[str, Any]], target_doi: str) -> list[Signal]:
    """STRONG signals from notices' update-to entries matching the target."""
    target = normalize_doi(target_doi)
    signals: list[Signal] = []
    for notice in notices:
        notice_doi = normalize_doi(notice.get("DOI") or "")
        for entry in notice.get("update-to", []):
            if normalize_doi(entry.get("DOI") or "") != target:
                continue
            raw_type = (entry.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
            kind = _UPDATE_TYPE_MAP.get(raw_type)
            if kind is None:
                continue
            detail = f"Crossref update-to type: {raw_type}"
            if raw_type == "partial_retraction":
                detail += " (partial retraction reported conservatively as corrected)"
            signals.append(
                Signal(
                    source=Source.CROSSREF,
                    kind=kind,
                    strength=Strength.STRONG,
                    date=_update_date(entry),
                    notice_doi=notice_doi,
                    evidence_url=f"https://doi.org/{notice_doi}" if notice_doi else None,
                    detail=detail,
                )
            )
    return signals
