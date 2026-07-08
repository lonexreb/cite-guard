"""Reference-list checker: DOIs / .bib / a paper's DOI -> editorial statuses.

The RW index is a local join (free); OpenAlex is one batched call per ~50
DOIs; Crossref is free and always consulted so a clean result means
"checked everywhere", not "didn't look" (see resolve() R6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from citeguard.crossref import CrossrefClient, crossref_signals
from citeguard.openalex import OpenAlexClient, openalex_signal, paratext_note
from citeguard.retractionwatch import HijackedIndex, RWIndex, hijacked_signal, rw_signals
from citeguard.status import EditorialStatus, Signal, Source, normalize_doi, resolve

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>}{,]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    ref: str  # how the caller identified it: bib key, raw DOI, or OpenAlex ID
    status: EditorialStatus


def extract_dois_from_bib(text: str) -> list[tuple[str, str | None]]:
    """(bib entry key, normalized DOI or None). DOI field first, URL fallback."""
    import bibtexparser

    entries = bibtexparser.loads(text).entries
    out: list[tuple[str, str | None]] = []
    for entry in entries:
        key = entry.get("ID", "?")
        doi = normalize_doi(entry.get("doi", ""))
        if doi is None:
            match = _DOI_RE.search(entry.get("url", ""))
            doi = normalize_doi(match.group(0)) if match else None
        out.append((key, doi))
    return out


def _venue(work: dict[str, Any]) -> tuple[str | None, str | None]:
    source = (work.get("primary_location") or {}).get("source") or {}
    issns = source.get("issn") or []
    return source.get("display_name"), issns[0] if issns else None


def check_dois(
    dois: list[str],
    *,
    rw_index: RWIndex,
    oa_client: OpenAlexClient | None = None,
    cr_client: CrossrefClient | None = None,
    hijacked: HijackedIndex | None = None,
    prefetched_works: dict[str, dict[str, Any]] | None = None,
) -> list[EditorialStatus]:
    """Resolve each DOI against all available sources. Order preserved."""
    normalized = [normalize_doi(d) for d in dois]
    valid = [d for d in normalized if d]

    works: dict[str, dict[str, Any]] = dict(prefetched_works or {})
    if oa_client is not None:
        missing = [d for d in valid if d not in works]
        if missing:
            works.update(oa_client.get_works_by_dois(missing))

    results: list[EditorialStatus] = []
    for raw, doi in zip(dois, normalized, strict=True):
        if doi is None:
            results.append(
                resolve(raw, [], frozenset(), extra_notes=("Not a recognizable DOI.",))
            )
            continue
        signals: list[Signal] = []
        checked: set[Source] = {Source.RETRACTION_WATCH}
        notes: list[str] = []

        signals.extend(rw_signals(rw_index.get(doi, [])))

        work = works.get(doi)
        if oa_client is not None or work is not None:
            checked.add(Source.OPENALEX)
        if work is not None:
            if sig := openalex_signal(work):
                signals.append(sig)
            if note := paratext_note(work):
                notes.append(note)
            if hijacked is not None:
                journal, issn = _venue(work)
                if hsig := hijacked_signal(journal, issn, hijacked):
                    signals.append(hsig)

        if cr_client is not None:
            signals.extend(crossref_signals(cr_client.get_updates_for(doi), doi))
            checked.add(Source.CROSSREF)

        results.append(resolve(doi, signals, frozenset(checked), extra_notes=tuple(notes)))
    return results


def check_bibtex(
    text: str,
    *,
    rw_index: RWIndex,
    oa_client: OpenAlexClient | None = None,
    cr_client: CrossrefClient | None = None,
    hijacked: HijackedIndex | None = None,
) -> list[ReferenceResult]:
    """Per-entry statuses for a .bib file; entries without a DOI come back UNKNOWN."""
    keyed = extract_dois_from_bib(text)
    statuses = check_dois(
        [doi if doi else f"(no doi: {key})" for key, doi in keyed],
        rw_index=rw_index,
        oa_client=oa_client,
        cr_client=cr_client,
        hijacked=hijacked,
    )
    return [ReferenceResult(ref=key, status=s) for (key, _), s in zip(keyed, statuses, strict=True)]


@dataclass(frozen=True, slots=True)
class PaperReport:
    doi: str
    paper: EditorialStatus
    references: list[ReferenceResult]
    references_without_doi: int


def check_paper(
    doi: str,
    *,
    rw_index: RWIndex,
    oa_client: OpenAlexClient,
    cr_client: CrossrefClient | None = None,
    hijacked: HijackedIndex | None = None,
) -> PaperReport | None:
    """The 'paste a DOI' mode: check the paper AND everything it cites.

    Costs: 1 lookup for the paper + ceil(refs/50) batched lookups.
    """
    work = oa_client.get_work(doi)
    if work is None:
        return None
    (paper_status,) = check_dois(
        [doi], rw_index=rw_index, oa_client=oa_client, cr_client=cr_client,
        hijacked=hijacked, prefetched_works={normalize_doi(doi) or doi: work},
    )
    ref_ids: list[str] = work.get("referenced_works") or []
    ref_works = oa_client.get_works_by_ids(ref_ids) if ref_ids else {}

    with_doi: list[tuple[str, str, dict[str, Any]]] = []  # (openalex id, doi, work)
    no_doi = 0
    for rid in ref_ids:
        rwork = ref_works.get(rid)
        rdoi = normalize_doi((rwork or {}).get("doi") or "")
        if rwork is not None and rdoi:
            with_doi.append((rid, rdoi, rwork))
        else:
            no_doi += 1

    statuses = check_dois(
        [rdoi for _, rdoi, _ in with_doi],
        rw_index=rw_index,
        oa_client=oa_client,
        cr_client=cr_client,
        hijacked=hijacked,
        prefetched_works={rdoi: rwork for _, rdoi, rwork in with_doi},
    )
    refs = [
        ReferenceResult(ref=rid, status=s)
        for (rid, _, _), s in zip(with_doi, statuses, strict=True)
    ]
    return PaperReport(
        doi=normalize_doi(doi) or doi,
        paper=paper_status,
        references=refs,
        references_without_doi=no_doi,
    )
