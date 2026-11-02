"""resolve_uk_citation against the full legal-rag-router index.

Runs only where the index is present: set ANSWER_CHECK_UK_INDEX to its directory. The index is a
separate download from the legal-rag-router releases.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from answer_check_mcp import build_server

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.environ.get("ANSWER_CHECK_UK_INDEX"), reason="ANSWER_CHECK_UK_INDEX is not set"
    ),
]


async def resolve(citation: str) -> dict[str, Any]:
    server = build_server(Path(os.environ["ANSWER_CHECK_UK_INDEX"]))
    async with Client(server) as client:
        result = await client.call_tool("resolve_uk_citation", {"citation": citation})
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.parametrize(
    ("citation", "status", "coordinates", "corrections"),
    [
        (
            "section 124 of the Employment Rights Act 1996",
            "ROUTE_BOUNDED",
            ["uk/ukpga/1996/18/s124"],
            [],
        ),
        (
            "section 12 of the Employmnet Rights Act 1996",
            "ROUTE_BOUNDED",
            ["uk/ukpga/1996/18/s12"],
            [["employmnet", "employment"]],
        ),
        (
            "section 3 of the Digital Privacy Rights Act 2021",
            "EPISTEMIC_ABSTENTION_INSTRUMENT_NOT_FOUND",
            [],
            [],
        ),
        ("Article 6 of the GDPR", "ROUTE_OUT_OF_COVERAGE", [], []),
    ],
    ids=["real-law", "a-typo-is-corrected", "invented-law-is-refused", "eu-law-is-out-of-coverage"],
)
async def test_a_citation_resolves_to_real_law_or_says_why_not(
    citation: str, status: str, coordinates: list[str], corrections: list[list[str]]
) -> None:
    report = await resolve(citation)

    assert (report["status"], report["coordinates"], report["corrections"]) == (
        status,
        coordinates,
        corrections,
    )
    assert report["index_snapshot"]
