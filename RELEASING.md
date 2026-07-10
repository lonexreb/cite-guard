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
first upload; scope it to the `cite-guard` project afterwards, or use a Trusted
Publisher — see step 4).

```bash
uv build                                   # dist/cite_guard-0.1.0.{tar.gz,whl}
uv publish --token pypi-XXXX               # or: UV_PUBLISH_TOKEN=... uv publish
```

Verify: `uv tool install cite-guard && citeguard-mcp` should launch the server.

> Distribution name is `cite-guard` (the bare `citeguard` is taken on PyPI by an
> unrelated project). The importable module stays `citeguard`; the console command
> stays `citeguard-mcp`.

## 2. Tag a release + archive to Zenodo (gets the DOI)

1. Link the repo at https://zenodo.org/account/settings/github/ (flip CiteGuard on).
2. Cut a GitHub release — Zenodo mints a DOI automatically from the tag:

```bash
git tag -a v0.1.0 -m "CiteGuard 0.1.0 — MVP"
git push origin v0.1.0
gh release create v0.1.0 --title "CiteGuard 0.1.0" --notes "First public release: editorial-status model, MCP server, eval gate."
```

3. Add the DOI badge Zenodo gives you to the top of `README.md`.

## 3. List on the MCP registry

Verify the current `server.json` schema at https://registry.modelcontextprotocol.io
(the `$schema` URL and field names evolve), then publish with the official CLI:

```bash
# install mcp-publisher per the registry docs, authenticate via GitHub, then:
mcp-publisher publish
```

The registry validates that `server.json`'s PyPI package exists — do step 1 first.

## 4. (Optional) PyPI Trusted Publishing via GitHub Actions

Avoids storing a token: configure a Trusted Publisher on PyPI pointing at this repo +
a `release.yml` workflow using `pypa/gh-action-pypi-publish` on tag push. Add when you
want tagged releases to publish themselves.

## Version bumps

Bump `version` in **three** places, keep them in sync: `pyproject.toml`,
`server.json`, `CITATION.cff` (and `src/citeguard/__init__.py`).
