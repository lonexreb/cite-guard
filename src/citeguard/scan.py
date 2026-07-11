"""Corpus contamination scan — quantify how much a body of work cites flagged research.

This is the measurement engine behind the "citation contamination" evidence
artifact: point it at an institution (ROR) or a DOI list, and it reports how
many works cite retracted / corrected / expression-of-concern papers, which
flagged papers are cited most, and the worst-offending works.

The heavy join is local and free: it intersects each work's inline
`referenced_works` (OpenAlex IDs) with the flagged-ID set derived from the
RW->OpenAlex map (see citeguard.watch.build_rw_id_map). Only fetching the
institution's works costs API credits, and those are cheap list pages.

    uv run python -m citeguard.scan --ror https://ror.org/013cjyk83 --since 2015-01-01
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from citeguard.resources import get_resources
from citeguard.retractionwatch import RWIndex, rw_signals
from citeguard.status import Source, normalize_doi, resolve
from citeguard.watch import ID_MAP_PATH, load_reverse_flagged_map


@dataclass
class WorkContamination:
    work_id: str
    doi: str | None
    title: str | None
    flagged_refs: list[tuple[str, str]]  # (flagged_doi, kind)


@dataclass
class ContaminationReport:
    corpus: str
    works_scanned: int
    works_with_references: int
    works_with_flagged_refs: int
    total_flagged_citations: int
    by_kind: dict[str, int]
    most_cited_flagged: list[tuple[str, str, int]]  # (doi, kind, times_cited)
    worst_works: list[WorkContamination]
    notes: list[str] = field(default_factory=list)

    @property
    def contamination_rate(self) -> float:
        base = self.works_with_references or 1
        return self.works_with_flagged_refs / base

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "works_scanned": self.works_scanned,
            "works_with_references": self.works_with_references,
            "works_with_flagged_refs": self.works_with_flagged_refs,
            "contamination_rate": round(self.contamination_rate, 4),
            "total_flagged_citations": self.total_flagged_citations,
            "by_kind": self.by_kind,
            "most_cited_flagged": [
                {"doi": d, "kind": k, "times_cited": n} for d, k, n in self.most_cited_flagged
            ],
            "worst_works": [
                {
                    "work_id": w.work_id,
                    "doi": w.doi,
                    "title": w.title,
                    "flagged_reference_count": len(w.flagged_refs),
                    "flagged_references": [{"doi": d, "kind": k} for d, k in w.flagged_refs],
                }
                for w in self.worst_works
            ],
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Citation contamination scan — {self.corpus}",
            "",
            f"- Works scanned: **{self.works_scanned}** "
            f"({self.works_with_references} with references available)",
            f"- Works citing flagged research: **{self.works_with_flagged_refs}** "
            f"(**{self.contamination_rate:.1%}** of works with references)",
            f"- Total flagged citations: **{self.total_flagged_citations}**",
            "",
            "## By editorial status",
        ]
        for kind, n in sorted(self.by_kind.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {kind.replace('_', ' ')}: {n}")
        lines += ["", "## Most-cited flagged papers"]
        for doi, kind, n in self.most_cited_flagged:
            lines.append(f"- `{doi}` ({kind.replace('_', ' ')}) — cited by {n} work(s)")
        lines += ["", "## Worst-offending works"]
        for w in self.worst_works:
            title = (w.title or "")[:70]
            ref = w.doi or w.work_id
            lines.append(f"- `{ref}` — {len(w.flagged_refs)} flagged ref(s) — {title}")
        for note in self.notes:
            lines += ["", f"> {note}"]
        return "\n".join(lines) + "\n"


def scan_works(
    works: list[dict[str, Any]],
    rw_index: RWIndex,
    flagged_id_to_doi: dict[str, str],
    corpus: str,
    top_n: int = 20,
) -> ContaminationReport:
    """Local join: intersect each work's references with the flagged-ID set.

    Pure and offline — no network. `flagged_id_to_doi` maps OpenAlex work IDs
    (of flagged papers) to their DOIs; build it once via
    citeguard.watch.build_rw_id_map, then reverse it.
    """
    kind_cache: dict[str, str] = {}

    def kind_of(doi: str) -> str:
        if doi not in kind_cache:
            status = resolve(doi, rw_signals(rw_index[doi]), frozenset({Source.RETRACTION_WATCH}))
            kind_cache[doi] = status.kind.value
        return kind_cache[doi]

    contaminated: list[WorkContamination] = []
    with_refs = 0
    cited_counter: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    total = 0

    for work in works:
        refs = work.get("referenced_works") or []
        if refs:
            with_refs += 1
        flagged: list[tuple[str, str]] = []
        for ref_id in refs:
            flagged_doi = flagged_id_to_doi.get(ref_id)
            if flagged_doi is None or flagged_doi not in rw_index:
                continue
            k = kind_of(flagged_doi)
            flagged.append((flagged_doi, k))
            cited_counter[flagged_doi] += 1
            by_kind[k] += 1
            total += 1
        if flagged:
            contaminated.append(
                WorkContamination(
                    work_id=work.get("id") or "?",
                    doi=normalize_doi(work.get("doi") or ""),
                    title=work.get("title"),
                    flagged_refs=flagged,
                )
            )

    most_cited = [(doi, kind_of(doi), n) for doi, n in cited_counter.most_common(top_n)]
    worst = sorted(contaminated, key=lambda w: -len(w.flagged_refs))[:top_n]

    return ContaminationReport(
        corpus=corpus,
        works_scanned=len(works),
        works_with_references=with_refs,
        works_with_flagged_refs=len(contaminated),
        total_flagged_citations=total,
        by_kind=dict(by_kind),
        most_cited_flagged=most_cited,
        worst_works=worst,
    )


def scan_institution(
    ror: str,
    since: str | None = None,
    *,
    id_map_path: Path = ID_MAP_PATH,
    top_n: int = 20,
) -> ContaminationReport:
    """Fetch an institution's works (cheap list pages) and scan them locally."""
    r = get_resources()
    flagged_id_to_doi = load_reverse_flagged_map(id_map_path)
    notes: list[str] = []
    if not flagged_id_to_doi:
        notes.append(
            "The RW->OpenAlex ID map is empty or missing; citation scanning found "
            "nothing. Build it once with citeguard.watch.build_rw_id_map."
        )
    works = list(r.oa_client.list_institution_works(ror, from_publication_date=since))
    report = scan_works(works, r.rw_index, flagged_id_to_doi, corpus=ror, top_n=top_n)
    report.notes.extend(notes)
    return report


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Quantify citation contamination in a corpus.")
    p.add_argument("--ror", help="Institution ROR ID (e.g. https://ror.org/013cjyk83)")
    p.add_argument("--since", help="Only works published on/after this YYYY-MM-DD")
    p.add_argument("--out", type=Path, help="Write the JSON report here")
    p.add_argument("--markdown", type=Path, help="Write a markdown summary here")
    args = p.parse_args(argv)

    if not args.ror:
        p.error("provide --ror (DOI-list mode: import scan_works directly)")

    report = scan_institution(args.ror, args.since)
    if args.out:
        args.out.write_text(json.dumps(report.to_dict(), indent=2))
    if args.markdown:
        args.markdown.write_text(report.to_markdown())
    print(report.to_markdown())
    return 0


if __name__ == "__main__":
    sys.exit(_main())
