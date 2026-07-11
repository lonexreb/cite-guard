# Releasing CiteGuard

The repo is build-ready (`uv build` produces a clean sdist + wheel). The steps below
need your accounts/tokens, so run them yourself — they are not automated.

## 0. Push to GitHub (once)

```bash
gh repo create lonexreb/cite-guard --public --source=. --remote=origin --push
# or, if the remote already exists:
git push -u origin main
```

CI (`.github/workflows/ci.yml`) runs ruff + mypy + pytest (incl. the eval gate) on push.

## 1. Publish to PyPI

Get a token at https://pypi.org/manage/account/token/ (an account-scoped token for the
first upload; scope it to the `retractguard` project afterwards, or use a Trusted
Publisher — see step 4).

```bash
uv build                                   # dist/retractguard-0.1.0.{tar.gz,whl}
uv publish --token pypi-XXXX               # or: UV_PUBLISH_TOKEN=... uv publish
```

Verify: `uv tool install retractguard && retractguard-mcp` should launch the server.

> Distribution name is `retractguard`. PyPI rejects both `citeguard` (taken by an
> unrelated project) and `cite-guard` (too similar to it). The importable module stays
> `citeguard`; the GitHub repo stays `cite-guard`; the console command is
> `retractguard-mcp`.

## 2. Tag a release + archive to Zenodo (gets the DOI)

1. Link the repo at https://zenodo.org/account/settings/github/ (flip CiteGuard on).
2. Cut a GitHub release — Zenodo mints a DOI automatically from the tag:

```bash
git tag -a v0.1.0 -m "CiteGuard 0.1.0 — MVP"
git push origin v0.1.0
gh release create v0.1.0 --title "CiteGuard 0.1.0" --notes "First public release: editorial-status model, MCP server, eval gate."
```

3. Add the DOI badge Zenodo gives you to the top of `README.md`.

## 3. Automated release → PyPI + MCP registry (no tokens)

`.github/workflows/release.yml` fires on a **published GitHub release** (or manual
`workflow_dispatch`) and does the whole chain over OIDC — no PyPI token, no interactive
GitHub login:

1. `uv build`
2. Publish to PyPI via **Trusted Publishing** (`pypa/gh-action-pypi-publish`)
3. Publish `server.json` to the **MCP registry** via `mcp-publisher login github-oidc`

The MCP registry proves you own the PyPI package by requiring
`mcp-name: io.github.lonexreb/retractguard` in the PyPI README (present in `README.md`),
which is why PyPI must publish *before* the registry step.

### One-time setup (required before the workflow can publish to PyPI)

Configure a **Trusted Publisher** at
https://pypi.org/manage/project/retractguard/settings/publishing/ (or, if the project
UI differs, the "pending publisher" form) with:

- **Owner:** `lonexreb`
- **Repository:** `cite-guard`
- **Workflow:** `release.yml`
- **Environment:** *(leave blank)*

Do **not** set a required environment on PyPI unless you also add `environment:` to the
workflow. After this one-time step, every release publishes itself.

> The MCP registry namespace `io.github.lonexreb/*` is authorized automatically by the
> workflow's GitHub OIDC identity — nothing to configure.

## 4. Cut a release

```bash
git tag -a v0.1.1 -m "..." && git push origin v0.1.1
gh release create v0.1.1 --title "..." --notes "..."
```

The `release.yml` workflow then publishes to PyPI and the MCP registry automatically.

## Version bumps

Bump `version` in **four** places, keep them in sync: `pyproject.toml`, `server.json`
(top-level **and** the package entry), `CITATION.cff`, and `src/citeguard/__init__.py`.
