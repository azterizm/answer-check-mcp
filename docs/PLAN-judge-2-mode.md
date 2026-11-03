# Plan, phase 2 of 3: an optional judge mode (0.2.0)

Status: written 2026-11-01; decisions taken 2026-11-02; steps 1–7 done (6: repo created and PR #1 merged on 2026-11-02; 7: the live smoke passed, see the testing plan).
It depends on phase 1, the judge module in `legal-rag-verifier` 0.5.0
(`legal-rag-verifier/docs/PLAN-judge-1-module.md`). This repository's tests are in
`docs/PLAN-judge-3-testing.md`.

## Goal

With a judge endpoint configured, `check_answer` also judges the sentences the claim check cannot test, using the
verifier's measured judge. Without one, the server behaves exactly as in 0.1.0: deterministic, no model call, no
network.

## Two decisions before any code ⛔

### 1. Which sentences go to the judge

- **(a) The measured configuration (recommended).** The claim check runs first. The judge then decides entailment for
  every sentence that reaches it, and figures the claim check rejects are sent to it too (`STRICT_FIGURES`). This is
  the configuration whose accuracy is published (90.1% on 151 unseen sentences, 93.8% on 354), so the README can
  quote it. It makes one call per clause.
- **(b) Only the sentences the claim check marks unchecked.** Fewer calls, but a configuration nobody has measured.
  The README could not quote any accuracy for it until it is measured.

Recommendation: (a) as the only judge mode in 0.2.0. (b) is not built until a measurement backs it.

**Answer (2026-11-02):** (a), the measured configuration, `STRICT_FIGURES`, is the only judge mode.

### 2. The limit on answers written with sources

An MCP agent usually writes with its sources in hand. On such answers in the verifier's second fresh test, every
judge scored below no judge: 88.9% against 94.4%, on 72 sentences. The judge mostly helps sentences the model wrote
from its own knowledge. Stop 70 found the live loop still helped the 7B with the source in the prompt (answers with
a wrong sentence fell from 25 to 13 of 240).

Proposal: the README states both findings beside the accuracy figure. It describes judge mode as most useful when the
agent mixes its own knowledge with the sources, and says a judge can add false rejections on answers that stay close
to their sources.

**Answer (2026-11-02):** the README uses the proposed text: judge mode is most useful when the agent mixes its own
knowledge with the sources, and a judge can add false rejections on answers that stay close to their sources.

## Decisions made while planning (2026-11-02)

### 3. Wrong figures

Verdicts stay as measured, and `suggested` is filled back in. When the judge rejects a sentence with a figure it was
sent, a claims-only `Verifier()` pass on that sentence supplies the source value. This makes no model call.

Evidence: GRID stop 52 E2 gained 8 and lost 0. GRID stop 56 P3 gained 3 and lost 1. Design decision D-a fixes the
trigger: the claims-only pass must find `UNGROUNDED_FIGURE`, because a judge-rejected wrong figure carries
`NLI_CONTRADICTION`.

### 4. Preset and model

`--judge-url` alone uses `qwen27-ar4` (`measured: true`). `--judge-model` sets up a custom judge (`measured: false`),
with the short reply, `STRICT_FIGURES`, the server's default sampling and no template arguments. Both flags together,
or either flag without `--judge-url`, is an error at start.

### 5. Past the cap

Past `--judge-max-calls`, the claim check still runs, matching 0.1.0 behaviour. Wrong figures and citations stay
unsupported, with suggestions. The rest are `unchecked`. Each such sentence gets this detail:
"judge cap of N calls reached; not judged".

### 7. Three measured presets, two defined in this repo

`--judge-preset` accepts the library's `PRESETS` plus two local presets, each built as a
`legal_rag_verifier.judge.Preset`. The keys follow `scripts/modal_distill.py` and the label files.

| Key | Model @ revision | Reply | Server and sampling | Figures (fresh 1 / fresh 2) |
|---|---|---|---|---|
| `qwen27-ar4` (library, the default) | `Vishva007/Qwen3.8-27B-W4A16-AutoRound-GPTQ@1b9d56b428e9f841d7ad566f87660b5f47553c97` | short | as in the library | 93.8% / 90.1%, 0.54 s |
| `gemma4-e4b` (local) | `google/gemma-4-E4B-it@ee0ef6023621cff504d758262d4e04895a5af4a2` | short (`SHORT_SHA`) | SGLang 0.5.21, `--context-length 65536`, one L40S; temperature 1.0, top_p 0.95, top_k 64, max_tokens 1024, seed 0; `enable_thinking: False` | 86.4% (16 false rollbacks / 116 caught) / 85.4% (9 / 54), 0.41 s |
| `qwen27-nothink` (local) | `Qwen/Qwen3.8-27B-FP8@017b9c7af6b5689d5dd426a76e0bc077eb5ca20a` | full (`PROMPT_SHA`) | SGLang 0.5.21, `--reasoning-parser qwen3 --context-length 65536`, one L40S; the same sampling as `qwen27-ar4`; `enable_thinking: False` | 91.5% (14 / 132) / 90.7% (9 / 62) |

Recorded caveats:

- The library decided "No FP8 preset" (`API.md:262`). This repo defines one on the user's decision of 2026-11-02.
- The with-source limit was measured on `qwen27-ar4` (88.9% against 94.4%). Stop 56 found a similar gap on FP8 with
  `notes2`. It was not measured for Gemma.

### Replay check (step 1b)

The replay script was a scratch script following `tests/test_judge_replay.py`, with `_cell` copied unchanged. It was
not kept in either repo.

Command:

```sh
cd legal-rag-verifier && uv run python replay_local.py
```

| Preset | Set | Reply | Unknown prompts | Correct / units | False rollbacks / caught | Result |
|---|---|---|---:|---|---|---|
| `gemma4-e4b` | fresh | short | 0 | 306/354 | 16 / 116 | PASS |
| `gemma4-e4b` | fresh2 | short | 0 | 129/151 | 9 / 54 | PASS |
| `qwen27-nothink` | fresh | full | 0 | 324/354 | 14 / 132 | PASS |
| `qwen27-nothink` | fresh2 | full | 0 | 137/151 | 9 / 62 | PASS |

Both local presets are marked measured.

### 6. Git

Commit 0.1.0 on `main`, then work on branch `judge-mode`. Nothing is pushed. The GitHub repo does not exist yet;
creating it is step 6 ⛔.

### Other design decisions

Design decision D-b: `open_world_hint=true` on `check_answer` only. `resolve_uk_citation` makes no network call.

## Design

**Flags**, each with an environment variable of the same meaning:

| Flag | Meaning |
|---|---|
| `--judge-url` | Base URL of an OpenAI-compatible server (SGLang, vLLM or a hosted API) |
| `--judge-model` | Model name the server expects |
| `--judge-preset` | A measured preset from the library's `PRESETS` plus the two local ones in `src/answer_check_mcp/presets.py`. It sets the sampling, template arguments and reply form |
| `--judge-api-key-env` | Name of the environment variable holding the key. The key itself is never a flag |
| `--judge-timeout` | Seconds per call, default 30 |
| `--judge-max-calls` | Cap on judge calls per `check_answer`, default 40. Past the cap the claim check still runs, with a detail saying why |

**Output.** Fields are added, none removed:

- each sentence gains `checked_by` (`"claims"` or `"judge"`), `judge_label` and `judge_passage`
- the report gains `judge`: the model, the preset or none, `measured` (true only for a preset), the prompt hash, the
  number of calls, and the number of failed calls
- the `checked` text says a judge read the prose, and names the model

**MCP behaviour.**

- In judge mode the tools' `open_world_hint` becomes true, because the sources and the answer leave the machine. The
  README says so plainly.
- The server instructions gain one line: a sentence the judge marked supported is still only as good as the judge's
  measured accuracy.
- At start, the server sends `GET /v1/models` to the endpoint, which is free, and refuses to start with a clear
  message if the endpoint is unreachable or does not list the model.
- A judge call that fails three times scores not stated, as measured, and is counted. If every judge call in a check
  fails, `check_answer` returns a tool error ("judge unavailable") instead of quietly rejecting every sentence.
- Calls run one at a time in 0.2.0, as measured. Parallel calls would be a later change with its own latency check.

**README.**

- A judge-mode section: the measured presets in a table (model, test, accuracy, time per call, link to
  `measurements.md`), the sentence "Any other model is unmeasured", decision 2's limit, and one launch example
  against a self-hosted SGLang server.
- What judge mode costs: one call per clause, about 0.54 s each at p50 on one L40S for the default preset (stop 61).

**Version.** 0.2.0, depending on `legal-rag-verifier>=0.5,<0.6`.

## Steps

1. Decisions 1 and 2 recorded here with your answers.
2. Tests first, failing, against a stub OpenAI-compatible server (the testing plan lists them).
3. The code: flag parsing in `__init__.py`, and in `server.py` the `JudgedVerifier` from the preset or the custom
   endpoint, the output fields, the start probe and the per-check cap.
4. README and the version bump.
5. Checks: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` on Python 3.12 to 3.14, and the wheel
   launched in a clean `uvx` environment in both modes.
6. Push and CI ⛔, with your go.
7. The live smoke runs with phase 3's live check, against the same server.

## Done when

- With no judge flags, all 0.1.0 tests pass unchanged and the server makes no network call.
- With a preset and a reachable endpoint, prose sentences come back judged, each with `checked_by`, and the report
  says `measured: true`.
- With a custom model, the report says `measured: false`, and the README tells the reader what that means.
- The key never appears in output, errors or logs.

## Risks

- Endpoints differ in reasoning fields and template arguments. Presets cover the measured servers. Anything else is
  run as unmeasured and may need its own reply handling.
- One call per clause makes long answers slow. The per-check cap bounds it, and the README states the cost.
- An agent may read "supported by the judge" as proof. The output names the judge and its measured accuracy, and the
  instructions say a judge can be wrong.

## Cost and time

About half a day after phase 1 ships. No spend: the live smoke shares phase 3's live check.
