"""The normalized editorial-status model and conservative resolution logic.

Pure module: no I/O, no network. Source modules (retractionwatch, openalex,
crossref) produce ``Signal``s; ``resolve()`` reconciles them.

The invariant that must never break: RETRACTED is only ever emitted when at
least one STRONG (documented-notice) signal says retracted. OpenAlex's
``is_retracted`` boolean alone yields UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class StatusKind(StrEnum):
    RETRACTED = "retracted"
    CORRECTED = "corrected"
    EXPRESSION_OF_CONCERN = "expression_of_concern"
    REINSTATED = "reinstated"
    HIJACKED_JOURNAL = "hijacked_journal"
    NONE = "none"
    UNKNOWN = "unknown"


class Source(StrEnum):
    RETRACTION_WATCH = "retraction_watch"
    OPENALEX = "openalex"
    CROSSREF = "crossref"


ALL_SOURCES = frozenset(Source)


class Strength(StrEnum):
    STRONG = "strong"  # documented editorial notice (RW record, Crossref update-to)
    WEAK = "weak"  # derived boolean (OpenAlex is_retracted)


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# For merging disagreeing strong sources: pick the more severe claim and flag it.
_SEVERITY: dict[StatusKind, int] = {
    StatusKind.RETRACTED: 5,
    StatusKind.EXPRESSION_OF_CONCERN: 4,
    StatusKind.CORRECTED: 3,
    StatusKind.REINSTATED: 2,
    StatusKind.HIJACKED_JOURNAL: 1,
    StatusKind.NONE: 0,
    StatusKind.UNKNOWN: 0,
}

_FP_GUARD_NOTE = (
    "OpenAlex marks this work retracted, but no documented editorial notice was "
    "found in Retraction Watch or Crossref. OpenAlex's boolean has produced false "
    "positives in the past; treat as unverified."
)


@dataclass(frozen=True, slots=True)
class Signal:
    """What one source, alone, implies about one work."""

    source: Source
    kind: StatusKind
    strength: Strength
    date: date | None = None
    notice_doi: str | None = None
    evidence_url: str | None = None
    detail: str = ""
    confidence_hint: Confidence | None = None  # e.g. hijacked ISSN vs title-only match


@dataclass(frozen=True, slots=True)
class EditorialStatus:
    doi: str
    kind: StatusKind
    confidence: Confidence
    date: date | None
    evidence_url: str | None
    signals: tuple[Signal, ...]
    notes: tuple[str, ...]
    conflict: bool
    sources_checked: frozenset[Source] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (dates -> ISO strings, sets -> sorted lists)."""
        return {
            "doi": self.doi,
            "kind": self.kind.value,
            "confidence": self.confidence.value,
            "date": self.date.isoformat() if self.date else None,
            "evidence_url": self.evidence_url,
            "conflict": self.conflict,
            "notes": list(self.notes),
            "sources_checked": sorted(s.value for s in self.sources_checked),
            "signals": [
                {
                    "source": s.source.value,
                    "kind": s.kind.value,
                    "strength": s.strength.value,
                    "date": s.date.isoformat() if s.date else None,
                    "notice_doi": s.notice_doi,
                    "evidence_url": s.evidence_url,
                    "detail": s.detail,
                }
                for s in self.signals
            ],
        }


def normalize_doi(raw: str) -> str | None:
    """Lowercase, strip resolver prefixes; None if it doesn't look like a DOI."""
    doi = raw.strip().lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi.org/",
        "doi:",
    ):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip()
    if not doi.startswith("10.") or "/" not in doi:
        return None
    return doi


def _collapse_rw_timeline(
    rw: list[Signal],
) -> tuple[StatusKind | None, Signal | None, list[str]]:
    """R1: run the RW records, date-sorted, through a small state machine.

    Returns (collapsed kind, the signal that determined it, notes).
    """
    if not rw:
        return None, None, []
    # Undated records sort last so they cannot silently override a dated timeline.
    ordered = sorted(rw, key=lambda s: (s.date is None, s.date or date.min))
    state: StatusKind | None = None
    determining: Signal | None = None
    notes: list[str] = []
    for sig in ordered:
        if sig.kind is StatusKind.RETRACTED:
            if state is StatusKind.EXPRESSION_OF_CONCERN:
                notes.append(
                    "Escalated: an expression of concern preceded the retraction."
                )
            state, determining = StatusKind.RETRACTED, sig
        elif sig.kind is StatusKind.REINSTATED:
            if state is StatusKind.RETRACTED and determining is not None:
                notes.append(
                    f"Previously retracted on {determining.date or 'unknown date'}; "
                    f"reinstated on {sig.date or 'unknown date'}."
                )
            state, determining = StatusKind.REINSTATED, sig
        elif sig.kind is StatusKind.EXPRESSION_OF_CONCERN:
            if state is not StatusKind.RETRACTED:
                state, determining = StatusKind.EXPRESSION_OF_CONCERN, sig
        elif sig.kind is StatusKind.CORRECTED:
            if state not in (StatusKind.RETRACTED, StatusKind.EXPRESSION_OF_CONCERN):
                state, determining = StatusKind.CORRECTED, sig
    if any(s.date is None for s in ordered) and len(ordered) > 1:
        notes.append(
            "One or more Retraction Watch records lack a parseable date; "
            "timeline ordering is best-effort."
        )
    return state, determining, notes


def _pick_strong(
    rw_kind: StatusKind | None,
    rw_sig: Signal | None,
    cr: list[Signal],
) -> tuple[StatusKind | None, Signal | None, Confidence, bool, list[str]]:
    """R2: merge collapsed RW with Crossref update-to signals."""
    cr_sig = max(cr, key=lambda s: _SEVERITY[s.kind], default=None)
    cr_kind = cr_sig.kind if cr_sig else None

    if rw_kind is None and cr_kind is None:
        return None, None, Confidence.HIGH, False, []
    if rw_kind is None:
        return cr_kind, cr_sig, Confidence.HIGH, False, []
    if cr_kind is None:
        return rw_kind, rw_sig, Confidence.HIGH, False, []
    if rw_kind is cr_kind:
        return rw_kind, rw_sig or cr_sig, Confidence.HIGH, False, []
    # Reinstatement is the one legitimate downgrade: RW tracks the fuller
    # timeline, while Crossref keeps pointing at the historical notice.
    if rw_kind is StatusKind.REINSTATED:
        return (
            StatusKind.REINSTATED,
            rw_sig,
            Confidence.MEDIUM,
            False,
            [
                f"Crossref still records a {cr_kind.value.replace('_', ' ')} notice; "
                "Retraction Watch documents a later reinstatement."
            ],
        )
    # Genuine disagreement: take the more severe claim, flag the conflict.
    severe_kind, severe_sig = max(
        [(rw_kind, rw_sig), (cr_kind, cr_sig)], key=lambda p: _SEVERITY[p[0]]
    )
    return (
        severe_kind,
        severe_sig,
        Confidence.MEDIUM,
        True,
        [
            f"Sources disagree: Retraction Watch indicates "
            f"{rw_kind.value.replace('_', ' ')}, Crossref indicates "
            f"{cr_kind.value.replace('_', ' ')}. Reporting the more severe status."
        ],
    )


def resolve(
    doi: str,
    signals: list[Signal],
    sources_checked: frozenset[Source],
    extra_notes: tuple[str, ...] = (),
) -> EditorialStatus:
    """Conservatively reconcile all signals for one work."""
    notes: list[str] = list(extra_notes)

    rw = [
        s
        for s in signals
        if s.source is Source.RETRACTION_WATCH and s.kind is not StatusKind.HIJACKED_JOURNAL
    ]
    hijacked = [s for s in signals if s.kind is StatusKind.HIJACKED_JOURNAL]
    crossref = [s for s in signals if s.source is Source.CROSSREF and s.strength is Strength.STRONG]
    oa_retracted = any(
        s.source is Source.OPENALEX and s.kind is StatusKind.RETRACTED for s in signals
    )

    rw_kind, rw_sig, rw_notes = _collapse_rw_timeline(rw)
    notes.extend(rw_notes)
    kind, determining, confidence, conflict, merge_notes = _pick_strong(rw_kind, rw_sig, crossref)
    notes.extend(merge_notes)

    if kind is not None:
        # R4: a documented notice wins; OpenAlex lag is telemetry, not a conflict.
        if kind is StatusKind.RETRACTED and not oa_retracted:
            notes.append("OpenAlex does not (yet) flag this work as retracted.")
    elif oa_retracted:
        # R3: the false-positive guard.
        kind, confidence = StatusKind.UNKNOWN, Confidence.LOW
        notes.append(_FP_GUARD_NOTE)
    elif hijacked:
        # R5: venue-level flag applies only when the article itself is clean.
        h = hijacked[0]
        kind = StatusKind.HIJACKED_JOURNAL
        confidence = h.confidence_hint or Confidence.MEDIUM
        determining = h
        notes.append(
            "This flag concerns the journal (hijacked/cloned venue), not the "
            "conduct of the article's authors."
        )
    else:
        # R6: distinguish "checked and clean" from "didn't look".
        strong_sources = {Source.RETRACTION_WATCH, Source.CROSSREF}
        if strong_sources <= sources_checked:
            kind, confidence = StatusKind.NONE, Confidence.HIGH
        elif strong_sources & sources_checked:
            kind, confidence = StatusKind.NONE, Confidence.MEDIUM
            missing = ", ".join(sorted(s.value for s in strong_sources - sources_checked))
            notes.append(f"Not all editorial-notice sources were checked (missing: {missing}).")
        else:
            kind, confidence = StatusKind.UNKNOWN, Confidence.LOW
            notes.append("No editorial-notice source (Retraction Watch, Crossref) was checked.")

    # Hijacked venue noted even when an article-level status outranks it (R5).
    if hijacked and kind is not StatusKind.HIJACKED_JOURNAL:
        notes.append("Additionally, the publication venue appears on a hijacked-journal list.")

    # The invariant (R3): never claim RETRACTED without a documented notice.
    if kind is StatusKind.RETRACTED:
        assert any(
            s.strength is Strength.STRONG and s.kind is StatusKind.RETRACTED for s in signals
        ), "invariant violated: RETRACTED emitted without a strong retraction signal"

    return EditorialStatus(
        doi=doi,
        kind=kind,
        confidence=confidence,
        date=determining.date if determining else None,
        evidence_url=(determining.evidence_url or determining.notice_doi)
        if determining
        else None,
        signals=tuple(signals),
        notes=tuple(notes),
        conflict=conflict,
        sources_checked=sources_checked,
    )
