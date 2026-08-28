"""Prompt-mode contracts shared by benchmark construction and experiment runs."""

from __future__ import annotations

from enum import Enum
from typing import Final


class PromptMode(str, Enum):
    """Model-visible context supplied with each SQL query."""

    SCHEMA_AWARE = "schema_aware"
    QUERY_ONLY = "query_only"


PROMPT_MODES: Final[tuple[PromptMode, ...]] = tuple(PromptMode)


SFT_FILENAMES_BY_PROMPT_MODE: Final[dict[PromptMode, dict[str, str]]] = {
    PromptMode.SCHEMA_AWARE: {
        "train_sqls.json": "train_datas_schema_aware_openai_format.jsonl",
        "valid_sqls.json": "valid_datas_schema_aware_openai_format.jsonl",
        "test_sqls.json": "test_datas_schema_aware_openai_format.jsonl",
    },
    PromptMode.QUERY_ONLY: {
        "train_sqls.json": "train_datas_query_only_openai_format.jsonl",
        "valid_sqls.json": "valid_datas_query_only_openai_format.jsonl",
        "test_sqls.json": "test_datas_query_only_openai_format.jsonl",
    },
}


def parse_prompt_mode(value: PromptMode | str) -> PromptMode:
    """Return a validated prompt mode with a useful error for invalid input."""
    if isinstance(value, PromptMode):
        return value
    try:
        return PromptMode(value)
    except ValueError as error:
        supported = ", ".join(mode.value for mode in PROMPT_MODES)
        raise ValueError(
            f"Unsupported prompt_mode {value!r}; expected one of: {supported}"
        ) from error


def sft_filename(source_sql_filename: str, prompt_mode: PromptMode | str) -> str:
    """Return the SFT artifact name for one raw SQL split and prompt mode."""
    mode = parse_prompt_mode(prompt_mode)
    try:
        return SFT_FILENAMES_BY_PROMPT_MODE[mode][source_sql_filename]
    except KeyError as error:
        raise ValueError(f"Unsupported benchmark SQL file: {source_sql_filename}") from error


def all_sft_filenames() -> frozenset[str]:
    """Return every mode-specific SFT artifact filename."""
    return frozenset(
        filename
        for filenames in SFT_FILENAMES_BY_PROMPT_MODE.values()
        for filename in filenames.values()
    )
