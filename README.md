# CiteGuard

[![PyPI](https://img.shields.io/pypi/v/retractguard)](https://pypi.org/project/retractguard/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21304655.svg)](https://doi.org/10.5281/zenodo.21304655)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**The free, open, OpenAlex-native watchdog for retracted and problematic citations.**

CiteGuard tells you — and keeps telling you — when your references, your authors, or your
institution's papers cite research the community has flagged as **retracted, corrected, or
subject to an expression of concern**.

It exists because the existing options each fall short: scite is proprietary and paywalled,
RetractoBot had to license Scopus (no open citation database existed at the time), and
OpenAlex collapses all editorial status into a single `is_retracted` boolean that can't tell
a retraction from a correction — and has produced false positives in the past.

Now that the **Retraction Watch dataset is open** (via Crossref) and the **OpenAlex citation
graph is CC0**, CiteGuard can do this fully in the open, for free.

> Status: **early development.** Building the MVP. See `GOAL.md` for the mission and
> `CLAUDE.md` for the build guide.

## What it does

- **Check a reference list.** Paste a DOI or upload a `.bib` file → get a per-reference
  status: retracted, corrected, expression of concern, hijacked-journal, or clean.
- **Nuanced status, not a boolean.** Every flag carries its source (Retraction Watch /
  OpenAlex / Crossref), an evidence link, a date, and a confidence note. When sources
  disagree, CiteGuard surfaces the conflict instead of silently guessing.
- **Watch an institution.** Point it at a ROR ID → get a digest when any of that
  institution's works cites (or becomes) a newly-flagged paper.
- **Use it from an AI agent.** An **MCP server** exposes the same logic as tools
  (`check_references`, `get_editorial_status`, `watch_institution`) for Claude, Cursor, and
  any MCP-compatible client.

## Why it's trustworthy

Integrity tooling can do real harm if it's wrong — a false "retracted" flag damages a real
author. CiteGuard is **conservative by design**: it corroborates before flagging, prefers
the documented editorial notice, and marks a work `UNKNOWN` rather than guess. Every core
capability ships with a **published eval** reporting precision and recall on a gold set.

## Who it's for

- Research-integrity officers and journal editors screening submissions
- Academic librarians at OpenAlex-adopting institutions
- Systematic reviewers (one retracted included study can invalidate a review)
- Developers and meta-scientists building on the MCP server
- Authors checking their own bibliography before submission

## Architecture

One core, two surfaces.

```
                 ┌─────────────────────────────┐
   OpenAlex ─────▶                             │
   (CC0 graph)   │   editorial-status model    │──▶  MCP server
                 │   + resolution logic        │      (check_references,
   Retraction ──▶│   (conservative)            │       get_editorial_status,
   Watch (open)  │                             │       watch_institution)
                 │                             │──▶  reference-list checker
   Crossref ─────▶                             │      (DOI / .bib → statuses,
   (DOI norm.)   └─────────────────────────────┘       thin web UI)
```

Repository layout:

```
src/citeguard/
  openalex.py         # keyed, rate-aware, ID-lookup-first OpenAlex client
  retractionwatch.py  # ingest + normalize the Retraction Watch dump
  status.py           # the EditorialStatus model + resolution logic (core)
  checker.py          # reference-list checker (DOI / .bib -> statuses)
  mcp_server.py       # MCP server exposing the three tools
tests/                # pytest unit + functional tests
evals/                # gold sets + precision/recall harness
data/                 # local RW dump + cached lookups (gitignored)
```

## Design constraints (important)

- **Free-tier-aware.** OpenAlex API keys are required (since Feb 13, 2026); the free tier is
  small and search costs ~10× a record lookup. CiteGuard resolves to IDs first and looks up
  by ID; bulk work uses the free monthly snapshot, and the live API is reserved for
  incremental checks.
- **Open and reproducible.** CC0 ethos, with proper attribution to Retraction Watch and
  OpenAlex, thorough docs, and a Zenodo DOI.

## Getting started (dev)

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
uv sync                                   # install dependencies
export OPENALEX_API_KEY=...               # your OpenAlex key
export CITEGUARD_MAILTO=you@example.org   # polite-pool contact

uv run pytest                             # run tests
uv run python -m evals.run                # run the eval harness (precision/recall)
uv run python -m citeguard.mcp_server     # launch the MCP server locally
```

<!-- mcp-name: io.github.lonexreb/retractguard -->

## Connect it as an MCP server

CiteGuard exposes `get_editorial_status`, `check_references`, and `watch_institution`
to any MCP client. After `pip install retractguard` (or `uv tool install retractguard`),
the `retractguard-mcp` command launches the stdio server.

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "retractguard": {
      "command": "retractguard-mcp",
      "env": {
        "OPENALEX_API_KEY": "your-key",
        "CITEGUARD_MAILTO": "you@example.org"
      }
    }
  }
}
```

**Cursor / other clients** — point them at the same `retractguard-mcp` command (stdio
transport). Running from a checkout instead of an install? Use
`"command": "uv", "args": ["run", "retractguard-mcp"]` with `"cwd"` set to the repo.

On first call the server downloads the Retraction Watch dump (~65 MB, free) into
`CITEGUARD_DATA_DIR` (default `./data`). Editorial-notice lookups (Retraction Watch,
Crossref) need no key; OpenAlex corroboration and `watch_institution` do.

## The web checker

A thin web UI for people who don't live in an editor — paste DOIs or drop a `.bib` file,
get a per-reference status table.

```bash
retractguard-web            # then open http://127.0.0.1:8000
# or from a checkout: uv run python -m citeguard.web
```

Add `Accept: application/json` to `POST /check` to get the results as JSON instead of a
table. It reuses the same conservative resolution logic as the MCP server — no separate
code path, no separate trust model.

## Roadmap (MVP)

1. `status.py` — the normalized editorial-status model (foundation)
2. `retractionwatch.py` — ingest + normalize the Retraction Watch dump
3. `openalex.py` — keyed, ID-first client
4. `checker.py` — DOI / `.bib` → statuses
5. `mcp_server.py` — expose the three tools
6. `evals/` — gold set + precision/recall harness (running from step 2 onward)

## Credits & data

- **OpenAlex** — CC0 scholarly metadata and citation graph.
- **Retraction Watch** — retraction database, made openly available via **Crossref**.
- **Crossref** — DOI infrastructure.

CiteGuard is independent and not affiliated with these projects; it builds on their open data
with gratitude.

## License

**MIT** (see `LICENSE`) — permissive and maximally reusable, in keeping with the
open-science ethos in `GOAL.md`.

The code is CiteGuard's. The **data it builds on is not** and carries its own terms:
Retraction Watch (via Crossref) and OpenAlex/Crossref metadata. CiteGuard redistributes
only a tiny evaluation extract (see `evals/fixtures/ATTRIBUTION.md`); anything at scale
should be fetched from the upstream sources under their licenses.
