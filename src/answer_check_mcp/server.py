"""MCP tools that check an answer's figures, citations and obligations against its sources."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from legal_rag_verifier.premise import Premise
from legal_rag_verifier.verifier import Reason, SentenceVerdict, Verdict, Verifier
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

MAX_ANSWER_CHARS = 20_000
MAX_SOURCES = 50
MAX_SOURCE_CHARS = 200_000

CHECKED = (
    "The check covers numbers, money, percentages, dates and durations, legal citations and the "
    "names of Acts and other instruments, qualifiers such as 'at least', and obligation wording "
    "such as 'must' against 'may'. A sentence with none of these is 'unchecked', not verified."
)

INSTRUCTIONS = (
    "Call check_answer on a draft before sending it whenever the draft states figures, dates, "
    "citations or obligations taken from sources you were given. Rewrite or remove every "
    "'unsupported' sentence, using the source values in 'suggested' where they are offered, then "
    "check again. Never describe an 'unchecked' sentence as verified."
)

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


class Source(BaseModel):
    """One source document the answer must agree with."""

    text: str = Field(description="The source text. Paragraphs are separated by blank lines.")
    title: str | None = Field(
        default=None,
        description="The name of the instrument the text comes from, such as "
        "'Employment Rights Act 1996', so the answer may name it.",
    )
    citation: str | None = Field(
        default=None,
        description="The provision the text is, such as 's124', so the answer may cite it.",
    )


class SentenceCheck(BaseModel):
    text: str
    start: int = Field(description="Character offset of the sentence in the answer.")
    end: int
    status: Literal["supported", "unsupported", "unchecked"]
    reasons: list[str] = Field(description="Why the sentence failed, empty unless unsupported.")
    ungrounded: list[str] = Field(description="Claims in the sentence that no source supports.")
    suggested: list[str] = Field(
        description="Values from the sources that could replace the first ungrounded claim."
    )
    details: list[str]


class CheckReport(BaseModel):
    passed: bool = Field(description="True when no sentence is unsupported.")
    supported: int
    unsupported: int
    unchecked: int
    sentences: list[SentenceCheck]
    checked: str = Field(description="What the check covers, and what it does not.")


class CitationReport(BaseModel):
    status: str = Field(description="ROUTE_BOUNDED when the citation names real law in the index.")
    next_action: str = Field(description="What to do next, from the router's closed set.")
    coordinates: list[str] = Field(description="The provisions the citation resolves to.")
    excluded: list[str]
    corrections: list[list[str]] = Field(description="Typos fixed, as [as written, corrected].")
    suggestions: list[str] = Field(description="Close real titles offered with a refusal.")
    candidates: list[str] = Field(description="Options to show the user when it is ambiguous.")
    clarification: str | None
    repealed: bool
    messages: list[str]
    index_snapshot: str = Field(description="Date of the statute-book index the answer rests on.")


def _status(verdict: SentenceVerdict) -> Literal["supported", "unsupported", "unchecked"]:
    if verdict.verdict is Verdict.ROLLBACK:
        return "unsupported"
    if Reason.GROUNDED in verdict.reasons:
        return "supported"
    return "unchecked"


def _sentence(verdict: SentenceVerdict) -> SentenceCheck:
    status = _status(verdict)
    repair = verdict.repair
    return SentenceCheck(
        text=verdict.text,
        start=verdict.start,
        end=verdict.end,
        status=status,
        reasons=[r.value for r in verdict.reasons] if status == "unsupported" else [],
        ungrounded=verdict.ungrounded,
        suggested=list(repair.candidates) if repair and repair.mode == "allow" else [],
        details=list(verdict.details),
    )


def check(answer: str, sources: list[Source], question: str | None = None) -> CheckReport:
    """Check every sentence of ``answer`` against ``sources``."""
    if len(answer) > MAX_ANSWER_CHARS:
        raise ToolError(f"The answer is over {MAX_ANSWER_CHARS:,} characters.")
    if not sources:
        raise ToolError("Give at least one source. Without one, nothing can be supported.")
    if len(sources) > MAX_SOURCES:
        raise ToolError(f"Give at most {MAX_SOURCES} sources.")
    if sum(len(s.text) for s in sources) > MAX_SOURCE_CHARS:
        raise ToolError(f"The sources are over {MAX_SOURCE_CHARS:,} characters in total.")

    premise = Premise.from_text(
        "\n\n".join(s.text for s in sources),
        titles=[s.title for s in sources if s.title],
        citations=[s.citation for s in sources if s.citation],
    )
    sentences = [_sentence(v) for v in Verifier().check_text(premise, answer, query=question)]
    counts = {
        k: sum(s.status == k for s in sentences) for k in ("supported", "unsupported", "unchecked")
    }
    return CheckReport(
        passed=counts["unsupported"] == 0, sentences=sentences, checked=CHECKED, **counts
    )


def build_server(uk_index: Path | None = None) -> MCPServer:
    """The server. ``resolve_uk_citation`` is registered only when a UK index is given."""
    server = MCPServer("answer-check", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def check_answer(
        answer: str, sources: list[Source], question: str | None = None
    ) -> CheckReport:
        """Check each sentence of an answer against the sources it should rest on.

        Each sentence comes back 'supported', 'unsupported' (with the claims no source backs and,
        where possible, the source values to use instead) or 'unchecked'. Figures stated in the
        question count as supported. No model is called, and the same input always gives the
        same result.
        """
        return check(answer, sources, question)

    if uk_index is not None:
        from legal_rag_router import Router

        router = Router.from_path(uk_index)

        @server.tool(annotations=READ_ONLY)
        def resolve_uk_citation(citation: str) -> CitationReport:
            """Resolve a citation to UK legislation, such as 'section 124 of the Employment
            Rights Act 1996', against an index of the statute book.

            Real law resolves to its provision. Invented law is refused with close real titles,
            typos are corrected, and EU law is declared out of coverage. Use it before quoting
            or relying on any UK statute.
            """
            result = router.route(citation)
            return CitationReport(
                status=result.status.value,
                next_action=result.next_action.value,
                coordinates=[str(c) for c in result.coordinates],
                excluded=[str(c) for c in result.excluded],
                corrections=[list(pair) for pair in result.corrections],
                suggestions=[c.label for c in result.suggestions],
                candidates=[c.label for c in result.candidates],
                clarification=result.clarification,
                repealed=result.repealed,
                messages=list(result.messages),
                index_snapshot=result.index_snapshot,
            )

    return server
