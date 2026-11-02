"""check_answer as an agent calls it: through an MCP client, reading the structured result."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from answer_check_mcp import build_server

pytestmark = pytest.mark.anyio

PLAN = {
    "text": "The Pro plan costs $20 a month and includes 5 seats.\n\n"
    "Customers must request a refund within 30 days of purchase."
}
STATUTE = {
    "text": "The amount of a compensatory award shall not exceed the lower of £123,543 and 52 "
    "multiplied by a week's pay of the person concerned.",
    "title": "Employment Rights Act 1996",
    "citation": "s124",
}


async def check(answer: str, sources: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    async with Client(build_server()) as client:
        result = await client.call_tool(
            "check_answer", {"answer": answer, "sources": sources, **extra}
        )
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def test_only_check_answer_is_listed_without_an_index_and_it_is_read_only() -> None:
    async with Client(build_server()) as client:
        (tool,) = (await client.list_tools()).tools

    assert tool.name == "check_answer"
    assert tool.annotations is not None
    assert (tool.annotations.read_only_hint, tool.annotations.destructive_hint) == (True, False)


@pytest.mark.parametrize(
    ("answer", "source", "status", "reasons", "ungrounded", "suggested"),
    [
        (
            "The Pro plan costs $25 a month.",
            PLAN,
            "unsupported",
            ["UNGROUNDED_FIGURE"],
            ["$25"],
            ["$20"],
        ),
        ("It includes 5 seats.", PLAN, "supported", [], [], []),
        ("Support is friendly and fast.", PLAN, "unchecked", [], [], []),
        (
            "Customers may request a refund within 30 days.",
            PLAN,
            "unsupported",
            ["DEONTIC_SHIFT"],
            [],
            ["must", "shall"],
        ),
        (
            "Under section 124 of the Employment Rights Act 1996, the award cannot exceed the "
            "lower of £123,543 and 52 weeks' pay.",
            STATUTE,
            "supported",
            [],
            [],
            [],
        ),
        (
            "Under section 124 of the Employment Rights Act 1996, the award cannot exceed "
            "£123,543.",
            STATUTE,
            "unsupported",
            ["QUALIFIER_DROPPED"],
            [],
            [],
        ),
        (
            "Under section 125 of the Employment Rights Act 1996, the award cannot exceed the "
            "lower of £123,543 and 52 weeks' pay.",
            STATUTE,
            "unsupported",
            ["UNGROUNDED_CITATION"],
            ["section 125"],
            [],
        ),
        (
            "Under the Equality Act 2010, the award cannot exceed the lower of £123,543 and 52 "
            "weeks' pay.",
            STATUTE,
            "unsupported",
            ["UNGROUNDED_INSTRUMENT"],
            ["Equality Act 2010"],
            ["Employment Rights Act 1996"],
        ),
    ],
    ids=[
        "a-wrong-price-names-the-source-price",
        "a-figure-in-the-source",
        "prose-with-nothing-to-check-is-not-called-verified",
        "may-where-the-source-says-must",
        "a-correct-citation-with-its-qualifier",
        "a-cap-without-the-lower-of-qualifier",
        "a-section-the-source-does-not-cite",
        "an-act-the-sources-do-not-name",
    ],
)
async def test_each_sentence_gets_a_status_and_what_to_fix(
    answer: str,
    source: dict[str, Any],
    status: str,
    reasons: list[str],
    ungrounded: list[str],
    suggested: list[str],
) -> None:
    (sentence,) = (await check(answer, [source]))["sentences"]

    assert (sentence["status"], sentence["reasons"]) == (status, reasons)
    assert (sentence["ungrounded"], sentence["suggested"]) == (ungrounded, suggested)


async def test_an_answer_passes_only_when_no_sentence_is_unsupported() -> None:
    good = await check("It includes 5 seats. Support is friendly.", [PLAN])
    bad = await check("It includes 5 seats. The Pro plan costs $25 a month.", [PLAN])

    assert (good["passed"], good["supported"], good["unchecked"]) == (True, 1, 1)
    assert (bad["passed"], bad["unsupported"]) == (False, 1)


async def test_a_figure_the_user_gave_in_the_question_counts_as_supported() -> None:
    answer = "Your weekly pay of £700 is used."
    alone = await check(answer, [STATUTE])
    asked = await check(answer, [STATUTE], question="My week's pay is £700. What is the cap?")

    assert (alone["passed"], asked["passed"]) == (False, True)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"answer": "It includes 5 seats.", "sources": []}, "Give at least one source"),
        ({"answer": "x" * 20_001, "sources": [PLAN]}, "The answer is over 20,000 characters"),
        ({"answer": "x", "sources": [PLAN] * 51}, "Give at most 50 sources"),
    ],
    ids=["no-sources", "answer-too-long", "too-many-sources"],
)
async def test_bad_input_is_an_error_the_agent_can_read(
    arguments: dict[str, Any], message: str
) -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("check_answer", arguments)

    assert result.is_error
    assert message in result.content[0].text  # type: ignore[union-attr]
