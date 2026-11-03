# answer-check-mcp

**An MCP server that checks an AI agent's draft answer against its sources before the agent replies. By default no model is called, no network is used, and the same input always gives the same result. An optional judge mode also sends each sentence to an LLM endpoint you choose.**

An agent calls `check_answer` with its draft and the sources it was given. Each sentence comes back `supported`, `unsupported` or `unchecked`. An unsupported sentence names the claims no source backs and, where the source holds the right value, offers it as the fix. A sentence with nothing the check can test comes back `unchecked`, so prose is never reported as verified.

```text
source:  The Pro plan costs $20 a month and includes 5 seats.
         Customers must request a refund within 30 days of purchase.

draft:   The Pro plan costs $25 a month.                  unsupported, the source says $20
         It includes 5 seats.                             supported
         Support is friendly.                             unchecked
         Customers may request a refund within 30 days.   unsupported, the source says must
```

## Results

The check is the deterministic layer of [`legal-rag-verifier`](https://github.com/azterizm/legal-rag-verifier). On that package's held-out set of 346 sentences on UK law, sealed before it ran once, it caught 83 of 155 planted errors and rejected 10 of 191 correct sentences. When it rejected a sentence, it was right 89.3% of the time. The method and raw results are in the [held-out section of the measurements](https://github.com/azterizm/legal-rag-verifier/blob/main/docs/measurements.md#held-out--sealed-heldout-2026-10-06-run-once-per-detector-2026-10-06).

### What it does not show

The held-out set is UK law only. The check reads numbers, money, percentages, dates, durations, legal citations, the names of Acts and other instruments, qualifiers such as "the lower of", and obligation wording such as "must" against "may". A wrong statement made only in prose gets past it and comes back `unchecked`, so the agent or a judge model still has to read those sentences. This server's judge mode does that; see [Judge mode](#judge-mode).

## Use it

With Claude Code:

```bash
claude mcp add answer-check -- uvx answer-check-mcp
```

Any other MCP host takes the same command in its server configuration:

```json
{
  "mcpServers": {
    "answer-check": {
      "command": "uvx",
      "args": ["answer-check-mcp"]
    }
  }
}
```

The server tells the agent to check any draft that states figures, dates, citations or obligations from its sources, to rewrite or remove each unsupported sentence, and never to call an unchecked sentence verified.

## Tools

| Tool | What it does | Needs |
|---|---|---|
| `check_answer` | Checks each sentence of `answer` against `sources`. Figures stated in the optional `question` count as supported. | Nothing |
| `resolve_uk_citation` | Resolves a citation to UK legislation against the statute book. Real law resolves to its provision, a typo is corrected, invented law is refused with close real titles, and EU law is declared out of coverage. | The [`legal-rag-router`](https://github.com/azterizm/legal-rag-router) index (about 360 MB) |

Each source can carry a `title` (the Act it comes from) and a `citation` (the provision), so the answer may name them. By default both tools are read-only and make no network calls. In judge mode `check_answer` calls the configured judge endpoint; `resolve_uk_citation` never does. Input is bounded: an answer of up to 20,000 characters, and up to 50 sources with 200,000 characters in total.

To turn on `resolve_uk_citation`, download the index as the router's README describes, then:

```bash
uvx --with legal-rag-router answer-check-mcp --uk-index data/index
```

## Judge mode

Judge mode is off unless `--judge-url` is set. With it, every sentence is also judged by an LLM over an OpenAI-compatible API such as SGLang, vLLM or a hosted API, using the verifier's measured `STRICT_FIGURES` configuration. It makes one call per clause, one at a time, until the cap is reached. Each sentence gains `checked_by`, `judge_label` and `judge_passage`. The report gains a `judge` object with `model`, `preset`, `measured`, `prompt_sha256`, `calls` and `failed_calls`.

| Flag | Environment variable | Default |
|---|---|---|
| `--judge-url` | `ANSWER_CHECK_JUDGE_URL` | none; judge mode is off |
| `--judge-model` | `ANSWER_CHECK_JUDGE_MODEL` | none; custom unmeasured model when set |
| `--judge-preset` | `ANSWER_CHECK_JUDGE_PRESET` | `qwen27-ar4` when only the URL is given |
| `--judge-api-key-env` | `ANSWER_CHECK_JUDGE_API_KEY_ENV` | none; this names the variable holding the key, the key is never a flag |
| `--judge-timeout` | `ANSWER_CHECK_JUDGE_TIMEOUT` | 30 seconds |
| `--judge-max-calls` | `ANSWER_CHECK_JUDGE_MAX_CALLS` | 40 calls per check |

`--judge-model` and `--judge-preset` are mutually exclusive, and either needs `--judge-url`. Past the cap, the claim check still runs and each sentence says `judge cap of N calls reached; not judged`.

The two test sets below have 354 and 151 sentences that the judges never saw.

| Key | Model | Reply | First test / second test | Time per clause, p50, one L40S | Measurements |
|---|---|---|---|---|---|
| `qwen27-ar4` | `Vishva007/Qwen3.8-27B-W4A16-AutoRound-GPTQ` | short | 93.8 % / 90.1 % | 0.54 s | [`measurements.md`](https://github.com/azterizm/legal-rag-verifier/blob/main/docs/measurements.md#a-judge-reply-without-the-reason-stop-61-2026-10-12-method-in-docsgridmd) |
| `gemma4-e4b` | `google/gemma-4-E4B-it` | short | 86.4 % / 85.4 % | 0.41 s | [`measurements.md`](https://github.com/azterizm/legal-rag-verifier/blob/main/docs/measurements.md#two-smaller-judges-untrained-stop-62-2026-10-12-method-in-docsgridmd) |
| `qwen27-nothink` | `Qwen/Qwen3.8-27B-FP8` | full | 91.5 % / 90.7 % | 3.5 s (full reply) | [`GRID.md` stop 55](https://github.com/azterizm/legal-rag-verifier/blob/main/docs/GRID.md#stop-55-results-2026-10-11); [`GRID.md` stop 56](https://github.com/azterizm/legal-rag-verifier/blob/main/docs/GRID.md#stop-56-results-2026-10-11) |

`gemma4-e4b` and `qwen27-nothink` are defined by this server in `src/answer_check_mcp/presets.py`, not by `legal-rag-verifier`. Their recorded labels were replayed through the library's judge and reproduced the published counts.

Any other model is unmeasured. `--judge-model NAME` runs a custom model with the short reply and the server's default sampling. The report says `measured: false` and the `checked` text says `unmeasured`: nobody knows how accurate it is.

There is a limit on answers written with the sources in hand. In the verifier's second fresh test, every judge scored below no judge: 88.9 % against 94.4 %, on 72 sentences. That was measured on `qwen27-ar4`; stop 56 found a similar gap on the FP8 model with another prompt; it was not measured for Gemma. The judge mostly helps sentences the model wrote from its own knowledge. In a live loop (stop 70) it still helped a 7B model with the source in its prompt: answers with a wrong sentence fell from 25 to 13 of 240. Judge mode is most useful when the agent mixes its own knowledge with the sources, and a judge can add false rejections on answers that stay close to their sources.

Cost is one call per clause. The cap bounds a check, and the p50 times are in the table above.

In judge mode the answer and the sources are sent to the judge endpoint, and the tool's `open_world_hint` is true. A sentence the judge marked supported is only as good as the judge's measured accuracy.

At start the server checks `GET /v1/models` and refuses to start if the endpoint is unreachable or does not list the model. If every judge call in a check fails, `check_answer` returns `judge unavailable`.

Example with SGLang 0.5.21 for the default preset on one L40S:

```bash
python -m sglang.launch_server \
  --model-path Vishva007/Qwen3.8-27B-W4A16-AutoRound-GPTQ \
  --revision 1b9d56b428e9f841d7ad566f87660b5f47553c97 \
  --reasoning-parser qwen3 \
  --context-length 65536 \
  --mem-fraction-static 0.85 \
  --port 30000

claude mcp add answer-check -- uvx answer-check-mcp --judge-url http://localhost:30000
```

Hosted API variant:

```bash
claude mcp add answer-check -- uvx answer-check-mcp --judge-url https://api.example.com --judge-model model-name --judge-api-key-env ANSWER_CHECK_JUDGE_API_KEY
```

The variable named by `--judge-api-key-env` must be set in the server's environment (for Claude Code, `claude mcp add -e ANSWER_CHECK_JUDGE_API_KEY=...`); the key never appears in output or errors.

## Tests

```bash
uv sync --extra router
uv run pytest                                   # 42 pass, 4 citation tests skip
ANSWER_CHECK_UK_INDEX=data/index uv run pytest  # all 46, with the router index
```

The tests call the server through an MCP client, as an agent does, and one of them launches the installed command over stdio. The judge tests use a local stub server, with no model and no network beyond localhost.

## Licence

AGPL-3.0-only, like the two packages it builds on. Built by [Abdullah Memon](https://azterizm.com) at [Memon Systems Ltd](https://memonsystems.com).
