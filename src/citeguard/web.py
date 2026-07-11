"""Thin reference-list checker web UI (Starlette — already a dependency of mcp).

Intentionally minimal per CLAUDE.md ("don't add a heavyweight web framework
yet"): one page, two routes, no JS framework, no database. Reuses
citeguard.checker and the shared resources.

    uv run python -m citeguard.web        # http://127.0.0.1:8000
"""

from __future__ import annotations

import html

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from citeguard import checker
from citeguard.resources import Resources, get_resources
from citeguard.status import EditorialStatus

MAX_REFERENCES = 500  # keep a single request within the free API tier

_KIND_BADGE = {
    "retracted": ("Retracted", "#b3261e"),
    "corrected": ("Corrected", "#a15c00"),
    "expression_of_concern": ("Expression of concern", "#8a6d00"),
    "reinstated": ("Reinstated", "#2e7d32"),
    "hijacked_journal": ("Hijacked journal", "#6a1b9a"),
    "none": ("Clean", "#2e7d32"),
    "unknown": ("Unknown", "#5f6368"),
}

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CiteGuard — reference checker</title>
<style>
  :root {{ --fg:#1a1a1a; --muted:#5f6368; --line:#e0e0e0; --bg:#fafafa; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    max-width:820px; margin:0 auto; padding:2rem 1.25rem; color:var(--fg); background:#fff; }}
  h1 {{ margin:0 0 .25rem; font-size:1.7rem; }}
  p.sub {{ color:var(--muted); margin:0 0 1.5rem; }}
  textarea {{ width:100%; min-height:140px; font:14px/1.5 ui-monospace,Menlo,monospace;
    padding:.75rem; border:1px solid var(--line); border-radius:8px; resize:vertical; }}
  .row {{ display:flex; gap:.75rem; align-items:center; margin:.75rem 0 0; flex-wrap:wrap; }}
  button {{ background:#1a1a1a; color:#fff; border:0; border-radius:8px;
    padding:.6rem 1.2rem; font-size:.95rem; cursor:pointer; }}
  button:hover {{ background:#333; }}
  input[type=file] {{ font-size:.9rem; }}
  table {{ width:100%; border-collapse:collapse; margin-top:1.5rem; font-size:.92rem; }}
  th,td {{ text-align:left; padding:.55rem .5rem; border-bottom:1px solid var(--line);
    vertical-align:top; }}
  th {{ color:var(--muted); font-weight:600; font-size:.8rem; text-transform:uppercase;
    letter-spacing:.03em; }}
  .badge {{ display:inline-block; padding:.15rem .55rem; border-radius:999px;
    color:#fff; font-size:.78rem; font-weight:600; white-space:nowrap; }}
  .doi {{ font-family:ui-monospace,Menlo,monospace; font-size:.85rem; }}
  .note {{ color:var(--muted); font-size:.82rem; }}
  a {{ color:#1a5fb4; }}
  footer {{ margin-top:2.5rem; color:var(--muted); font-size:.8rem;
    border-top:1px solid var(--line); padding-top:1rem; }}
</style></head><body>
<h1>CiteGuard</h1>
<p class="sub">Paste DOIs (one per line) or upload a <code>.bib</code> file. Conservative by
design — a work is never called retracted without a documented editorial notice.</p>
<form method="post" action="/check" enctype="multipart/form-data">
  <textarea name="dois" placeholder="10.1016/S0140-6736(97)11096-0">{dois}</textarea>
  <div class="row">
    <button type="submit">Check references</button>
    <label class="note">or upload .bib: <input type="file" name="bibfile" accept=".bib"></label>
  </div>
</form>
{results}
<footer>Built on open data from Retraction Watch (via Crossref), OpenAlex, and Crossref.
MIT-licensed · <a href="https://github.com/lonexreb/cite-guard">source</a></footer>
</body></html>"""


def _badge(kind: str) -> str:
    label, color = _KIND_BADGE.get(kind, (kind, "#5f6368"))
    return f'<span class="badge" style="background:{color}">{html.escape(label)}</span>'


def _row(ref: str | None, status: EditorialStatus) -> str:
    doi = html.escape(status.doi)
    link = (
        f'<a class="doi" href="{html.escape(status.evidence_url)}">{doi}</a>'
        if status.evidence_url
        else f'<span class="doi">{doi}</span>'
    )
    note = html.escape(status.notes[0]) if status.notes else ""
    conf = status.confidence.value
    label = f"{html.escape(ref)} " if ref and ref != status.doi else ""
    return (
        f"<tr><td>{label}{link}</td><td>{_badge(status.kind.value)}</td>"
        f"<td>{conf}</td><td class='note'>{note}</td></tr>"
    )


def _results_table(rows: list[tuple[str | None, EditorialStatus]]) -> str:
    if not rows:
        return ""
    flagged = sum(1 for _, s in rows if s.kind.value not in ("none", "unknown"))
    body = "".join(_row(ref, s) for ref, s in rows)
    summary = f"{len(rows)} reference(s) checked · {flagged} flagged"
    return (
        f"<p class='sub' style='margin-top:1.5rem'>{summary}</p>"
        "<table><thead><tr><th>Reference</th><th>Status</th>"
        "<th>Confidence</th><th>Note</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


async def index(_: Request) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(dois="", results=""))


def _check_inputs(
    r: Resources, dois_text: str, bib_text: str
) -> list[tuple[str | None, EditorialStatus]]:
    if bib_text.strip():
        results = checker.check_bibtex(
            bib_text, rw_index=r.rw_index, oa_client=r.oa_client,
            cr_client=r.cr_client, hijacked=r.hijacked,
        )
        return [(x.ref, x.status) for x in results[:MAX_REFERENCES]]
    dois = [ln.strip() for ln in dois_text.splitlines() if ln.strip()][:MAX_REFERENCES]
    statuses = checker.check_dois(
        dois, rw_index=r.rw_index, oa_client=r.oa_client,
        cr_client=r.cr_client, hijacked=r.hijacked,
    )
    return list(zip(dois, statuses, strict=True))


async def check(request: Request) -> HTMLResponse | JSONResponse:
    form = await request.form()
    dois_text = str(form.get("dois") or "")
    bib_text = ""
    upload = form.get("bibfile")
    if upload is not None and hasattr(upload, "read"):
        bib_text = (await upload.read()).decode("utf-8", errors="replace")

    r = get_resources()
    rows = _check_inputs(r, dois_text, bib_text)

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            {"references": [{"ref": ref, **s.to_dict()} for ref, s in rows]}
        )
    return HTMLResponse(_PAGE.format(dois=html.escape(dois_text), results=_results_table(rows)))


def build_app() -> Starlette:
    return Starlette(routes=[Route("/", index), Route("/check", check, methods=["POST"])])


app = build_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
