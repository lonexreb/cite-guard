# CLAUDE.md — CiteGuard

Guidance for Claude Code when working in this repository.

## What this project is

CiteGuard is an **open, OpenAlex-native citation-integrity layer** for the open-science
community. It flags references that are **retracted, corrected, or subject to an
expression of concern** — the nuance OpenAlex's single `is_retracted` boolean cannot
express — and surfaces this to librarians, research-integrity officers, systematic
reviewers, and authors.

It ships as two surfaces over one core:
1. **An evals-backed MCP server** — the primary deliverable. Tools: `check_references`,
   `get_editorial_status`, `watch_institution`.
2. **A reference-list checker** — paste a DOI / upload a `.bib` → per-reference status.

The differentiator vs. prior art (RetractoBot, scite, Feet of Clay) is that this is
**free, fully open, OpenAlex-native, and evals-backed**. RetractoBot could not build
this openly because no open citation database existed at the time; OpenAlex now fills
that gap.

## Non-negotiable design constraints

- **Free-tier-aware by default.** OpenAlex API keys are mandatory (since Feb 13, 2026).
  Free tier ≈ $1/day. `/works?search=` costs 10× a single-record lookup. **Architect
  around cheap ID-based lookups**, not bulk search. Use the free monthly snapshot subset
  for anything bulk; use the live API only for incremental/targeted checks.
- **Conservative labeling.** A false "retracted" flag harms real authors — this is the
  exact bug OpenAlex shipped. Never over-claim. Distinguish retraction vs. correction vs.
  expression of concern vs. hijacked-journal. When status is ambiguous, say so.
- **Evals are a first-class deliverable, not an afterthought.** Every core capability
  needs a gold-set test with reported precision/recall. The eval harness IS the moat.
- **CC0 / open ethos.** Attribute Retraction Watch (via Crossref) and OpenAlex. Keep the
  project reproducible and well-documented (README, architecture docs, Zenodo DOI).

## Data sources

- **OpenAlex API** — works, authors, institutions, citation graph. Requires API key
  (env `OPENALEX_API_KEY`), plus a polite-pool `mailto`.
- **Retraction Watch dataset** — now open via Crossref. Ingest the dump; it carries the
  `update-nature` nuance (retraction / correction / expression of concern) that we
  normalize into our own editorial-status model.
- **Crossref REST API** — DOI normalization and cross-checking.

## Repository layout

```
src/citeguard/
  __init__.py
  openalex.py      # thin OpenAlex client: keyed, rate-aware, ID-lookup-first
  retractionwatch.py  # ingest + normalize the RW dump -> editorial-status model
  status.py        # the normalized EditorialStatus model + resolution logic
  checker.py       # reference-list checker (DOI / .bib -> statuses)
  mcp_server.py    # MCP server exposing check_references / get_editorial_status / watch_institution
tests/             # pytest unit + functional tests
evals/             # gold sets + eval harness (precision/recall reporting)
data/              # local RW dump + cached lookups (gitignored)
```

## Conventions

- **Python 3.11+**, managed with `uv`. Deps in `pyproject.toml`.
- **Type hints everywhere**; run `mypy`. Format/lint with `ruff`.
- **No secrets in code.** Read `OPENALEX_API_KEY` and `CITEGUARD_MAILTO` from env.
- **Every network call is cached** locally during dev to conserve credits.
- **Small, testable functions.** Core logic must be unit-testable without network
  (mock the clients; keep pure functions pure).

## Commands

```bash
uv sync                      # install deps
uv run pytest                # unit + functional tests
uv run python -m evals.run   # run the eval harness, print precision/recall
uv run ruff check .          # lint
uv run mypy src              # type-check
uv run python -m citeguard.mcp_server   # launch the MCP server locally
```

## The editorial-status model (core abstraction)

`status.py` defines `EditorialStatus` — richer than a boolean:
- `RETRACTED`, `CORRECTED`, `EXPRESSION_OF_CONCERN`, `REINSTATED`, `HIJACKED_JOURNAL`,
  `NONE`, `UNKNOWN`.
- Each status carries: source (RW / OpenAlex / Crossref), evidence URL, date, and a
  confidence note. Resolution logic reconciles disagreements between sources
  **conservatively** (prefer the documented editorial notice; flag conflicts rather
  than silently picking one).

## What NOT to do

- Don't hammer `/works?search=`. Resolve to IDs first, then look up by ID.
- Don't hard-delete or over-write cached data during dev without asking.
- Don't add a heavyweight web framework yet — MCP server + a thin checker first.
- Don't claim a work is retracted on a single weak signal; require corroboration or
  mark `UNKNOWN`.

## Current milestone

MVP slice, in order:
1. `status.py` — the normalized model (foundation).
2. `retractionwatch.py` — ingest + normalize the RW dump.
3. `openalex.py` — keyed, ID-first client.
4. `checker.py` — DOI / `.bib` → statuses.
5. `mcp_server.py` — expose the three tools.
6. `evals/` — gold set + precision/recall harness (in parallel from step 2 on).
