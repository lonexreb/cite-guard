"""Institution watch: local-join screening of an institution's corpus.

The trick that keeps this inside the free tier: invert the RW dump into an
OpenAlex-ID set ONCE (~1,200 batched lookups, checkpointed/resumable), then
every watch run is cheap list pages + local set intersections. A 5k-works/yr
institution costs ~25 requests to backfill and ~1 per weekly run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from citeguard.checker import check_dois
from citeguard.crossref import CrossrefClient
from citeguard.openalex import BATCH_SIZE, OpenAlexClient
from citeguard.retractionwatch import RWIndex, rw_signals
from citeguard.status import EditorialStatus, Source, normalize_doi, resolve

ID_MAP_PATH = Path("data/rw_openalex_ids.json")
WATCH_STATE_DIR = Path("data/watch")


def build_rw_id_map(
    rw_index: RWIndex,
    oa_client: OpenAlexClient,
    path: Path = ID_MAP_PATH,
    max_requests: int | None = None,
) -> dict[str, str | None]:
    """RW DOI -> OpenAlex work ID (or None if OpenAlex doesn't know it).

    Checkpointed after every batch, so it resumes where it stopped and can be
    built over several days if credit math is tight (pass max_requests).
    """
    mapping: dict[str, str | None] = {}
    if path.exists():
        mapping = json.loads(path.read_text())
    todo = [d for d in rw_index if d not in mapping]
    for requests_made, i in enumerate(range(0, len(todo), BATCH_SIZE)):
        if max_requests is not None and requests_made >= max_requests:
            break
        batch = todo[i : i + BATCH_SIZE]
        found = oa_client.get_works_by_dois(batch)
        for doi in batch:
            work = found.get(doi)
            mapping[doi] = work["id"] if work else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mapping))
    return mapping


@dataclass(frozen=True, slots=True)
class CitedFlag:
    citing_work_id: str
    citing_doi: str | None
    citing_title: str | None
    flagged_reference: EditorialStatus


@dataclass(frozen=True, slots=True)
class WatchDigest:
    ror: str
    since: str | None
    works_scanned: int
    flagged_works: list[EditorialStatus]
    works_citing_flagged: list[CitedFlag]
    new_flag_keys: list[str]  # empty when everything was already reported
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ror": self.ror,
            "since": self.since,
            "works_scanned": self.works_scanned,
            "flagged_works": [s.to_dict() for s in self.flagged_works],
            "works_citing_flagged": [
                {
                    "citing_work_id": c.citing_work_id,
                    "citing_doi": c.citing_doi,
                    "citing_title": c.citing_title,
                    "flagged_reference": c.flagged_reference.to_dict(),
                }
                for c in self.works_citing_flagged
            ],
            "new_flag_keys": self.new_flag_keys,
            "notes": self.notes,
        }


def _state_path(ror: str, state_dir: Path) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", ror.lower()).strip("-")
    return state_dir / f"{slug}.json"


def watch_institution(
    ror: str,
    since: str | None,
    *,
    rw_index: RWIndex,
    oa_client: OpenAlexClient,
    cr_client: CrossrefClient | None = None,
    id_map_path: Path = ID_MAP_PATH,
    state_dir: Path = WATCH_STATE_DIR,
) -> WatchDigest:
    """Scan an institution's works; report flags not seen in previous runs."""
    notes: list[str] = []
    id_map: dict[str, str | None] = {}
    if id_map_path.exists():
        id_map = json.loads(id_map_path.read_text())
    else:
        notes.append(
            "Citation screening is off: the RW->OpenAlex ID map has not been "
            "built yet (run citeguard.watch.build_rw_id_map once; ~1,200 "
            "batched lookups, checkpointed)."
        )
    flagged_id_to_doi = {v: k for k, v in id_map.items() if v}

    works = list(oa_client.list_institution_works(ror, from_publication_date=since))

    direct_dois = []
    direct_works = {}
    for work in works:
        doi = normalize_doi(work.get("doi") or "")
        if doi and doi in rw_index:
            direct_dois.append(doi)
            direct_works[doi] = work
    flagged_works = (
        check_dois(
            direct_dois,
            rw_index=rw_index,
            oa_client=oa_client,
            cr_client=cr_client,
            prefetched_works=direct_works,
        )
        if direct_dois
        else []
    )

    citing: list[CitedFlag] = []
    if flagged_id_to_doi:
        for work in works:
            for ref_id in work.get("referenced_works") or []:
                ref_doi = flagged_id_to_doi.get(ref_id)
                if ref_doi is None:
                    continue
                # Local resolve from RW records only: zero extra API calls.
                ref_status = resolve(
                    ref_doi,
                    rw_signals(rw_index[ref_doi]),
                    frozenset({Source.RETRACTION_WATCH}),
                )
                citing.append(
                    CitedFlag(
                        citing_work_id=work.get("id") or "?",
                        citing_doi=normalize_doi(work.get("doi") or ""),
                        citing_title=work.get("title"),
                        flagged_reference=ref_status,
                    )
                )

    # only-new-flags semantics
    keys = [f"direct:{s.doi}:{s.kind.value}" for s in flagged_works] + [
        f"cites:{c.citing_work_id}->{c.flagged_reference.doi}" for c in citing
    ]
    state_file = _state_path(ror, state_dir)
    reported: set[str] = set()
    if state_file.exists():
        reported = set(json.loads(state_file.read_text()).get("reported", []))
    new_keys = [k for k in keys if k not in reported]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"reported": sorted(reported | set(keys))}))

    return WatchDigest(
        ror=ror,
        since=since,
        works_scanned=len(works),
        flagged_works=flagged_works,
        works_citing_flagged=citing,
        new_flag_keys=new_keys,
        notes=notes,
    )
