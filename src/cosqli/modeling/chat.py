"""Shared Qwen chat rendering, encoding, and token-length helpers."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Sequence


TOKEN_LENGTH_THRESHOLDS = (2048, 4300)


def _require_messages(messages: Sequence[Dict[str, Any]]) -> None:
    if len(messages) < 3:
        raise ValueError("messages must contain system, user, and assistant turns")
    roles = [message.get("role") for message in messages[:3]]
    if roles != ["system", "user", "assistant"]:
        raise ValueError(
            "Co-SQLi messages must begin with system, user, assistant; "
            f"got {roles!r}"
        )


def _require_chat_template(tokenizer: Any) -> None:
    if not callable(getattr(tokenizer, "apply_chat_template", None)):
        raise ValueError("The configured tokenizer does not provide apply_chat_template")
    if not getattr(tokenizer, "chat_template", None):
        raise ValueError("The configured Qwen tokenizer does not define a chat template")


def render_training_chat(tokenizer: Any, messages: Sequence[Dict[str, Any]]) -> str:
    """Render the complete Qwen conversation used for SFT."""
    _require_messages(messages)
    _require_chat_template(tokenizer)
    return tokenizer.apply_chat_template(
        list(messages),
        tokenize=False,
        add_generation_prompt=False,
    )


def render_inference_chat(tokenizer: Any, messages: Sequence[Dict[str, Any]]) -> str:
    """Render the system/user prefix and open the Qwen assistant turn."""
    _require_messages(messages)
    _require_chat_template(tokenizer)
    return tokenizer.apply_chat_template(
        list(messages[:2]),
        tokenize=False,
        add_generation_prompt=True,
    )


def tokenize_rendered_chat(tokenizer: Any, rendered_chat: str, **kwargs: Any) -> Any:
    """Tokenize a pre-rendered chat without adding special tokens a second time."""
    return tokenizer(rendered_chat, add_special_tokens=False, **kwargs)


def token_ids_from_rendered_chat(tokenizer: Any, rendered_chat: str) -> List[int]:
    """Return untruncated token IDs for a pre-rendered chat string."""
    encoded = tokenize_rendered_chat(tokenizer, rendered_chat)
    input_ids = encoded["input_ids"]
    if hasattr(input_ids, "tolist"):
        input_ids = input_ids.tolist()
    if input_ids and isinstance(input_ids[0], list):
        if len(input_ids) != 1:
            raise ValueError("Expected one rendered chat sequence")
        input_ids = input_ids[0]
    return [int(token_id) for token_id in input_ids]


def assistant_only_labels(full_token_ids: Sequence[int], prompt_token_ids: Sequence[int]) -> List[int]:
    """Mask the rendered inference prefix and retain only assistant-turn targets."""
    prompt_length = len(prompt_token_ids)
    comparable_length = min(len(full_token_ids), prompt_length)
    if (
        list(full_token_ids[:comparable_length])
        != list(prompt_token_ids[:comparable_length])
    ):
        raise ValueError(
            "The training chat does not begin with the inference chat token prefix"
        )
    labels = [int(token_id) for token_id in full_token_ids]
    labels[:prompt_length] = [-100] * min(prompt_length, len(labels))
    return labels


def _percentile(sorted_values: List[int], percentile: float) -> int:
    if not sorted_values:
        return 0
    index = max(0, math.ceil(percentile * len(sorted_values)) - 1)
    return sorted_values[index]


def collect_message_tokenization_stats(
    examples: Iterable[Dict[str, Any]],
    tokenizer: Any,
    max_seq_length: int,
    *,
    purpose: str,
) -> Dict[str, Any]:
    """Measure rendered-chat lengths before truncation for one dataset split."""
    if purpose not in {"training", "inference"}:
        raise ValueError(f"Unsupported tokenization purpose: {purpose!r}")

    lengths: List[int] = []
    truncated_at_limit = 0
    assistant_label_truncated = 0
    assistant_label_fully_truncated = 0

    for example in examples:
        messages = example.get("messages")
        if not isinstance(messages, list):
            raise ValueError("Tokenization statistics require an OpenAI messages field")

        prompt_ids = token_ids_from_rendered_chat(
            tokenizer, render_inference_chat(tokenizer, messages)
        )
        if purpose == "training":
            full_ids = token_ids_from_rendered_chat(
                tokenizer, render_training_chat(tokenizer, messages)
            )
            assistant_only_labels(full_ids, prompt_ids)
            length = len(full_ids)
            retained_length = min(length, max_seq_length)
            assistant_tokens = len(full_ids) - len(prompt_ids)
            if assistant_tokens <= 0:
                raise ValueError("Training chat has no assistant target tokens")
            if length > max_seq_length:
                truncated_at_limit += 1
            if retained_length < length and retained_length > len(prompt_ids):
                assistant_label_truncated += 1
            if retained_length <= len(prompt_ids):
                assistant_label_fully_truncated += 1
        else:
            length = len(prompt_ids)
            if length > max_seq_length:
                truncated_at_limit += 1

        lengths.append(length)

    ordered = sorted(lengths)
    stats: Dict[str, Any] = {
        "purpose": purpose,
        "measurement": "full_training_chat" if purpose == "training" else "inference_prompt",
        "total_examples": len(lengths),
        "max_seq_length": max_seq_length,
        "min": ordered[0] if ordered else 0,
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1] if ordered else 0,
        "mean": (sum(lengths) / len(lengths)) if lengths else 0.0,
        "over_2048": sum(length > 2048 for length in lengths),
        "over_4300": sum(length > 4300 for length in lengths),
        "truncated_at_max_seq_length": truncated_at_limit,
    }
    if purpose == "training":
        stats.update(
            {
                "assistant_label_truncated": assistant_label_truncated,
                "assistant_label_fully_truncated": assistant_label_fully_truncated,
            }
        )
    return stats
