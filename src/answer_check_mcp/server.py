"""MCP tools that check an answer's figures, citations and obligations against its sources."""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, replace
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, cast

from legal_rag_verifier.index import build_index
from legal_rag_verifier.judge import SHORT_SHA, STRICT_FIGURES, Judge, JudgedVerifier, OpenAIChat
from legal_rag_verifier.premise import Premise
from legal_rag_verifier.segmenter import split_sentences
from legal_rag_verifier.verifier import NLIProbs, Reason, SentenceVerdict, Verdict, Verifier
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from answer_check_mcp.presets import DEFAULT_PRESET, PRESETS

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

JUDGE_INSTRUCTIONS = (
    INSTRUCTIONS
    + " A sentence the judge marked supported is only as good as the judge's measured accuracy, "
    "given in the report's 'checked' text."
)

JUDGE_CHECK_DESCRIPTION = """Check each sentence of an answer against the sources it should rest on.

Each sentence comes back 'supported', 'unsupported' (with the claims no source backs and,
where possible, the source values to use instead) or 'unchecked'. Figures stated in the
question count as supported. An LLM judge on the configured endpoint also reads each
sentence, so the answer and the sources leave this machine."""

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
JUDGE_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


@dataclass(frozen=True)
class JudgeSettings:
    url: str
    model: str | None = None
    preset: str | None = None
    api_key_env: str | None = None
    timeout: float = 30.0
    max_calls: int = 40

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise ValueError("judge url must start with http:// or https://")
        if self.model is not None and self.preset is not None:
            raise ValueError("judge model and judge preset are mutually exclusive")
        if self.model is None and self.preset is None:
            object.__setattr__(self, "preset", DEFAULT_PRESET)
        if self.preset is not None and self.preset not in PRESETS:
            choices = ", ".join(sorted(PRESETS))
            raise ValueError(f"unknown judge preset {self.preset!r}; choose one of: {choices}")
        if self.timeout <= 0:
            raise ValueError("judge timeout must be greater than 0")
        if self.max_calls < 1:
            raise ValueError("judge max calls must be at least 1")


class JudgeUnavailable(Exception):
    """The judge endpoint failed the start probe."""


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
    checked_by: Literal["claims", "judge"] = Field(
        default="claims", description="Whether claims checks or the LLM judge decided the sentence."
    )
    judge_label: str | None = Field(
        default=None, description="The judge label counted for this sentence, when it was judged."
    )
    judge_passage: str | None = Field(
        default=None, description="The source passage the judge used for this sentence, when known."
    )


class JudgeInfo(BaseModel):
    model: str = Field(description="The judge model and revision used for this report.")
    preset: str | None = Field(description="The measured preset key, or null for a custom model.")
    measured: bool = Field(description="True when the judge is one of the measured presets.")
    prompt_sha256: str = Field(description="SHA-256 of the judge prompt template.")
    calls: int = Field(description="How many judge calls were recorded.")
    failed_calls: int = Field(description="How many judge calls failed after retrying.")


class CheckReport(BaseModel):
    passed: bool = Field(description="True when no sentence is unsupported.")
    supported: int
    unsupported: int
    unchecked: int
    sentences: list[SentenceCheck]
    checked: str = Field(description="What the check covers, and what it does not.")
    judge: JudgeInfo | None = Field(
        default=None, description="Judge details, present in judge mode."
    )


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turn redirects into HTTP errors instead of following them."""

    def redirect_request(  # noqa: PLR0917 - urllib's signature
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        fp.close()
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, io.BytesIO())


def _status(verdict: SentenceVerdict) -> Literal["supported", "unsupported", "unchecked"]:
    if verdict.verdict is Verdict.ROLLBACK:
        return "unsupported"
    if Reason.GROUNDED in verdict.reasons:
        return "supported"
    return "unchecked"


def _sentence(
    verdict: SentenceVerdict,
    *,
    checked_by: Literal["claims", "judge"] = "claims",
    judge_label: str | None = None,
    judge_passage: str | None = None,
    cap_detail: str | None = None,
    premise: Premise | None = None,
    question: str | None = None,
) -> SentenceCheck:
    status = _status(verdict)
    repair = verdict.repair
    ungrounded = verdict.ungrounded
    suggested = list(repair.candidates) if repair and repair.mode == "allow" else []
    if checked_by == "judge" and status == "unsupported" and premise is not None:
        claims = Verifier().check_sentence(premise, verdict.text, query=question)
        claims_repair = claims.repair
        if (
            Reason.UNGROUNDED_FIGURE in claims.reasons
            and claims_repair is not None
            and claims_repair.mode == "allow"
        ):
            suggested = list(claims_repair.candidates)
            if not ungrounded:
                ungrounded = claims.ungrounded
    details = list(verdict.details)
    if cap_detail is not None:
        details.append(cap_detail)
    return SentenceCheck(
        text=verdict.text,
        start=verdict.start,
        end=verdict.end,
        status=status,
        reasons=[r.value for r in verdict.reasons] if status == "unsupported" else [],
        ungrounded=ungrounded,
        suggested=suggested,
        details=details,
        checked_by=checked_by,
        judge_label=judge_label,
        judge_passage=judge_passage,
    )


def _authorization(api_key_env: str | None) -> tuple[str | None, str | None]:
    if not api_key_env:
        return None, None
    key = os.environ.get(api_key_env, "").strip()
    if not key:
        return None, None
    if not (key.isprintable() and all(c <= "\xff" for c in key)):
        raise ValueError(f"{api_key_env} holds an invalid header value") from None
    return key, f"Bearer {key}"


def _expected_model(settings: JudgeSettings) -> str:
    if settings.preset is not None:
        return PRESETS[settings.preset].model
    assert settings.model is not None  # noqa: S101 - JudgeSettings validates this.
    return settings.model


def _probe(settings: JudgeSettings) -> None:
    endpoint = f"{settings.url.rstrip('/')}/v1/models"
    try:
        headers = {}
        key, authorization = _authorization(settings.api_key_env)
        if authorization is not None:
            headers["Authorization"] = authorization
        request = urllib.request.Request(  # noqa: S310 - the caller's endpoint
            endpoint, method="GET", headers=headers
        )
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=settings.timeout) as response:
            payload = json.loads(response.read())
        data = payload["data"]
        if not isinstance(data, list):
            raise TypeError("data is not a list")
        ids = []
        for item in data:
            if not isinstance(item, dict):
                raise TypeError("model is not an object")
            ids.append(str(item["id"]))
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        exc.close()
        raise JudgeUnavailable(f"judge endpoint {settings.url} unreachable: {detail}") from None
    except urllib.error.URLError as exc:
        detail = str(exc.reason) if exc.reason else type(exc).__name__
        raise JudgeUnavailable(f"judge endpoint {settings.url} unreachable: {detail}") from None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise JudgeUnavailable(
            f"judge endpoint {settings.url} unreachable: {type(exc).__name__}"
        ) from None

    model = _expected_model(settings)
    if model not in ids:
        safe_ids = [model_id.replace(key, "[redacted]") for model_id in ids] if key else ids
        listed = ", ".join(safe_ids) or "nothing"
        raise JudgeUnavailable(
            f"judge endpoint {settings.url} does not list model {model!r}; it lists: {listed}"
        )


class _CapReached(Exception):
    """The configured judge call cap has been reached."""


class _CappedJudge(Judge):
    def __init__(self, chat: Any, *, reply: Literal["short", "full"], max_calls: int) -> None:
        super().__init__(chat, reply=reply)
        self.max_calls = max_calls

    def score(self, premises: Sequence[str], hypothesis: str) -> list[NLIProbs]:
        if len(self.calls) >= self.max_calls:
            raise _CapReached
        return super().score(premises, hypothesis)


def _new_judge(settings: JudgeSettings) -> _CappedJudge:
    if settings.preset is not None:
        name = settings.preset
        preset = PRESETS[name]
        chat = OpenAIChat(
            settings.url,
            preset.model,
            api_key_env=settings.api_key_env,
            sampling=dict(preset.sampling),
            template_kwargs=dict(preset.template_kwargs),
            timeout=settings.timeout,
        )
        judge = _CappedJudge(
            chat,
            reply=cast(Literal["short", "full"], preset.reply),
            max_calls=settings.max_calls,
        )
        judge.preset = name
        judge.model_id = f"{preset.model}@{preset.revision}"
        return judge
    assert settings.model is not None  # noqa: S101 - JudgeSettings validates this.
    chat = OpenAIChat(
        settings.url,
        settings.model,
        api_key_env=settings.api_key_env,
        timeout=settings.timeout,
    )
    return _CappedJudge(chat, reply="short", max_calls=settings.max_calls)


def _shift(verdict: SentenceVerdict, offset: int) -> SentenceVerdict:
    return replace(verdict, start=verdict.start + offset, end=verdict.end + offset)


def _judged_check(
    premise: Premise, answer: str, question: str | None, judge: _CappedJudge
) -> list[tuple[SentenceVerdict, bool]]:
    jv = JudgedVerifier(judge, STRICT_FIGURES)
    out: list[tuple[SentenceVerdict, bool]] = []
    earlier: list[str] = []
    capped = False
    claims_only = Verifier()
    for i, sentence in enumerate(split_sentences(answer)):
        if capped:
            verdict = claims_only.check_sentence(premise, sentence.text, query=question)
            out.append((_shift(verdict, sentence.start), True))
            earlier.append(sentence.text)
            continue
        judge.prefix = " ".join(earlier)
        judge.sentence = i
        try:
            verdict = Verifier.check_sentence(jv, premise, sentence.text, query=question)
        except _CapReached:
            capped = True
            verdict = claims_only.check_sentence(premise, sentence.text, query=question)
            out.append((_shift(verdict, sentence.start), True))
        else:
            out.append((_shift(verdict, sentence.start), False))
        earlier.append(sentence.text)
    return out


def _judge_label(judge: _CappedJudge, sentence: int) -> str | None:
    calls = [call for call in judge.calls if call.get("sentence") == sentence]
    if not calls:
        return None
    rank = {"contradicted": 0, "not_stated": 1, "error": 1, "supported": 2}
    return min(calls, key=lambda call: rank.get(str(call.get("label")), 1)).get("label")


def _validate_input(answer: str, sources: list[Source]) -> None:
    if len(answer) > MAX_ANSWER_CHARS:
        raise ToolError(f"The answer is over {MAX_ANSWER_CHARS:,} characters.")
    if not sources:
        raise ToolError("Give at least one source. Without one, nothing can be supported.")
    if len(sources) > MAX_SOURCES:
        raise ToolError(f"Give at most {MAX_SOURCES} sources.")
    if sum(len(s.text) for s in sources) > MAX_SOURCE_CHARS:
        raise ToolError(f"The sources are over {MAX_SOURCE_CHARS:,} characters in total.")


def _premise(sources: list[Source]) -> Premise:
    return Premise.from_text(
        "\n\n".join(s.text for s in sources),
        titles=[s.title for s in sources if s.title],
        citations=[s.citation for s in sources if s.citation],
    )


def _judge_info(judge: _CappedJudge) -> JudgeInfo:
    preset = judge.preset
    failed_calls = sum(call.get("error") is not None for call in judge.calls)
    return JudgeInfo(
        model=judge.model_id,
        preset=preset,
        measured=preset is not None,
        prompt_sha256=PRESETS[preset].prompt_sha256 if preset is not None else SHORT_SHA,
        calls=len(judge.calls),
        failed_calls=failed_calls,
    )


def _checked_text(judge: _CappedJudge) -> str:
    figure = PRESETS[judge.preset].figure if judge.preset is not None else "unmeasured"
    return (
        CHECKED
        + f" Every sentence was also read by an LLM judge, {judge.model_id}, against the sources. "
        f"Its measured accuracy: {figure}."
    )


def _last_error(judge: _CappedJudge) -> str:
    for call in reversed(judge.calls):
        error = call.get("error")
        if error is not None:
            return str(error)
    return "unknown"


def check(answer: str, sources: list[Source], question: str | None = None) -> CheckReport:
    """Check every sentence of ``answer`` against ``sources``."""
    _validate_input(answer, sources)
    premise = _premise(sources)
    sentences = [_sentence(v) for v in Verifier().check_text(premise, answer, query=question)]
    counts = {
        k: sum(s.status == k for s in sentences) for k in ("supported", "unsupported", "unchecked")
    }
    return CheckReport(
        passed=counts["unsupported"] == 0, sentences=sentences, checked=CHECKED, **counts
    )


def _check_with_judge(
    answer: str, sources: list[Source], question: str | None, settings: JudgeSettings
) -> CheckReport:
    _validate_input(answer, sources)
    premise = _premise(sources)
    judge = _new_judge(settings)
    verdicts = _judged_check(premise, answer, question, judge)
    calls = len(judge.calls)
    failed_calls = sum(call.get("error") is not None for call in judge.calls)
    if calls > 0 and failed_calls == calls:
        raise ToolError(f"judge unavailable: all {calls} judge calls failed ({_last_error(judge)})")

    index = build_index(premise)
    sentences: list[SentenceCheck] = []
    cap_detail = f"judge cap of {settings.max_calls} calls reached; not judged"
    for i, (verdict, capped) in enumerate(verdicts):
        checked_by: Literal["claims", "judge"] = (
            "judge"
            if not capped and any(call.get("sentence") == i for call in judge.calls)
            else "claims"
        )
        passage = None
        if (
            checked_by == "judge"
            and verdict.nli is not None
            and 0 <= verdict.nli.window < len(index.windows)
        ):
            passage = index.windows[verdict.nli.window].text
        sentences.append(
            _sentence(
                verdict,
                checked_by=checked_by,
                judge_label=_judge_label(judge, i) if checked_by == "judge" else None,
                judge_passage=passage,
                cap_detail=cap_detail if capped else None,
                premise=premise,
                question=question,
            )
        )
    counts = {
        k: sum(s.status == k for s in sentences) for k in ("supported", "unsupported", "unchecked")
    }
    return CheckReport(
        passed=counts["unsupported"] == 0,
        sentences=sentences,
        checked=_checked_text(judge),
        judge=_judge_info(judge),
        **counts,
    )


def build_server(uk_index: Path | None = None, judge: JudgeSettings | None = None) -> MCPServer:
    """The server. ``resolve_uk_citation`` is registered only when a UK index is given."""
    if judge is not None:
        _probe(judge)
    server = MCPServer(
        "answer-check",
        version=version("answer-check-mcp"),
        instructions=JUDGE_INSTRUCTIONS if judge else INSTRUCTIONS,
    )
    annotations = JUDGE_READ_ONLY if judge else READ_ONLY
    tool_kwargs: dict[str, Any] = {"annotations": annotations}
    if judge is not None:
        tool_kwargs["description"] = JUDGE_CHECK_DESCRIPTION

    @server.tool(**tool_kwargs)
    def check_answer(
        answer: str, sources: list[Source], question: str | None = None
    ) -> CheckReport:
        """Check each sentence of an answer against the sources it should rest on.

        Each sentence comes back 'supported', 'unsupported' (with the claims no source backs and,
        where possible, the source values to use instead) or 'unchecked'. Figures stated in the
        question count as supported. No model is called, and the same input always gives the
        same result.
        """
        if judge is not None:
            try:
                return _check_with_judge(answer, sources, question, judge)
            except ToolError as exc:
                if str(exc).startswith("judge unavailable"):
                    return CallToolResult(
                        content=[TextContent(type="text", text=str(exc))], is_error=True
                    )
                raise
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
