# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-11-03

### Fixed
- The server reported an empty version in its MCP `serverInfo`. It now reports the installed
  package version.

## [0.2.0] - 2026-11-03

### Added
- Optional judge mode: `--judge-url`, `--judge-model`, `--judge-preset`, `--judge-api-key-env`,
  `--judge-timeout`, `--judge-max-calls` flags and matching `ANSWER_CHECK_JUDGE_*` environment
  variables.
- Three measured presets (`qwen27-ar4`, `gemma4-e4b`, `qwen27-nothink`), two defined in this
  package (`gemma4-e4b` and `qwen27-nothink`).
- Per-sentence `checked_by` (`"claims"` or `"judge"`), `judge_label` and `judge_passage`, and the
  report's `judge` object.
- Start probe: verifies the endpoint is reachable and lists the model via `GET /v1/models` before
  accepting requests.
- Call cap (`--judge-max-calls`, default 40) with claim-check fallback for remaining sentences.
- Suggested values restored via claims-only pass for wrong figures rejected by the judge.
- API key is read from an environment variable at call time and never appears in output or errors.

### Changed
- Requires `legal-rag-verifier>=0.5,<0.6`.
- `check_answer` tool's `open_world_hint` is true in judge mode.
- README and package descriptions no longer claim no model call without qualification.

### Evaluation
- Free tests: 42 pass, 4 router tests skip without the index.
- Live smoke on 2026-11-02 against the `qwen27-ar4` judge passed (wrong figure unsupported with
  suggestion, wrong prose claim unsupported, correct answer supported) alongside `legal-rag-verifier`
  stop 78's 138/151.

## [0.1.0] - 2026-11-02

### Added
- `check_answer`: checks figures, citations, Act names, qualifiers, and must/may wording, sentence by
  sentence, with suggestions for unsupported values.
- `resolve_uk_citation`: resolves UK legislation citations against the statute book using a
  `legal-rag-router` index.
- stdio MCP launch.
- Bounded inputs: answer up to 20,000 characters and up to 50 sources with 200,000 characters total.

[0.2.1]: https://github.com/azterizm/answer-check-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/azterizm/answer-check-mcp/compare/0cd3d98...v0.2.0
[0.1.0]: https://github.com/azterizm/answer-check-mcp/tree/0cd3d98
