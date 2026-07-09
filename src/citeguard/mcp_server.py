"""MCP server exposing CiteGuard's three tools.

Run locally:  uv run python -m citeguard.mcp_server
Env: OPENALEX_API_KEY (required for live lookups), CITEGUARD_MAILTO,
     CITEGUARD_DATA_DIR (default ./data).

Tools return JSON dicts built from EditorialStatus.to_dict(); labeling is
conservative by design (see status.resolve).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from citeguard import checker, watch
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

app = FastMCP(
    "citeguard",
    instructions=(
        "CiteGuard flags references that are retracted, corrected, or subject "
        "to an expression of concern, reconciling Retraction Watch, OpenAlex, "
        "and Crossref conservatively. A 'retracted' claim always carries a "
        "documented editorial notice; ambiguous works are reported as "
        "'unknown', never over-claimed."
    ),
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
    """Lazy init; first call downloads the RW dump (~65MB, free) if absent."""
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


@app.tool()
def get_editorial_status(doi: str) -> dict[str, Any]:
    """Editorial status of one work (retracted / corrected / expression of
    concern / reinstated / hijacked journal / none / unknown), with source,
    evidence URL, date, confidence, and any source conflicts."""
    r = get_resources()
    (status,) = checker.check_dois(
        [doi],
        rw_index=r.rw_index,
        oa_client=r.oa_client,
        cr_client=r.cr_client,
        hijacked=r.hijacked,
    )
    return status.to_dict()


@app.tool()
def check_references(
    dois: list[str] | None = None,
    bibtex: str | None = None,
    paper_doi: str | None = None,
) -> dict[str, Any]:
    """Check a reference list. Provide exactly one of: `dois` (list of DOIs),
    `bibtex` (a .bib file's text), or `paper_doi` (a paper's DOI — its cited
    references are fetched from OpenAlex and checked)."""
    r = get_resources()
    provided = [x for x in (dois, bibtex, paper_doi) if x]
    if len(provided) != 1:
        return {"error": "provide exactly one of: dois, bibtex, paper_doi"}

    if dois is not None:
        statuses = checker.check_dois(
            dois, rw_index=r.rw_index, oa_client=r.oa_client,
            cr_client=r.cr_client, hijacked=r.hijacked,
        )
        return {"references": [s.to_dict() for s in statuses]}
    if bibtex is not None:
        results = checker.check_bibtex(
            bibtex, rw_index=r.rw_index, oa_client=r.oa_client,
            cr_client=r.cr_client, hijacked=r.hijacked,
        )
        return {"references": [{"ref": x.ref, **x.status.to_dict()} for x in results]}
    assert paper_doi is not None
    report = checker.check_paper(
        paper_doi, rw_index=r.rw_index, oa_client=r.oa_client,
        cr_client=r.cr_client, hijacked=r.hijacked,
    )
    if report is None:
        return {"error": f"DOI not found in OpenAlex: {paper_doi}"}
    return {
        "paper": report.paper.to_dict(),
        "references": [{"ref": x.ref, **x.status.to_dict()} for x in report.references],
        "references_without_doi": report.references_without_doi,
    }


@app.tool()
def watch_institution(ror: str, since: str | None = None) -> dict[str, Any]:
    """Scan an institution's works (by ROR ID, e.g. https://ror.org/02y3ad647)
    for papers that are flagged or that cite flagged papers. Repeat calls
    report only NEW flags (state kept locally). `since` is an optional
    YYYY-MM-DD publication-date floor — set it for large institutions."""
    r = get_resources()
    digest = watch.watch_institution(
        ror,
        since,
        rw_index=r.rw_index,
        oa_client=r.oa_client,
        cr_client=r.cr_client,
        id_map_path=r.data_dir / "rw_openalex_ids.json",
        state_dir=r.data_dir / "watch",
    )
    return digest.to_dict()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
