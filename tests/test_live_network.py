"""Live smoke tests — excluded by default (pytest -m network to run).

These hit the real APIs with a polite mailto and the on-disk cache, so a
repeat run costs zero requests. They verify the production path the mocked
suite can't: auth/pool acceptance, response shapes, and the conservative
resolution against real editorial notices.
"""

import os
from pathlib import Path

import pytest

from citeguard.checker import check_dois
from citeguard.crossref import CrossrefClient
from citeguard.openalex import OpenAlexClient
from citeguard.retractionwatch import load_dump
from citeguard.status import StatusKind

pytestmark = pytest.mark.network

WAKEFIELD = "10.1016/s0140-6736(97)11096-0"
DUMP = Path("data/retraction_watch.csv")


@pytest.fixture(scope="module")
def oa() -> OpenAlexClient:
    return OpenAlexClient(mailto=os.environ.get("CITEGUARD_MAILTO", "ci@citeguard.example"))


@pytest.fixture(scope="module")
def cr() -> CrossrefClient:
    return CrossrefClient(mailto=os.environ.get("CITEGUARD_MAILTO", "ci@citeguard.example"))


def test_openalex_single_lookup(oa: OpenAlexClient) -> None:
    work = oa.get_work(WAKEFIELD)
    assert work is not None
    assert work["is_retracted"] is True  # OpenAlex agrees on this famous one


def test_crossref_notice_discovery(cr: CrossrefClient) -> None:
    notices = cr.get_updates_for(WAKEFIELD)
    assert notices, "Crossref should return the 2010 Lancet retraction notice"


@pytest.mark.skipif(not DUMP.exists(), reason="local RW dump not downloaded")
def test_full_stack_wakefield_resolves_retracted(oa: OpenAlexClient, cr: CrossrefClient) -> None:
    rw_index = load_dump(DUMP)
    (status,) = check_dois([WAKEFIELD], rw_index=rw_index, oa_client=oa, cr_client=cr)
    assert status.kind is StatusKind.RETRACTED
    assert status.confidence.value == "high"
    assert not status.conflict
    assert status.evidence_url  # documented notice, not a boolean
