# Plan, phase 3 of 3: testing the judge mode (this repository's part)

Status: live smoke done 2026-11-02, PASS. The judge module's own tests, the replay of recorded labels and the paid live
check are planned in `legal-rag-verifier/docs/PLAN-judge-3-testing.md`. This plan covers the MCP server.

## Free tests (no model, no spend)

Written before the code (phase 2, step 3), each failing first. They call the server through an MCP client, as an
agent does, against a stub OpenAI-compatible server started on localhost by a fixture. The stub returns scripted
replies and records each request.

| Test | What it proves |
|---|---|
| No judge flags | Every 0.1.0 test passes unchanged, and the stub receives no request |
| Prose is judged | A sentence the claim check cannot test comes back with the stub's label as its status, and `checked_by` is `"judge"` |
| Figures still checked first | The stub says contradicted; the result is unsupported with `$20` suggested; and the stub received the call |
| Measured flag | Each of the three presets gives `measured: true` and its prompt hash (`SHORT_SHA` for `qwen27-ar4` and `gemma4-e4b`, `PROMPT_SHA` for `qwen27-nothink`). A custom `--judge-model` gives `measured: false` |
| Request shape | The stub sees the preset's sampling and template arguments, and the prompt for each sentence carries the sentences before it |
| Key handling | A key passed through `--judge-api-key-env` reaches the stub as a bearer header and appears in no tool output or error text |
| One failed call | Three stub failures score that clause as not stated, and the report counts one failed call |
| Every call fails | `check_answer` returns a tool error, "judge unavailable" |
| Call cap | Past `--judge-max-calls`, the remaining sentences fall back to the claim check: wrong figures and citations stay unsupported with suggestions, and the rest are `unchecked`. Each has the detail "judge cap of N calls reached; not judged", and the stub sees exactly the cap |
| Start probe | An unreachable endpoint, or one whose `/v1/models` does not list the model, stops the server at start with a clear message |
| Annotations | `open_world_hint` is false without a judge and true with one |
| Over stdio | The installed command, launched with judge flags against the stub, judges one prose sentence |

## Live smoke (no separate spend)

Run in the same session as `legal-rag-verifier`'s live check, option A, against the same Modal SGLang server, so it
adds a few calls and no new spend line:

1. Launch the server from the released wheel in a clean `uvx` environment with `--judge-preset` set to the default
   and `--judge-url` set to the Modal endpoint.
2. Call `check_answer` on three short answers with sources: one wrong figure, one wrong prose claim, and one correct
   answer.
3. Record each sentence's status, `checked_by`, the judge label, the time per call, and that the report says
   `measured: true`.

The pass rule is fixed before the run: the wrong figure and the wrong prose claim are both unsupported, and the
correct answer passes. If any of the three fails, record the failure, note it in the README, and do not publish
0.2.0 until the cause is understood.

### Result (2026-11-02)

Run against `legal-rag-verifier` stop 78 (Modal, SGLang 0.5.21, `qwen27-ar4` at `1b9d56b4`, one L40S, behind an API key).
Server under test: `answer-check-mcp` at `65e7260` (version 0.2.0), launched with `uvx --isolated --from git+https://github.com/azterizm/answer-check-mcp@65e7260 answer-check-mcp --judge-url <Modal URL> --judge-api-key-env LIVE_JUDGE_API_KEY`.

| Case | Answer | Status | Checked by | Judge label | Suggested | Calls | Seconds |
|---|---|---|---|---|---|---:|---:|
| Wrong figure | The Pro plan costs $25 a month. | unsupported | judge | contradicted | $20 | 1 | 1.31 |
| Wrong prose claim | Refunds have no time limit. | unsupported | judge | contradicted | — | 1 | 1.25 |
| Correct answer | The Pro plan costs $20 a month and includes 5 seats. Customers must request a refund within 30 days of purchase. | supported | judge | supported | — | 2 | 2.40 |

Verdict: PASS. The wrong figure and wrong prose claim are both unsupported, and the correct answer passes (both sentences supported). The report returned `measured: true` (`prompt_sha256`: `7748f874...`), and the API key appeared in no tool output. Wall time was ~1.2–1.3 s per call (Pakistan to Modal us-east, including ~0.7 s network round trip; Modal server p50 was 0.58 s).

Departure: launched from the merged git main (`65e7260`, PR #1), not a PyPI wheel. `answer-check-mcp` is not published on PyPI; the git install is the release users get from the README.

## Order

1. The free tests green before the push in phase 2, step 6.
2. The live smoke after `legal-rag-verifier` 0.5.0 is on PyPI and its live check has your go.
