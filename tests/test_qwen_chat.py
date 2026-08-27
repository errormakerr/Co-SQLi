"""Regression tests for native Qwen chat rendering and label masking."""

from __future__ import annotations

import unittest

from cosqli.modeling.chat import (
    assistant_only_labels,
    collect_message_tokenization_stats,
    render_inference_chat,
    render_training_chat,
    token_ids_from_rendered_chat,
    tokenize_rendered_chat,
)


class FakeQwenTokenizer:
    """Small tokenizer double that exposes accidental second special tokens."""

    chat_template = "native-qwen-template"

    def __init__(self) -> None:
        self.add_special_tokens_calls = []

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        self.assertFalse(tokenize)
        rendered = "".join(
            "<|im_start|>{}\n{}<|im_end|>\n".format(
                message["role"], message["content"]
            )
            for message in messages
        )
        if add_generation_prompt:
            rendered += "<|im_start|>assistant\n"
        return rendered

    def assertFalse(self, value):
        if value:
            raise AssertionError("The test double only supports text rendering")

    def __call__(self, text, *, add_special_tokens=True, **_kwargs):
        self.add_special_tokens_calls.append(add_special_tokens)
        token_ids = [ord(char) for char in text]
        if add_special_tokens:
            token_ids.insert(0, 999)
        return {"input_ids": token_ids}


MESSAGES = [
    {"role": "system", "content": "Classify SQL."},
    {"role": "user", "content": "SELECT 1"},
    {"role": "assistant", "content": "benign"},
]


class QwenChatTests(unittest.TestCase):
    def test_training_and_inference_share_an_exact_token_prefix(self) -> None:
        tokenizer = FakeQwenTokenizer()
        training = render_training_chat(tokenizer, MESSAGES)
        inference = render_inference_chat(tokenizer, MESSAGES)

        self.assertTrue(training.startswith(inference))
        training_ids = token_ids_from_rendered_chat(tokenizer, training)
        inference_ids = token_ids_from_rendered_chat(tokenizer, inference)
        self.assertEqual(training_ids[: len(inference_ids)], inference_ids)
        self.assertEqual(tokenizer.add_special_tokens_calls, [False, False])

    def test_assistant_only_labels_mask_the_full_prompt(self) -> None:
        tokenizer = FakeQwenTokenizer()
        training_ids = token_ids_from_rendered_chat(
            tokenizer, render_training_chat(tokenizer, MESSAGES)
        )
        prompt_ids = token_ids_from_rendered_chat(
            tokenizer, render_inference_chat(tokenizer, MESSAGES)
        )
        labels = assistant_only_labels(training_ids, prompt_ids)

        self.assertTrue(all(label == -100 for label in labels[: len(prompt_ids)]))
        self.assertTrue(any(label != -100 for label in labels[len(prompt_ids) :]))

    def test_rendered_chat_encoding_never_adds_special_tokens_again(self) -> None:
        tokenizer = FakeQwenTokenizer()
        tokenize_rendered_chat(tokenizer, "already rendered")
        self.assertEqual(tokenizer.add_special_tokens_calls, [False])

    def test_training_stats_detect_fully_truncated_assistant_targets(self) -> None:
        tokenizer = FakeQwenTokenizer()
        stats = collect_message_tokenization_stats(
            [{"messages": MESSAGES}],
            tokenizer,
            max_seq_length=8,
            purpose="training",
        )
        self.assertEqual(stats["assistant_label_fully_truncated"], 1)
        self.assertEqual(stats["truncated_at_max_seq_length"], 1)


if __name__ == "__main__":
    unittest.main()
