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
- **Citation timing** relative to the notice — the key distinction:
  - *pre-notice* (cited before the notice existed; blameless),
  - *concurrent* (within a configurable grace window while the notice propagates),
  - *post-notice* (cited well after the notice — the citations that should not happen).
  The headline figure is **post-notice citations**: citing a paper long after it was
  flagged is the measurable problem, and separating it from pre-notice citation is what
  keeps the study fair to authors.
- **Most-cited flagged papers** in the corpus (the repeat offenders).
- **Worst-offending works** (most flagged references in a single bibliography).

## Reproduce it

```bash
# one-time: build the DOI -> OpenAlex ID map (needs OPENALEX_API_KEY + CITEGUARD_MAILTO)
uv run python -c "from pathlib import Path; from citeguard.resources import get_resources; \
from citeguard.watch import build_rw_id_map; r=get_resources(); \
build_rw_id_map(r.rw_index, r.oa_client)"

# scan a corpus (grace-days sets the post-notice propagation window; default 365)
uv run python -m citeguard.scan --ror https://ror.org/013cjyk83 --since 2015-01-01 \
  --grace-days 365 --out report.json --markdown report.md
```

## Limitations (state them plainly)

- **Coverage floors, not ceilings.** OpenAlex may lack some references or DOIs; Retraction
  Watch does not cover every notice. Reported contamination is a **lower bound**.
- **DOI-keyed.** References without a resolvable DOI/OpenAlex ID are not checked.
- **Timing is scored, not assumed.** Each citation is classified pre-/concurrent/post-notice
  against the notice date, with a configurable grace window for propagation. We report the
  breakdown and never infer authorial fault — a pre-notice citation was blameless, and a
  post-notice one is a hygiene finding about the citing work, not an accusation.
- **Grace window is a judgement call.** The default 365-day propagation window is a
  defensible starting point, not a validated constant; report the value used and test
  sensitivity to it.
- **Conservative by construction.** Ambiguous cases are excluded from flagged counts, which
  pushes the estimate down, not up.

## Results — pilot across two universities, 2020–present

A pilot across two independent OpenAlex-adopting institutions. Raw outputs are committed
alongside this write-up (`study/*-2020.json` / `.md`); rerun with the command above to
reproduce. All works published 2020-01-01 onward; grace window 365 days.

| Institution | Works w/ refs | Contaminated works | Rate | Flagged citations | Post-notice |
|---|--:|--:|--:|--:|--:|
| Maastricht University (`02jz4aj89`) | 34,822 | 712 | **2.0%** | 798 | **402 (50%)** |
| Leiden University (`027bh9e22`) | 27,392 | 299 | **1.1%** | 342 | **145 (42%)** |

Editorial-status breakdown of flagged citations:

| Institution | Retracted | Expression of concern | Corrected | Reinstated |
|---|--:|--:|--:|--:|
| Maastricht | 522 | 119 | 107 | 50 |
| Leiden | 244 | 39 | 54 | 5 |

**The pattern holds across both sites.** Contamination sits in the low single-digit percent
(1–2% of works with references), retracted papers dominate the flagged citations, and
**roughly half of every flagged citation was made well after the editorial notice** — 50% at
Maastricht, 42% at Leiden. Pre-notice citations are reported separately and treated as
blameless; the post-notice count is the measurable problem, and it would be invisible to any
tool that checks only whether a cited paper is *currently* flagged, without asking *when* it
was cited.

**Conservative labeling, demonstrated on live data:** the Corman-Drosten COVID PCR paper
(`10.2807/1560-7917.es.2020.25.3.2000045`) is among the most-cited flagged papers at
Maastricht (27 citations) — and CiteGuard labels it *expression of concern*, **never
retracted**. This is the exact false positive a single-boolean tool produces; here it is
avoided on real data, not just in the test suite.

### Caveats

- Numbers are a **lower bound** (see Limitations): OpenAlex reference coverage is incomplete,
  and Retraction Watch does not carry every notice.
- Two institutions are a **pilot, not a survey.** Both are ordinary European research
  universities; a 1–2% rate should be read as a baseline, not an indictment of either. More
  institutions were queued for this run but OpenAlex's keyless *polite pool* rate-limited the
  batch after two full corpus scans plus the one-time 62k-DOI ID-map build — additional sites
  need an API key or a quota reset, not more retries.
- All figures describe citation *hygiene*, not author conduct. No individual work or author
  is being accused of anything.

## Artifacts

- Code + eval harness: this repository (MIT), archived at
  [10.5281/zenodo.21304655](https://doi.org/10.5281/zenodo.21304655).
- Scan outputs: [`study/maastricht-2020.md`](study/maastricht-2020.md) ·
  [`study/leiden-2020.md`](study/leiden-2020.md) (with `.json` alongside each).
