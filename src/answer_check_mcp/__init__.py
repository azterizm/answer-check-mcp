"""answer-check: an MCP server that checks an answer against its sources."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from answer_check_mcp.presets import PRESETS
from answer_check_mcp.server import JudgeSettings, JudgeUnavailable, build_server

__all__ = ["JudgeSettings", "build_server", "main"]


def _preset(value: str) -> str:
    if value not in PRESETS:
        choices = ", ".join(sorted(PRESETS))
        raise argparse.ArgumentTypeError(
            f"unknown judge preset {value!r}; choose one of: {choices}"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(prog="answer-check-mcp", description=__doc__)
    parser.add_argument(
        "--uk-index",
        type=Path,
        default=os.environ.get("ANSWER_CHECK_UK_INDEX"),
        help="legal-rag-router index directory; enables resolve_uk_citation",
    )
    parser.add_argument("--judge-url", default=os.environ.get("ANSWER_CHECK_JUDGE_URL"))
    parser.add_argument("--judge-model", default=os.environ.get("ANSWER_CHECK_JUDGE_MODEL"))
    parser.add_argument(
        "--judge-preset",
        type=_preset,
        choices=sorted(PRESETS),
        default=os.environ.get("ANSWER_CHECK_JUDGE_PRESET"),
    )
    parser.add_argument(
        "--judge-api-key-env", default=os.environ.get("ANSWER_CHECK_JUDGE_API_KEY_ENV")
    )
    parser.add_argument(
        "--judge-timeout",
        type=float,
        default=os.environ.get("ANSWER_CHECK_JUDGE_TIMEOUT", 30),
    )
    parser.add_argument(
        "--judge-max-calls",
        type=int,
        default=os.environ.get("ANSWER_CHECK_JUDGE_MAX_CALLS", 40),
    )
    args = parser.parse_args()

    if not args.judge_url and (args.judge_model or args.judge_preset):
        parser.error("--judge-model and --judge-preset need --judge-url")

    judge = None
    if args.judge_url:
        try:
            judge = JudgeSettings(
                url=args.judge_url,
                model=args.judge_model,
                preset=args.judge_preset,
                api_key_env=args.judge_api_key_env,
                timeout=args.judge_timeout,
                max_calls=args.judge_max_calls,
            )
        except ValueError as exc:
            parser.error(str(exc))

    try:
        build_server(args.uk_index, judge).run()
    except JudgeUnavailable as exc:
        print(f"answer-check-mcp: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
