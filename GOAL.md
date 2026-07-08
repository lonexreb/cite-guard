# GOAL.md — CiteGuard

The "why." This file states the mission, who it serves, what success looks like, and the
evidence plan. `README.md` is the public-facing doc; `CLAUDE.md` is the build guide; this
is the north star. When a decision is unclear, it should be resolved in favor of the goals
below, in priority order.

## Mission

Give the open-science community a **free, open, OpenAlex-native way to catch citations of
retracted, corrected, or otherwise flagged research** — with the nuance that existing tools
either paywall (scite), gate behind proprietary citation databases (RetractoBot used
Scopus), or cannot express at all (OpenAlex's single `is_retracted` boolean).

## Priorities (in order)

1. **Genuine open-science public good.** CC0 ethos, reproducible, well-documented, free.
2. **Extraordinary-ability (O-1A) evidence.** Original contribution of major significance,
   with a path to press coverage, institutional adoption, and expert letters.
3. **Serve the OpenAlex community specifically** — librarians, bibliometricians, research
   offices, integrity officers, and developers.

These do not conflict often. When they do, the higher one wins.

## The problem, precisely

- Retracted and problematic papers keep getting cited long after the notice. Prior work
  (Feet of Clay / Problematic Paper Screener) found **hundreds of thousands of articles
  citing retracted works**, thousands with five or more retracted references.
- OpenAlex consolidates editorial status into a single boolean `is_retracted`, which has
  produced **false positives** (documented ~2,300-work misclassification in early 2024,
  incl. a widely-used COVID PCR paper) and cannot distinguish retraction from correction
  or expression of concern.
- There is **no free, open, alerting service** that watches a reference list, an author, or
  an institution's corpus for newly-flagged citations. RetractoBot was an RCT built on
  Scopus, not an open product; scite is proprietary and paywalled.

Now that the **Retraction Watch dataset is open (via Crossref)** and the **OpenAlex
citation graph is CC0**, a fully open version of this tool is possible for the first time.

## Target users

Primary (choose these for adoption + letters):
- **Research-integrity officers** and **journal editors** — need to screen submissions and
  monitor their corpus.
- **Academic librarians** at OpenAlex-adopting institutions (a fast-growing group:
  Sorbonne dropped Web of Science; Maastricht is dropping Scopus in 2027; France funds
  OpenAlex; 100+ Barcelona Declaration signatories).
- **Systematic reviewers** — a single retracted included study can invalidate a review.

Secondary:
- **Developers / meta-scientists** using the MCP server inside LLM agents.
- **Individual authors** checking their own bibliographies before submission.

## What we are building (scope)

One core, two surfaces:
- **Core:** a normalized editorial-status model + resolution logic over OpenAlex +
  Retraction Watch + Crossref.
- **Surface 1 (primary):** an **evals-backed MCP server** — `check_references`,
  `get_editorial_status`, `watch_institution`.
- **Surface 2:** a **reference-list checker** — DOI / `.bib` in, per-reference status out,
  with a thin web UI.

Explicitly **out of scope for the MVP:** general literature discovery, full-text search,
author disambiguation (OpenAlex is rewriting this), and anything requiring the full ~300GB
snapshot at query time.

## Success criteria

**Technical (MVP is "done" when):**
- The editorial-status model distinguishes retraction / correction / expression of concern
  / hijacked-journal / reinstated / none / unknown, with source + evidence + confidence.
- The checker accepts a DOI and a `.bib` file and returns correct statuses.
- The MCP server exposes all three tools and passes functional tests.
- The eval harness reports **precision/recall on a published gold set**, and precision on
  "retracted" claims is high (false positives are the cardinal sin).
- It runs within the free API tier for a realistic single-institution watch.

**Adoption (the 6–12 month signals that matter):**
- GitHub stars/forks; PyPI/npm downloads; MCP-registry listings; dependent repos.
- Named institutional adopters (libraries / research offices / journals) with testimonials.
- References checked; institutions watched.

**Recognition:**
- Coverage in the scholarly-comms press that reliably covers this beat (Retraction Watch,
  The Scholarly Kitchen, Nature Index, Times Higher Education, Chemistry World).
- An endorsement or working-group role in the OpenAlex community.

## O-1 evidence checklist (collect from day one)

- **Adoption metrics** — screenshot star/download growth over time; log references checked
  and institutions watched.
- **Named adopters** — record every institution that uses it; request short testimonials
  early, letters later.
- **Press** — pitch the beat outlets above; archive every mention.
- **Expert letters (line up early)** — research-integrity / open-science figures associated
  with Retraction Watch/Crossref, the Bennett Institute (RetractoBot), the Problematic
  Paper Screener, CWTS/Leiden, and OpenAlex-adopting libraries.
- **Judging / critical-role evidence** — maintainership; reviewing PRs/issues; OpenAlex
  community working-group participation; talks (code4lib, FORCE11, OASPA, PIDapalooza).
- **Original-contribution artifacts** — the published eval methodology; a short preprint
  quantifying citation contamination found via the open pipeline; a Zenodo DOI for the repo.
- Keep an **evidence matrix** mapping each artifact to a specific O-1A criterion, with
  consistent dates/metrics across exhibits.

## Precedent (why this pattern earns press + adoption)

- **RetractoBot** — Nature Index + Retraction Watch coverage; RCT at the Peer Review
  Congress; explicitly limited by having to license Scopus. Our opening: do it openly.
- **Feet of Clay / Problematic Paper Screener** — Times Higher Education + The Conversation
  coverage; quantified >764,000 articles citing retracted works.
- **scite** — funded, awarded, and acquired by Research Solutions (NASDAQ: RSSS) for a
  ~$14.8M enterprise value (~$3.6M ARR, ~21,000 subscribers). Proprietary — leaves the
  open lane empty.

## Risks & how we hold them

- **OpenAlex ships a richer editorial-status field** → pivot emphasis to the reference-list
  + evals + alerting angle (still novel); keep MCP as the interface to unique logic.
- **MCP is low-moat** (six community servers already exist; none evals-backed) → the eval
  harness + integrity use case are the differentiator, not the wrapper.
- **Integrity tooling carries defamation/accuracy risk** → conservative labeling; corroborate
  before flagging; mark `UNKNOWN` rather than guess.
- **Free-tier credits are tight** → ID-first lookups; free snapshot for bulk; live API only
  for incremental checks. Pricing is new and "will likely change" — re-verify before scaling.
- **Retraction Watch access/licensing could shift** → verify current terms before building
  ingestion; attribute properly.

## The single sentence

*The free, open, OpenAlex-native watchdog that tells you — and keeps telling you — when your
references, your authors, or your institution's papers cite research the community has flagged.*
