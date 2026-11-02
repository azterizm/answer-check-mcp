"""Measured judge presets available to answer-check-mcp."""

from __future__ import annotations

from types import MappingProxyType

from legal_rag_verifier.judge import PRESETS as LIBRARY_PRESETS
from legal_rag_verifier.judge import PROMPT_SHA, SHORT_SHA, Preset

DEFAULT_PRESET = "qwen27-ar4"
LOCAL_PRESETS: dict[str, Preset] = {
    "gemma4-e4b": Preset(
        model="google/gemma-4-E4B-it",
        revision="ee0ef6023621cff504d758262d4e04895a5af4a2",
        quantisation="none (the published checkpoint)",
        server=(
            "SGLang 0.5.21 (lmsysorg/sglang:v0.5.21), --context-length 65536 "
            "--mem-fraction-static 0.85, one L40S"
        ),
        sampling=MappingProxyType(
            {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "max_tokens": 1024, "seed": 0}
        ),
        template_kwargs=MappingProxyType({"enable_thinking": False}),
        reply="short",
        prompt_sha256=SHORT_SHA,
        figure=(
            "86.4 % (306/354) and 85.4 % (129/151) on the two fresh tests, stop 62, "
            "under STRICT_FIGURES with the short reply; the limit on answers written with "
            "sources was not measured for this judge"
        ),
        measurements=(
            "docs/measurements.md"
            "#two-smaller-judges-untrained-stop-62-2026-10-12-method-in-docsgridmd"
        ),
    ),
    "qwen27-nothink": Preset(
        model="Qwen/Qwen3.8-27B-FP8",
        revision="017b9c7af6b5689d5dd426a76e0bc077eb5ca20a",
        quantisation="FP8 (the official checkpoint)",
        server=(
            "SGLang 0.5.21 (lmsysorg/sglang:v0.5.21), --reasoning-parser qwen3 "
            "--context-length 65536 --mem-fraction-static 0.85, one L40S"
        ),
        sampling=MappingProxyType(
            {
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 20,
                "min_p": 0.0,
                "presence_penalty": 1.5,
                "max_tokens": 1024,
                "seed": 0,
            }
        ),
        template_kwargs=MappingProxyType({"enable_thinking": False}),
        reply="full",
        prompt_sha256=PROMPT_SHA,
        figure=(
            "91.5 % (324/354) and 90.7 % (137/151) on the two fresh tests, stops 55 "
            "and 56, under STRICT_FIGURES with the full reply; stop 56 found a gap on "
            "answers written with sources similar to qwen27-ar4's"
        ),
        measurements=(
            "docs/GRID.md#stop-55-results-2026-10-11; docs/GRID.md#stop-56-results-2026-10-11"
        ),
    ),
}
PRESETS: dict[str, Preset] = {**LIBRARY_PRESETS, **LOCAL_PRESETS}
