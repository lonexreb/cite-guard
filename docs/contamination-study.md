# Quantifying citation contamination with an open pipeline

Methodology scaffold for the CiteGuard evidence artifact — a short preprint measuring how
much a research corpus cites retracted, corrected, or otherwise-flagged work, using only
open data (Retraction Watch via Crossref, OpenAlex, Crossref). Fill the `TODO` numbers by
running `citeguard.scan`.

## Motivation

Retracted papers keep being cited long after the notice. Prior work (Feet of Clay /
Problematic Paper Screener) put the count in the hundreds of thousands, but those pipelines
leaned on proprietary citation databases. With the Retraction Watch dataset now open and the
OpenAlex citation graph CC0, the same measurement can be done — and reproduced — entirely in
the open. This study does that, and reports it conservatively: a citation is only counted as
"to a retracted work" when a documented editorial notice supports it (see the labeling rules
in `../CLAUDE.md` and `src/citeguard/status.py`).

## Method

1. **Flagged-work set.** Ingest the Retraction Watch dump (`retractionwatch.load_dump`) →
   ~62k DOIs with normalized editorial status.
2. **DOI → OpenAlex ID map.** Resolve the flagged DOIs to OpenAlex work IDs once
   (`watch.build_rw_id_map`, ~1,200 batched lookups, checkpointed). This is the only step
   with meaningful API cost; it is cached and reused.
3. **Corpus selection.** Choose a corpus by institution ROR (`scan.scan_institution`) or a
   DOI list. Fetch each work with its inline `referenced_works` (cheap OpenAlex list pages).
4. **Local join.** Intersect each work's `referenced_works` with the flagged-ID set
   (`scan.scan_works`). No per-reference API calls.
5. **Conservative resolution.** Each flagged reference is resolved through the same
   `status.resolve` logic used everywhere else — retraction vs. correction vs. expression of
   concern — so counts are broken down by editorial status, not lumped as "retracted."

### Metrics reported

- **Contamination rate** — share of works (with references) that cite ≥1 flagged paper.
- **Total flagged citations** and the **breakdown by editorial status**.
- **Most-cited flagged papers** in the corpus (the repeat offenders).
- **Worst-offending works** (most flagged references in a single bibliography).

## Reproduce it

```bash
# one-time: build the DOI -> OpenAlex ID map (needs OPENALEX_API_KEY + CITEGUARD_MAILTO)
uv run python -c "from pathlib import Path; from citeguard.resources import get_resources; \
from citeguard.watch import build_rw_id_map; r=get_resources(); \
build_rw_id_map(r.rw_index, r.oa_client)"

# scan a corpus
uv run python -m citeguard.scan --ror https://ror.org/013cjyk83 --since 2015-01-01 \
  --out report.json --markdown report.md
```

## Limitations (state them plainly)

- **Coverage floors, not ceilings.** OpenAlex may lack some references or DOIs; Retraction
  Watch does not cover every notice. Reported contamination is a **lower bound**.
- **DOI-keyed.** References without a resolvable DOI/OpenAlex ID are not checked.
- **Timing.** A work citing a paper *before* its retraction is still counted — the citation
  is contaminated regardless of intent; we do not infer authorial fault.
- **Conservative by construction.** Ambiguous cases are excluded from flagged counts, which
  pushes the estimate down, not up.

## Results

TODO — run the scan on the target corpus/corpora and paste `report.md` figures here:

- Corpus: TODO (institution / journal / field)
- Works scanned: TODO
- Contamination rate: TODO%
- Total flagged citations: TODO (retracted TODO / corrected TODO / EoC TODO)
- Most-cited flagged papers: TODO

## Artifacts

- Code + eval harness: this repository (MIT), archived at
  [10.5281/zenodo.21304655](https://doi.org/10.5281/zenodo.21304655).
- Scan outputs (`report.json` / `report.md`) should be committed alongside the write-up for
  reproducibility.
