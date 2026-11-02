"""answer-check: an MCP server that checks an answer against its sources."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from answer_check_mcp.server import build_server

__all__ = ["build_server", "main"]


def main() -> None:
    parser = argparse.ArgumentParser(prog="answer-check-mcp", description=__doc__)
    parser.add_argument(
        "--uk-index",
        type=Path,
        default=os.environ.get("ANSWER_CHECK_UK_INDEX"),
        help="legal-rag-router index directory; enables resolve_uk_citation",
    )
    args = parser.parse_args()
    build_server(args.uk_index).run()
