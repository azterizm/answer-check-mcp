# answer-check-mcp

**An MCP server that checks an AI agent's draft answer against its sources before the agent replies. No model is called, and the same input always gives the same result.**

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

The held-out set is UK law only. The check reads numbers, money, percentages, dates, durations, legal citations, the names of Acts and other instruments, qualifiers such as "the lower of", and obligation wording such as "must" against "may". A wrong statement made only in prose gets past it and comes back `unchecked`, so the agent or a judge model still has to read those sentences. `legal-rag-verifier` pairs the check with a model judge for that reason.

## Use it

With Claude Code:

```bash
claude mcp add answer-check -- uvx --from git+https://github.com/azterizm/answer-check-mcp answer-check-mcp
```

Any other MCP host takes the same command in its server configuration:

```json
{
  "mcpServers": {
    "answer-check": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/azterizm/answer-check-mcp", "answer-check-mcp"]
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

Each source can carry a `title` (the Act it comes from) and a `citation` (the provision), so the answer may name them. Both tools are read-only and make no network calls. Input is bounded: an answer of up to 20,000 characters, and up to 50 sources with 200,000 characters in total.

To turn on `resolve_uk_citation`, download the index as the router's README describes, then:

```bash
uvx --from git+https://github.com/azterizm/answer-check-mcp --with legal-rag-router answer-check-mcp --uk-index data/index
```

## Tests

```bash
uv sync --extra router
uv run pytest                                   # 15 pass, the 4 citation tests skip
ANSWER_CHECK_UK_INDEX=data/index uv run pytest  # all 19, with the router index
```

The tests call the server through an MCP client, as an agent does, and one of them launches the installed command over stdio.

## Licence

AGPL-3.0-only, like the two packages it builds on. Built by [Abdullah Memon](https://azterizm.com) at [Memon Systems Ltd](https://memonsystems.com).
