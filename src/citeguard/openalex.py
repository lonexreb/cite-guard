"""Thin OpenAlex client: keyed, rate-aware, ID-lookup-first.

Credit discipline (free tier ~ $1/day; search costs ~10x a record lookup):
- never calls /works?search=
- batches DOI lookups via filter=doi:a|b|c (50 per request)
- caches every response on disk
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx

from citeguard._http import cached_json_get, is_cached
from citeguard.status import Signal, Source, StatusKind, Strength, normalize_doi

OPENALEX_BASE = "https://api.openalex.org"
BATCH_SIZE = 50  # OpenAlex max values per filter
WORK_SELECT = (
    "id,doi,title,publication_date,is_retracted,is_paratext,referenced_works,primary_location"
)


class OpenAlexClient:
    def __init__(
        self,
        api_key: str | None = None,
        mailto: str | None = None,
        transport: httpx.BaseTransport | None = None,
        cache_dir: Path | None = Path("data/cache/openalex"),
        retry_base_seconds: float = 1.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY")
        self.mailto = mailto or os.environ.get("CITEGUARD_MAILTO")
        self.cache_dir = cache_dir
        self.retry_base_seconds = retry_base_seconds
        self._client = httpx.Client(
            base_url=OPENALEX_BASE,
            transport=transport,
            timeout=30.0,
            follow_redirects=True,
        )

    def _params(self, **extra: str) -> dict[str, str]:
        params = dict(extra)
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        return params

    def _get(self, path: str, **params: str) -> dict[str, Any]:
        return cached_json_get(
            self._client,
            path,
            self._params(**params),
            self.cache_dir,
            retry_base_seconds=self.retry_base_seconds,
        )

    def _is_cached(self, path: str, **params: str) -> bool:
        return is_cached(path, self._params(**params), self.cache_dir)

    def get_work(self, id_or_doi: str) -> dict[str, Any] | None:
        """Single-record lookup by OpenAlex ID or DOI. None on 404."""
        doi = normalize_doi(id_or_doi)
        ident = f"https://doi.org/{doi}" if doi else id_or_doi
        try:
            return self._get(f"/works/{ident}", select=WORK_SELECT)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def get_works_by_dois(self, dois: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Batched lookup: normalized DOI -> work. Missing DOIs are absent.

        DOIs containing filter metacharacters (',' joins clauses, '|' joins
        values) cannot ride in a batch; they fall back to single lookups.
        """
        normalized = [d for d in (normalize_doi(x) for x in dois) if d]
        safe = [d for d in normalized if "," not in d and "|" not in d]
        unsafe = [d for d in normalized if d not in safe]

        found: dict[str, dict[str, Any]] = {}
        for i in range(0, len(safe), BATCH_SIZE):
            batch = safe[i : i + BATCH_SIZE]
            page = self._get(
                "/works",
                filter="doi:" + "|".join(batch),
                select=WORK_SELECT,
                **{"per-page": str(BATCH_SIZE)},
            )
            for work in page.get("results", []):
                doi = normalize_doi(work.get("doi") or "")
                if doi:
                    found[doi] = work
        for doi in unsafe:
            work = self.get_work(doi)
            if work:
                found[doi] = work
        return found

    def get_works_by_ids(self, openalex_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Batched lookup by OpenAlex work ID (W...): full ID URL -> work."""
        found: dict[str, dict[str, Any]] = {}
        short = [i.rsplit("/", 1)[-1] for i in openalex_ids]
        for i in range(0, len(short), BATCH_SIZE):
            batch = short[i : i + BATCH_SIZE]
            page = self._get(
                "/works",
                filter="ids.openalex:" + "|".join(batch),
                select=WORK_SELECT,
                **{"per-page": str(BATCH_SIZE)},
            )
            for work in page.get("results", []):
                if work.get("id"):
                    found[work["id"]] = work
        return found

    def list_institution_works(
        self,
        ror: str,
        from_publication_date: str | None = None,
        page_delay_seconds: float = 0.0,
    ) -> Iterator[dict[str, Any]]:
        """Cursor-paginated works for an institution (cheap list pages).

        page_delay_seconds throttles between uncached pages to stay polite on
        large corpora; cached pages are not delayed.
        """
        filters = [f"authorships.institutions.ror:{ror}"]
        if from_publication_date:
            filters.append(f"from_publication_date:{from_publication_date}")
        cursor = "*"
        while cursor:
            was_cached = self._is_cached(
                "/works",
                filter=",".join(filters),
                select=WORK_SELECT,
                cursor=cursor,
                **{"per-page": "200"},
            )
            page = self._get(
                "/works",
                filter=",".join(filters),
                select=WORK_SELECT,
                cursor=cursor,
                **{"per-page": "200"},
            )
            yield from page.get("results", [])
            cursor = (page.get("meta") or {}).get("next_cursor") or ""
            if cursor and page_delay_seconds and not was_cached:
                time.sleep(page_delay_seconds)


def openalex_signal(work: dict[str, Any]) -> Signal | None:
    """WEAK signal — the boolean, never trusted alone (see resolve() R3)."""
    if not work.get("is_retracted"):
        return None
    return Signal(
        source=Source.OPENALEX,
        kind=StatusKind.RETRACTED,
        strength=Strength.WEAK,
        evidence_url=work.get("id"),
        detail="OpenAlex is_retracted=true",
    )


def paratext_note(work: dict[str, Any]) -> str | None:
    if work.get("is_paratext"):
        return "OpenAlex marks this as paratext (likely an editorial/front-matter item)."
    return None
