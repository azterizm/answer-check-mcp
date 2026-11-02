"""Judge mode as an agent calls it: through an MCP client against a local fake judge."""

from __future__ import annotations

import importlib
import json
import socket
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from legal_rag_verifier.judge import (
    PROMPT_SHA,
    SHORT_REPLY,
    SHORT_SHA,
    STRICT_FIGURES,
    Judge,
    JudgedVerifier,
)
from legal_rag_verifier.premise import Premise
from legal_rag_verifier.verifier import Reason, SentenceVerdict, Verdict
from mcp import Client

import answer_check_mcp.server as server

pytestmark = pytest.mark.anyio

PLAN = {
    "text": "The Pro plan costs $20 a month and includes 5 seats.\n\n"
    "Customers must request a refund within 30 days of purchase."
}
PROSE = "Support is friendly and fast."
SECRET = "sk-test-secret-123"
PRESET_KEYS = ("gemma4-e4b", "qwen27-ar4", "qwen27-nothink")


def _settings(judge_stub: Any, **overrides: Any) -> Any:
    values = {"url": judge_stub.url, **overrides}
    return server.JudgeSettings(**values)


async def _call_check(
    judge: Any,
    answer: str,
    sources: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> Any:
    async with Client(server.build_server(judge=judge)) as client:
        return await client.call_tool(
            "check_answer", {"answer": answer, "sources": sources or [PLAN], **extra}
        )


async def _checked(
    judge: Any,
    answer: str,
    sources: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result = await _call_check(judge, answer, sources, **extra)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


def _text_content(result: Any) -> str:
    return "\n".join(str(getattr(item, "text", "")) for item in result.content)


def _post_requests(judge_stub: Any) -> list[dict[str, Any]]:
    return [request for request in judge_stub.requests if request["method"] == "POST"]


def _prompt(request: dict[str, Any]) -> str:
    return str(request["json"]["messages"][1]["content"])


def _status(verdict: SentenceVerdict) -> str:
    if verdict.verdict is Verdict.ROLLBACK:
        return "unsupported"
    if Reason.GROUNDED in verdict.reasons:
        return "supported"
    return "unchecked"


def _server_view(sentence: Mapping[str, Any]) -> tuple[str, list[str]]:
    return sentence["status"], list(sentence["reasons"])


def _verdict_view(verdict: SentenceVerdict) -> tuple[str, list[str]]:
    status = _status(verdict)
    reasons = [reason.value for reason in verdict.reasons] if status == "unsupported" else []
    return status, reasons


async def test_no_judge_makes_no_request_and_keeps_claims_only_fields(judge_stub: Any) -> None:
    async with Client(server.build_server()) as client:
        result = await client.call_tool(
            "check_answer",
            {"answer": "It includes 5 seats. Support is friendly and fast.", "sources": [PLAN]},
        )

    assert not result.is_error, result.content
    assert judge_stub.requests == []
    assert result.structured_content is not None
    report = result.structured_content
    assert report["judge"] is None
    assert [sentence["checked_by"] for sentence in report["sentences"]] == ["claims", "claims"]
    assert [sentence["judge_label"] for sentence in report["sentences"]] == [None, None]
    assert [sentence["judge_passage"] for sentence in report["sentences"]] == [None, None]


async def test_prose_is_judged(judge_stub: Any) -> None:
    judge_stub.script = ["contradicted"]
    report = await _checked(_settings(judge_stub), PROSE)
    (sentence,) = report["sentences"]

    assert (sentence["status"], sentence["checked_by"], sentence["judge_label"]) == (
        "unsupported",
        "judge",
        "contradicted",
    )
    assert _post_requests(judge_stub), "the prose sentence reached the judge"


async def test_wrong_figure_keeps_judge_verdict_and_gets_claim_suggestion(judge_stub: Any) -> None:
    judge_stub.script = ["contradicted"]
    report = await _checked(_settings(judge_stub), "The Pro plan costs $25 a month.")
    (sentence,) = report["sentences"]

    assert sentence["status"] == "unsupported"
    assert sentence["suggested"] == ["$20"]
    assert sentence["checked_by"] == "judge"
    assert _post_requests(judge_stub)


@pytest.mark.parametrize(
    ("preset", "prompt_sha256"),
    [("qwen27-ar4", SHORT_SHA), ("gemma4-e4b", SHORT_SHA), ("qwen27-nothink", PROMPT_SHA)],
)
async def test_presets_are_measured_and_report_their_prompt_hash(
    judge_stub: Any, preset: str, prompt_sha256: str
) -> None:
    report = await _checked(_settings(judge_stub, preset=preset), PROSE)

    assert report["judge"]["preset"] == preset
    assert report["judge"]["measured"] is True
    assert report["judge"]["prompt_sha256"] == prompt_sha256


async def test_custom_model_is_unmeasured_and_uses_the_short_prompt(judge_stub: Any) -> None:
    report = await _checked(_settings(judge_stub, model="custom-model"), PROSE)

    assert report["judge"]["preset"] is None
    assert report["judge"]["model"] == "custom-model"
    assert report["judge"]["measured"] is False
    assert report["judge"]["prompt_sha256"] == SHORT_SHA


@pytest.mark.parametrize("preset_name", PRESET_KEYS)
async def test_request_shape_for_each_preset(judge_stub: Any, preset_name: str) -> None:
    presets = importlib.import_module("answer_check_mcp.presets")
    preset = presets.PRESETS[preset_name]
    first = "Support is friendly and fast."
    second = "Setup is quick."

    await _checked(_settings(judge_stub, preset=preset_name), f"{first} {second}")
    posts = _post_requests(judge_stub)
    assert len(posts) == 2
    first_body = posts[0]["json"]

    assert first_body["model"] == preset.model
    for key, value in dict(preset.sampling).items():
        assert first_body[key] == value
    assert first_body["chat_template_kwargs"] == dict(preset.template_kwargs)
    if preset.reply == "short":
        assert SHORT_REPLY in _prompt(posts[0])
    else:
        assert SHORT_REPLY not in _prompt(posts[0])
        assert '"reason" (one sentence)' in _prompt(posts[0])
    assert first in _prompt(posts[1])
    assert second in _prompt(posts[1])


def test_settings_validation_rejects_invalid_combinations(judge_stub: Any) -> None:
    cases = [
        {"url": judge_stub.url, "model": "custom-model", "preset": "qwen27-ar4"},
        {"url": judge_stub.url, "timeout": 0},
        {"url": judge_stub.url, "max_calls": 0},
        {"url": "ftp://x"},
    ]

    for kwargs in cases:
        with pytest.raises(ValueError):
            server.JudgeSettings(**kwargs)


def test_unknown_preset_lists_all_valid_keys_via_settings_and_cli(
    judge_stub: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(ValueError) as settings_error:
        server.JudgeSettings(url=judge_stub.url, preset="missing")
    message = str(settings_error.value)
    assert "unknown judge preset 'missing'" in message
    for key in PRESET_KEYS:
        assert key in message

    monkeypatch.setattr(
        sys,
        "argv",
        ["answer-check-mcp", "--judge-url", judge_stub.url, "--judge-preset", "missing"],
    )
    module = importlib.import_module("answer_check_mcp")
    with pytest.raises(SystemExit) as cli_exit:
        module.main()
    assert cli_exit.value.code == 2
    stderr = capsys.readouterr().err
    for key in PRESET_KEYS:
        assert key in stderr


@pytest.mark.parametrize(
    "argv",
    [
        ["answer-check-mcp", "--judge-model", "custom-model"],
        [
            "answer-check-mcp",
            "--judge-url",
            "STUB_URL",
            "--judge-model",
            "custom-model",
            "--judge-preset",
            "qwen27-ar4",
        ],
    ],
)
def test_cli_rejects_invalid_judge_argument_combinations(
    argv: list[str],
    judge_stub: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [judge_stub.url if value == "STUB_URL" else value for value in argv],
    )
    module = importlib.import_module("answer_check_mcp")

    with pytest.raises(SystemExit) as cli_exit:
        module.main()

    assert cli_exit.value.code == 2


def test_cli_reads_judge_defaults_from_environment(
    judge_stub: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: dict[str, Any] = {}

    class FakeServer:
        def run(self) -> None:
            return None

    def fake_build_server(uk_index: Any = None, judge: Any = None) -> FakeServer:
        recorded["uk_index"] = uk_index
        recorded["judge"] = judge
        return FakeServer()

    module = importlib.import_module("answer_check_mcp")
    monkeypatch.setattr(module, "build_server", fake_build_server)
    monkeypatch.setattr(sys, "argv", ["answer-check-mcp"])
    monkeypatch.setenv("ANSWER_CHECK_JUDGE_URL", judge_stub.url)
    monkeypatch.setenv("ANSWER_CHECK_JUDGE_MAX_CALLS", "1")

    module.main()

    judge = recorded["judge"]
    assert judge is not None
    assert judge.url == judge_stub.url
    assert judge.preset == "qwen27-ar4"
    assert judge.max_calls == 1


async def test_instructions_and_tool_description_track_judge_mode(judge_stub: Any) -> None:
    async with Client(server.build_server()) as client:
        no_judge_instructions = client.instructions or ""
        (no_judge_tool,) = (await client.list_tools()).tools

    assert "only as good as the judge" not in no_judge_instructions
    assert no_judge_tool.description is not None
    assert "No model is called" in no_judge_tool.description

    async with Client(server.build_server(judge=_settings(judge_stub))) as client:
        judge_instructions = client.instructions or ""
        (judge_tool,) = (await client.list_tools()).tools

    assert "only as good as the judge" in judge_instructions
    assert judge_tool.description is not None
    assert "No model is called" not in judge_tool.description


async def test_key_is_sent_and_never_leaks_to_outputs_or_errors(
    judge_stub: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANSWER_CHECK_TEST_KEY", SECRET)
    settings = _settings(judge_stub, api_key_env="ANSWER_CHECK_TEST_KEY")
    result = await _call_check(settings, PROSE)
    assert not result.is_error, result.content
    assert result.structured_content is not None

    assert any(
        request["headers"].get("authorization") == f"Bearer {SECRET}"
        for request in judge_stub.requests
    )
    assert SECRET not in json.dumps(result.structured_content)
    assert SECRET not in _text_content(result)

    judge_stub.script = [500, 500, 500]
    error = await _call_check(settings, PROSE)
    assert error.is_error
    assert SECRET not in _text_content(error)

    judge_stub.models = ["some-other-model"]
    with pytest.raises(server.JudgeUnavailable) as probe_error:
        server.build_server(judge=settings)
    assert SECRET not in str(probe_error.value)


async def test_one_failed_judge_call_scores_not_stated_and_is_counted(judge_stub: Any) -> None:
    judge_stub.script = [500, 500, 500, "supported"]
    report = await _checked(_settings(judge_stub), f"{PROSE} It includes 5 seats.")

    first, second = report["sentences"]
    assert (first["status"], first["judge_label"]) == ("unsupported", "error")
    assert second["checked_by"] == "judge"
    assert report["judge"]["failed_calls"] == 1


async def test_every_call_failed_returns_judge_unavailable_tool_error(judge_stub: Any) -> None:
    judge_stub.script = [500, 500, 500]
    result = await _call_check(_settings(judge_stub), PROSE)

    assert result.is_error
    assert _text_content(result).startswith("judge unavailable")


async def test_call_cap_falls_back_to_claims_and_keeps_claim_suggestions(judge_stub: Any) -> None:
    max_calls = 1
    answer = f"{PROSE} The Pro plan costs $25 a month. Another prose sentence."
    report = await _checked(_settings(judge_stub, max_calls=max_calls), answer)

    assert len(_post_requests(judge_stub)) == max_calls
    second, third = report["sentences"][1:]
    assert second["checked_by"] == "claims"
    assert third["checked_by"] == "claims"
    detail = f"judge cap of {max_calls} calls reached; not judged"
    assert detail in second["details"]
    assert detail in third["details"]
    assert (second["status"], second["suggested"]) == ("unsupported", ["$20"])


def _closed_local_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def test_start_probe_refuses_unreachable_and_missing_model(
    judge_stub: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(server.JudgeUnavailable) as unreachable:
        server.build_server(judge=server.JudgeSettings(url=_closed_local_url(), timeout=0.2))
    assert "unreachable" in str(unreachable.value)

    judge_stub.models = ["other-model"]
    with pytest.raises(server.JudgeUnavailable) as missing_model:
        server.build_server(judge=_settings(judge_stub))
    assert "does not list model" in str(missing_model.value)

    monkeypatch.setattr(sys, "argv", ["answer-check-mcp", "--judge-url", judge_stub.url])
    module = importlib.import_module("answer_check_mcp")
    with pytest.raises(SystemExit) as cli_exit:
        module.main()
    assert cli_exit.value.code == 1
    assert "answer-check-mcp: judge endpoint" in capsys.readouterr().err


async def test_check_answer_open_world_hint_tracks_judge_mode(judge_stub: Any) -> None:
    async with Client(server.build_server()) as client:
        (no_judge_tool,) = (await client.list_tools()).tools
    async with Client(server.build_server(judge=_settings(judge_stub))) as client:
        (judge_tool,) = (await client.list_tools()).tools

    assert no_judge_tool.annotations is not None
    assert judge_tool.annotations is not None
    assert no_judge_tool.annotations.open_world_hint is False
    assert judge_tool.annotations.open_world_hint is True


async def test_checked_text_names_the_model_and_figure_or_unmeasured(judge_stub: Any) -> None:
    presets = importlib.import_module("answer_check_mcp.presets")
    preset = presets.PRESETS["qwen27-ar4"]
    measured = await _checked(_settings(judge_stub, preset="qwen27-ar4"), PROSE)
    custom = await _checked(_settings(judge_stub, model="custom-model"), PROSE)

    assert preset.model in measured["checked"]
    assert preset.figure in measured["checked"]
    assert "custom-model" in custom["checked"]
    assert "unmeasured" in custom["checked"]


async def test_judge_passage_is_the_source_window_text(judge_stub: Any) -> None:
    report = await _checked(_settings(judge_stub), "It includes 5 seats.")
    (sentence,) = report["sentences"]

    assert sentence["checked_by"] == "judge"
    assert sentence["judge_passage"] is not None
    assert "The Pro plan costs $20 a month" in sentence["judge_passage"]


class ScriptedChat:
    def __init__(self, labels: Sequence[str]) -> None:
        self.labels = list(labels)
        self.seen = 0

    def __call__(self, messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        label = self.labels[self.seen] if self.seen < len(self.labels) else "supported"
        self.seen += 1
        return {
            "content": json.dumps({"label": label, "passage": 1, "reason": "stub"}),
            "ms": 1.0,
            "tokens": 1,
            "finish": "stop",
        }


async def test_regression_matches_judged_verifier_below_the_cap(judge_stub: Any) -> None:
    labels = ["supported", "contradicted", "not_stated"]
    answer = "It includes 5 seats. Support is friendly and fast. Setup is quick."
    judge_stub.script = labels.copy()
    report = await _checked(_settings(judge_stub, max_calls=10), answer)

    premise = Premise.from_text(PLAN["text"])
    verifier = JudgedVerifier(Judge(ScriptedChat(labels), reply="short"), STRICT_FIGURES)
    expected = verifier.check_text(premise, answer)

    assert [_server_view(sentence) for sentence in report["sentences"]] == [
        _verdict_view(verdict) for verdict in expected
    ]
