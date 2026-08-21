#!/usr/bin/env python
# coding=utf-8
"""
LoRA / QLoRA Fine-Tuning Script

Supervised fine-tuning of a causal language model using LoRA (or QLoRA) and
HuggingFace Accelerate for multi-GPU training.

This script is launched via ``accelerate launch`` from ``Defender.run_finetune()``
and should not typically be invoked directly.

Supported training data formats:
- ``prompt`` + ``completion`` fields (instruction-completion format).
- ``messages`` field (OpenAI conversation format).
"""
import sys
import argparse
import logging
import math
import os
import random
import datasets
from datetime import timedelta
import torch
from functools import partial
from accelerate import Accelerator
from accelerate.logging import get_logger
from accelerate.utils import DistributedType, set_seed, InitProcessGroupKwargs
from datasets import load_dataset
from torch.utils.data import DataLoader
from tqdm.auto import tqdm
import deepspeed
import numpy as np

import transformers
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoTokenizer,
    LlamaTokenizer,
    LlamaTokenizerFast,
    SchedulerType,
    DataCollatorForSeq2Seq,
    get_scheduler,
    GPTNeoXTokenizerFast,
    GPT2Tokenizer,
    OPTForCausalLM,
    BitsAndBytesConfig
)
from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training

def str2bool(value: str) -> bool:
    """Convert a string representation of a boolean to a Python bool."""
    if isinstance(value, bool):
        return value
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got {value!r}.")

class TemporarilySeededRandom:
    """Context manager that temporarily overrides the global random seed."""

    def __init__(self, seed: int) -> None:
        """
        Args:
            seed: The seed to use inside the context.
        """
        self.seed = seed
        self.stored_state = None
        self.stored_np_state = None

    def __enter__(self):
        # Store the current random state
        self.stored_state = random.getstate()
        self.stored_np_state = np.random.get_state()

        # Set the random seed
        random.seed(self.seed)
        np.random.seed(self.seed)

    def __exit__(self, exc_type, exc_value, traceback):
        # Restore the random state
        random.setstate(self.stored_state)
        np.random.set_state(self.stored_np_state)

def get_random_k_indices(data, data_prop: float, seed: int = 42):
    """
    Sample a random proportion of non-masked token positions from *data*.

    Args:
        data:      Nested list of label tensors (``-100`` entries are masked).
        data_prop: Fraction (0–1) of non-masked tokens to retain.
        seed:      Random seed for reproducibility.

    Returns:
        List of ``(sample_idx, token_idx)`` tuples for the selected tokens.
    """
    flattened = [
        (value, i, j)
        for i, sublist in enumerate(data)
        for j, value in enumerate(sublist)
        if value != -100
    ]
    with TemporarilySeededRandom(seed):
        random_k = random.sample(flattened, int(len(flattened) * data_prop))
    return [(item[1], item[2]) for item in random_k]

logger = get_logger(__name__)

def encode_with_prompt_completion_format(example, tokenizer, max_seq_length, with_prompt_token, add_bos=False):
    """
    Tokenise a ``prompt``/``completion`` example.

    The prompt and completion are concatenated *before* tokenisation so that
    the prompt is not padded/truncated independently.  The prompt portion of
    the labels is masked (set to -100) unless *with_prompt_token* is True.
    """
    # Ensure there is a whitespace boundary between prompt and completion
    if (
        not example["prompt"].endswith((" ", "\n", "\t"))
        and not example["completion"].startswith((" ", "\n", "\t"))
    ):
        example_text = example["prompt"] + " " + example["completion"]
    else:
        example_text = example["prompt"] + example["completion"]

    example_text = example_text + tokenizer.eos_token
    if add_bos:
        example_text = tokenizer.bos_token + example_text

    tokenized_example = tokenizer(
        example_text, return_tensors="pt", max_length=max_seq_length, truncation=True
    )
    input_ids = tokenized_example.input_ids
    labels = input_ids.clone()

    tokenized_prompt = tokenizer(
        example["prompt"], return_tensors="pt", max_length=max_seq_length, truncation=True
    )
    if not with_prompt_token:
        # Mask prompt tokens so the loss is only computed on the completion
        labels[:, : tokenized_prompt.input_ids.shape[1]] = -100

    attention_mask = torch.ones_like(input_ids)
    return {
        "input_ids": input_ids.flatten(),
        "labels": labels.flatten(),
        "attention_mask": attention_mask.flatten(),
    }

def encode_with_messages_format(example, tokenizer, max_seq_length, with_prompt_token, add_bos=False):
    """
    Tokenise an OpenAI-style ``messages`` example.

    All messages are concatenated with role delimiters and tokenised together.
    Non-assistant turn tokens are masked in the labels (set to -100) unless
    *with_prompt_token* is True.
    """
    messages = example["messages"]
    if len(messages) == 0:
        raise ValueError("messages field is empty.")

    def _concat_messages(msgs):
        text = ""
        for msg in msgs:
            if msg["role"] == "system":
                text += "<|system|>\n" + msg["content"].strip() + "\n"
            elif msg["role"] == "user":
                text += "<|user|>\n" + msg["content"].strip() + "\n"
            elif msg["role"] == "assistant":
                text += "<|assistant|>\n" + msg["content"].strip() + tokenizer.eos_token + "\n"
            else:
                raise ValueError(f"Invalid role: {msg['role']!r}")
        return text

    example_text = _concat_messages(messages).strip()
    if add_bos:
        example_text = tokenizer.bos_token + example_text

    tokenized_example = tokenizer(
        example_text, return_tensors="pt", max_length=max_seq_length, truncation=True
    )
    input_ids = tokenized_example.input_ids
    labels = input_ids.clone()

    # Mask non-assistant turns so the loss is only computed on assistant tokens
    for message_idx, message in enumerate(messages):
        if message["role"] != "assistant":
            message_start_idx = (
                0
                if message_idx == 0
                else tokenizer(
                    _concat_messages(messages[:message_idx]),
                    return_tensors="pt",
                    max_length=max_seq_length,
                    truncation=True,
                ).input_ids.shape[1]
            )
            # Include the assistant role tag in the masked region so it is
            # not used for loss computation either.
            if (
                message_idx < len(messages) - 1
                and messages[message_idx + 1]["role"] == "assistant"
            ):
                messages_so_far = _concat_messages(messages[: message_idx + 1]) + "<|assistant|>\n"
            else:
                messages_so_far = _concat_messages(messages[: message_idx + 1])

            message_end_idx = tokenizer(
                messages_so_far,
                return_tensors="pt",
                max_length=max_seq_length,
                truncation=True,
            ).input_ids.shape[1]

            if not with_prompt_token:
                labels[:, message_start_idx:message_end_idx] = -100

            if message_end_idx >= max_seq_length:
                break

    attention_mask = torch.ones_like(input_ids)
    return {
        "input_ids": input_ids.flatten(),
        "labels": labels.flatten(),
        "attention_mask": attention_mask.flatten(),
    }

def save_with_accelerate(accelerator, model, tokenizer, output_dir, args):
    """
    Save model weights (and tokenizer) using Accelerate's state-dict helpers.

    When using multi-GPU training the state dict must be gathered across all
    processes via ``accelerator.get_state_dict()`` to avoid saving only a
    partial shard.  LoRA models use ``PeftModel.save_pretrained()`` which
    handles adapter-only saving automatically.
    """
    # Use an empty GenerationConfig to avoid errors when saving; greedy
    # decoding does not require any generation config fields.
    model.generation_config = transformers.GenerationConfig(
        temperature=None,
        top_p=None,
        eos_token_id=tokenizer.eos_token_id,
        bos_token_id=tokenizer.bos_token_id
    )

    unwrapped_model = accelerator.unwrap_model(model)
    # When doing multi-gpu training, we need to use accelerator.get_state_dict(model) to get the state_dict.
    # Otherwise, sometimes the model will be saved with only part of the parameters.
    # Also, accelerator needs to use the wrapped model to get the state_dict.
    state_dict = accelerator.get_state_dict(model)
    if args.use_lora:
        # When using lora, the unwrapped model is a PeftModel, which doesn't support the is_main_process 
        # and has its own save_pretrained function for only saving lora modules.
        # We have to manually specify the is_main_process outside the save_pretrained function.
        if accelerator.is_main_process:
            unwrapped_model.save_pretrained(output_dir, state_dict=state_dict)
    else:
        # don't use safetensors for saving for now
        unwrapped_model.save_pretrained(
            output_dir, is_main_process=accelerator.is_main_process, save_function=accelerator.save, state_dict=state_dict,
            safe_serialization=False
        )

def _setup_accelerator(args):
    """Initialise Accelerator, configure logging, and set the random seed."""
    accelerator_log_kwargs = {}

    if args.with_tracking:
        accelerator_log_kwargs["log_with"] = args.report_to
        accelerator_log_kwargs["project_dir"] = args.output_dir

    # if you get timeouts (e.g. due to long tokenization) increase this.
    timeout_kwargs = InitProcessGroupKwargs(timeout=timedelta(seconds=args.timeout))

    accelerator = Accelerator(
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        **accelerator_log_kwargs,
        kwargs_handlers=[timeout_kwargs]
    )
    # Make one log on every process with the configuration for debugging.
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        level=logging.INFO,
    )
    logger.info(accelerator.state, main_process_only=False)
    if accelerator.is_local_main_process:
        datasets.utils.logging.set_verbosity_warning()
        transformers.utils.logging.set_verbosity_info()
    else:
        datasets.utils.logging.set_verbosity_error()
        transformers.utils.logging.set_verbosity_error()

    if args.seed is not None:
        set_seed(args.seed)

    if accelerator.is_main_process and args.output_dir is not None:
        os.makedirs(args.output_dir, exist_ok=True)

    accelerator.wait_for_everyone()
    return accelerator


def _load_raw_datasets(args):
    """Load raw datasets from HuggingFace or a local JSON file."""
    if args.dataset_name is not None:
        return load_dataset(
            args.dataset_name,
            args.dataset_config_name,
        )
    data_files = {}
    dataset_args = {}
    if args.train_file is not None:
        data_files["train"] = args.train_file
    return load_dataset(
        "json",
        data_files=data_files,
        **dataset_args,
    )


def _load_model_and_tokenizer(args, accelerator):
    """Load model config, tokenizer, model, handle special tokens, and apply LoRA."""
    # --- Load model configuration ---
    if args.config_name:
        config = AutoConfig.from_pretrained(
            args.config_name,
            trust_remote_code=args.trust_remote_code,
            revision=args.model_revision,
            token=os.getenv("HF_TOKEN", None)
        )
    elif args.model_name_or_path:
        config = AutoConfig.from_pretrained(
            args.model_name_or_path,
            trust_remote_code=args.trust_remote_code,
            revision=args.model_revision,
            token=os.getenv("HF_TOKEN", None)
        )
    else:
        raise ValueError(
            "You are instantiating a new config instance from scratch. This is not supported by this script."
        )

    tokenizer_revision = (
        args.model_revision if args.tokenizer_revision is None else args.tokenizer_revision
    )
    if tokenizer_revision != args.model_revision:
        logger.warning(
            f"Requested tokenizer revision `{tokenizer_revision}` differs from "
            f"model revision `{args.model_revision}`."
        )

    # --- Load tokenizer ---
    if args.tokenizer_name:
        tokenizer = AutoTokenizer.from_pretrained(
            args.tokenizer_name,
            trust_remote_code=args.trust_remote_code,
            use_fast=not args.use_slow_tokenizer,
            revision=tokenizer_revision,
            token=os.getenv("HF_TOKEN", None),
        )
        
    elif args.model_name_or_path:
        
        tokenizer = AutoTokenizer.from_pretrained(
            args.model_name_or_path,
            trust_remote_code=args.trust_remote_code,
            use_fast=not args.use_slow_tokenizer,
            revision=tokenizer_revision,
            token=os.getenv("HF_TOKEN", None),

        )
    else:
        raise ValueError(
            "You are instantiating a new tokenizer from scratch. This is not supported by this script."
            "You can do it from another script, save it, and load it from here, using --tokenizer_name."
        )

    # --- Load model ---
    if args.model_name_or_path:
        if args.use_qlora:
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            model = AutoModelForCausalLM.from_pretrained(
                args.model_name_or_path,
                from_tf=bool(".ckpt" in args.model_name_or_path),
                config=config,
                quantization_config=bnb_config,
                trust_remote_code=args.trust_remote_code,
                torch_dtype=torch.bfloat16,
                # use_flash_attention_2=True if args.use_flash_attn else False,
                revision=args.model_revision,
                token=os.getenv("HF_TOKEN", None),
            )
        else:
            model = AutoModelForCausalLM.from_pretrained(
                args.model_name_or_path,
                from_tf=bool(".ckpt" in args.model_name_or_path),
                config=config,
                trust_remote_code=args.trust_remote_code,
                low_cpu_mem_usage=args.low_cpu_mem_usage,
                # use_flash_attention_2=True if args.use_flash_attn else False,
                revision=args.model_revision,
                token=os.getenv("HF_TOKEN", None),
            )
    else:
        logger.info("Training new model from scratch.")
        model = AutoModelForCausalLM.from_config(config)

    # --- Special-token handling ---
    # LlamaTokenizer does not include a pad token by default; add one.
    if isinstance(tokenizer, LlamaTokenizer) or isinstance(tokenizer, LlamaTokenizerFast):
        num_added_tokens = tokenizer.add_special_tokens({
            "bos_token": "<s>",
            "eos_token": "</s>",
            "unk_token": "<unk>",
            "pad_token": "<pad>",
        })
        assert num_added_tokens in [0, 1], "LlamaTokenizer should only add one special token - the pad_token, or no tokens if pad token present."
    elif isinstance(tokenizer, GPTNeoXTokenizerFast):
        # OLMo newer models use this tokenizer
        if tokenizer.bos_token is None:
            tokenizer.bos_token = tokenizer.eos_token
            assert args.add_bos, "For OLMo with GPTNeoX, you must add bos token to the beginning of the input sequence."
        # else, pythia / other models
        else:
            num_added_tokens = tokenizer.add_special_tokens({
                "pad_token": "<pad>",
            })
            assert num_added_tokens == 1, "GPTNeoXTokenizer should only add one special token - the pad_token."
    elif isinstance(tokenizer, GPT2Tokenizer) and isinstance(model, OPTForCausalLM):
        num_added_tokens = tokenizer.add_special_tokens({'unk_token': '<unk>'})
    elif isinstance(tokenizer, transformers.PreTrainedTokenizerFast) and tokenizer.pad_token is None:
        num_added_tokens = tokenizer.add_special_tokens({'pad_token': '<pad>'})
        assert num_added_tokens == 1, "We detected no padding token but add_special_tokens did not add one."

    # --- Resize token embeddings if necessary ---
    # Gather the actual embedding size across DeepSpeed ZeRO shards before comparing.
    embeddings = model.get_input_embeddings()
    with deepspeed.zero.GatheredParameters(embeddings.weight, modifier_rank=None):
        embedding_size = embeddings.weight.shape[0]
    # resize does its own gather
    
    if len(tokenizer) > embedding_size:
        # Pad to a multiple of 8 for optimal tensor-core utilisation.
        model.resize_token_embeddings(len(tokenizer), pad_to_multiple_of=8)
    # Re-read embedding size after potential resize (needed for the sum-loss path).
    embeddings = model.get_input_embeddings()
    with deepspeed.zero.GatheredParameters(embeddings.weight, modifier_rank=None):
        embedding_size = embeddings.weight.shape[0]

    # Set the tokenizer chat template (Tulu / Open-Instruct format).
    # This ensures consistent prompt formatting during both training and evaluation.
    tokenizer.chat_template = (  # noqa: E501
        "{% for message in messages %}\n"
        "{% if message['role'] == 'user' %}\n"
        "{{ '<|user|>\n' + message['content'] }}\n"
        "{% elif message['role'] == 'assistant' %}\n"
        "{{ '<|assistant|>\n'  + message['content'] + eos_token }}\n"
        "{% endif %}\n"
        "{% if loop.last and add_generation_prompt %}\n"
        "{{ '<|assistant|>' }}\n"
        "{% endif %}\n"
        "{% endfor %}"
    )
    if args.add_bos:
        tokenizer.chat_template = "{{ bos_token }}" + tokenizer.chat_template


    # --- LoRA / QLoRA setup ---
    if args.use_lora:
        if args.gradient_checkpointing:
            model.gradient_checkpointing_enable()
        if args.use_qlora:
            model = prepare_model_for_kbit_training(
                model, use_gradient_checkpointing=args.gradient_checkpointing
            )
        logger.info("Initializing LoRA model...")
        peft_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            inference_mode=False,
            r=args.lora_rank,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            target_modules=["q_proj", "o_proj", "v_proj", "k_proj", "gate_proj", "up_proj", "down_proj"],
        )
        model = get_peft_model(model, peft_config)

        # PEFT creates new LoRA parameters in torch.float32 by default, even
        # when from_pretrained() loaded the base model in bfloat16. FSDP flattens
        # parameters within each wrapped module and requires a uniform dtype.
        # Convert the complete non-quantized model before accelerator.prepare()
        # so that both the frozen base weights and the LoRA adapters agree.
        if (
            accelerator.distributed_type == DistributedType.FSDP
            and not args.use_qlora
            and accelerator.mixed_precision == "bf16"
        ):
            model = model.to(dtype=torch.bfloat16)
            logger.info("Cast LoRA model to bfloat16 for FSDP parameter flattening.")
        model.print_trainable_parameters()
    elif args.gradient_checkpointing:
        model.gradient_checkpointing_enable()

    return model, tokenizer, embedding_size


def _encode_and_prepare_dataset(args, raw_datasets, model, tokenizer, accelerator):
    """Encode raw datasets into tokenised training tensors and apply token selection."""
    # --- Dataset encoding ---
    if "prompt" in raw_datasets["train"].column_names and "completion" in raw_datasets["train"].column_names:
        encode_function = partial(
            encode_with_prompt_completion_format,
            tokenizer=tokenizer,
            max_seq_length=args.max_seq_length,
            with_prompt_token=args.with_prompt_token,
            add_bos=args.add_bos,
        )

    elif "messages" in raw_datasets["train"].column_names:
        encode_function = partial(
            encode_with_messages_format,
            tokenizer=tokenizer,
            max_seq_length=args.max_seq_length,
            with_prompt_token=args.with_prompt_token,
            add_bos=args.add_bos,
        )
    else:
        raise ValueError("You need to have either 'prompt'&'completion' or 'messages' in your column names.")
    
    # NOTE: main_process_first() removed to avoid FSDP barrier deadlock.
    # With small datasets (e.g. 300 samples) each rank can tokenise independently.
    raw_datasets = raw_datasets.map(
        lambda example, idx: {"idx": idx},
        with_indices=True,
        num_proc=args.preprocessing_num_workers,
        desc="Adding idx column",
    )
    lm_datasets = raw_datasets.map(
        encode_function,
        batched=False,
        num_proc=args.preprocessing_num_workers,
        load_from_cache_file=not args.overwrite_cache,
        remove_columns=[
            name
            for name in raw_datasets["train"].column_names
            if name not in ["idx", "input_ids", "labels", "attention_mask"]
        ],
        desc="Tokenizing and reformatting instruction data",
    )
    lm_datasets.set_format(type="pt")
    accelerator.wait_for_everyone()

    if args.with_prompt_token:
        print("*** Training with prompt tokens included in loss. ***")

    train_dataset = lm_datasets["train"]
    orig_labels = train_dataset["labels"]

    # --- Token selection strategy ---
    if args.token_select_pattern == "token_cleaning":
        print("*** Token selection: token_cleaning ***")
        selected_labels = torch.load(
            args.label_path + f"token_labels_{args.train_data_tag}.pt"
        )
    elif args.token_select_pattern == "random":
        print("*** Token selection: random ***")
        selected_labels = [[-100] * len(label) for label in orig_labels]
        random_tokens_indices = get_random_k_indices(orig_labels, args.data_prop)
        selected_sample_idxs = {item[0] for item in random_tokens_indices}
        print(
            f"Selected {len(selected_sample_idxs)} samples "
            f"(out of {len(orig_labels)} total)."
        )
        for i, j in random_tokens_indices:
            selected_labels[i][j] = orig_labels[i][j].item()
    elif args.token_select_pattern == "default":
        print("*** Token selection: default (all tokens) ***")
        selected_labels = orig_labels
    else:
        raise NotImplementedError(
            f"Unsupported token_select_pattern: {args.token_select_pattern!r}"
        )

    train_dataset = train_dataset.map(
        lambda examples, idx: {"labels": selected_labels[idx]},
        with_indices=True,
    )

    return train_dataset


def _build_optimizer_and_scheduler(args, model, tokenizer, train_dataset, accelerator):
    """Create DataLoader, optimiser, LR scheduler, and prepare with accelerator."""
    # --- DataLoaders ---
    train_dataloader = DataLoader(
        train_dataset,
        shuffle=True,
        collate_fn=DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model, padding="longest"),
        batch_size=args.per_device_train_batch_size
    )

    # --- Optimiser ---
    # Parameters with "bias" or "layer_norm.weight" in their name are excluded
    # from weight decay following standard practice.
    no_decay = ["bias", "layer_norm.weight"]
    optimizer_grouped_parameters = [
        {
            "params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)],
            "weight_decay": args.weight_decay,
        },
        {
            "params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)],
            "weight_decay": 0.0,
        },
    ]
    if args.use_qlora:
        from bitsandbytes.optim import AdamW
        optimizer = AdamW(
            optimizer_grouped_parameters,
            lr=args.learning_rate,
            optim_bits=8 if args.use_8bit_optimizer else 32,
            is_paged=True
        )
    else:
        optimizer = torch.optim.AdamW(optimizer_grouped_parameters, lr=args.learning_rate)

    # --- LR Scheduler ---
    overrode_max_train_steps = False
    num_update_steps_per_epoch = math.ceil(len(train_dataloader) / args.gradient_accumulation_steps)
    if args.max_train_steps is None:
        args.max_train_steps = args.num_train_epochs * num_update_steps_per_epoch
        overrode_max_train_steps = True

    # ``accelerator.step()`` calls the real scheduler ``num_processes`` times per
    # global update step (once per process).  To compensate, the scheduler is
    # initialised with ``max_train_steps * num_processes`` when the user
    # specifies a fixed step count rather than epoch-derived steps.
    num_training_steps_for_scheduler = (
        args.max_train_steps
        if overrode_max_train_steps
        else args.max_train_steps * accelerator.num_processes
    )
    lr_scheduler = get_scheduler(
        name=args.lr_scheduler_type,
        optimizer=optimizer,
        num_training_steps=num_training_steps_for_scheduler,
        num_warmup_steps=int(num_training_steps_for_scheduler * args.warmup_ratio),
    )

    # --- Accelerate preparation ---
    model, optimizer, train_dataloader, lr_scheduler = accelerator.prepare(
        model, optimizer, train_dataloader, lr_scheduler
    )

    # Recalculate step / epoch counts after DataLoader size is known.
    num_update_steps_per_epoch = math.ceil(
        len(train_dataloader) / args.gradient_accumulation_steps
    )
    if overrode_max_train_steps:
        args.max_train_steps = args.num_train_epochs * num_update_steps_per_epoch
    args.num_train_epochs = math.ceil(args.max_train_steps / num_update_steps_per_epoch)

    checkpointing_steps = args.checkpointing_steps
    if checkpointing_steps is not None and checkpointing_steps.isdigit():
        checkpointing_steps = int(checkpointing_steps)

    if args.with_tracking:
        experiment_config = vars(args).copy()
        v = experiment_config["lr_scheduler_type"]
        if isinstance(v, SchedulerType):
            experiment_config["lr_scheduler_type"] = v.value
        else:
            experiment_config["lr_scheduler_type"] = str(v)
        # TensorBoard add_hparams only accepts int/float/str/bool/Tensor.
        # Convert any list or other unsupported types to strings.
        for k, val in experiment_config.items():
            if not isinstance(val, (int, float, str, bool, type(None))):
                experiment_config[k] = str(val)
        accelerator.init_trackers(
            "open_instruct_sft",
            experiment_config,
            init_kwargs={"wandb": {"entity": args.wandb_entity}}
        )

    return model, optimizer, train_dataloader, lr_scheduler, checkpointing_steps


def _training_loop(args, model, tokenizer, train_dataset, train_dataloader,
                   optimizer, lr_scheduler, accelerator, checkpointing_steps,
                   embedding_size):
    """Execute the main training loop with checkpointing and optional tracking."""
    # --- Training loop ---
    total_batch_size = (
        args.per_device_train_batch_size
        * accelerator.num_processes
        * args.gradient_accumulation_steps
    )
    logger.info("***** Running training *****")
    logger.info(f"  Num examples            = {len(train_dataset)}")
    logger.info(f"  Num epochs              = {args.num_train_epochs}")
    logger.info(f"  Batch size per device   = {args.per_device_train_batch_size}")
    logger.info(f"  Total batch size        = {total_batch_size}")
    logger.info(f"  Gradient accum steps    = {args.gradient_accumulation_steps}")
    logger.info(f"  Total optimisation steps = {args.max_train_steps}")

    # Progress bar is shown only on the local main process.
    progress_bar = tqdm(range(args.max_train_steps), disable=not accelerator.is_local_main_process)
    completed_steps = 0
    starting_epoch = 0

    # --- Resume from checkpoint (optional) ---
    if args.resume_from_checkpoint:
        if args.resume_from_checkpoint is not None and args.resume_from_checkpoint != "":
            checkpoint_path = args.resume_from_checkpoint
            path = os.path.basename(args.resume_from_checkpoint)
        else:
            # Get the most recent checkpoint
            dirs = [f.name for f in os.scandir(os.getcwd()) if f.is_dir()]
            dirs.sort(key=os.path.getctime)
            path = dirs[
                -1
            ]  # Sorts folders by date modified, most recent checkpoint is the last
            checkpoint_path = path
            path = os.path.basename(checkpoint_path)

        accelerator.print(f"Resumed from checkpoint: {checkpoint_path}")
        accelerator.load_state(path)
        training_difference = os.path.splitext(path)[0]

        if "epoch" in training_difference:
            starting_epoch = int(training_difference.replace("epoch_", "")) + 1
            resume_step = None
            completed_steps = starting_epoch * num_update_steps_per_epoch
        else:
            # Multiply by gradient_accumulation_steps to get the real dataloader step count.
            resume_step = (
                int(training_difference.replace("step_", ""))
                * args.gradient_accumulation_steps
            )
            starting_epoch = resume_step // len(train_dataloader)
            completed_steps = resume_step // args.gradient_accumulation_steps
            resume_step -= starting_epoch * len(train_dataloader)

    progress_bar.update(completed_steps)
    
    for epoch in range(starting_epoch, args.num_train_epochs):
        model.train()
        total_loss = 0
        if (
            args.resume_from_checkpoint
            and epoch == starting_epoch
            and resume_step is not None
        ):
            # We skip the first `n` batches in the dataloader when resuming from a checkpoint
            active_dataloader = accelerator.skip_first_batches(
                train_dataloader, resume_step
            )
        else:
            active_dataloader = train_dataloader
            
        
        for step, batch in enumerate(active_dataloader):
            with accelerator.accumulate(model):
                outputs = model(input_ids=batch['input_ids'], labels=batch['labels'], attention_mask=batch['attention_mask'], use_cache=False)

                if args.reduce_loss == 'mean':
                    loss = outputs.loss
                else:
                    # reduce loss is sum
                    # this ensures that we weight all tokens in the dataset equally,
                    # rather than weighting each overall example equally when
                    # using high amounts of gradient accumulation.
                    # this can result in > 5 point improvements in AlpacaEval
                    # see https://github.com/huggingface/transformers/issues/24725 for
                    # more discussion and details.
                    
                    logits = outputs.logits

                    labels = batch["labels"]
                    # Shift so that tokens < n predict n
                    shift_logits = logits[..., :-1, :].contiguous()
                    shift_labels = labels[..., 1:].contiguous()
                    # Flatten the tokens
                    loss_fct = torch.nn.CrossEntropyLoss(reduction='sum', ignore_index=-100)
                    shift_logits = shift_logits.view(-1, embedding_size)
                    shift_labels = shift_labels.view(-1)
                    
                    # Enable model parallelism
                    shift_labels = shift_labels.to(shift_logits.device)
                    loss = loss_fct(shift_logits, shift_labels)
                    
                # We keep track of the loss at each logged step
                total_loss += loss.detach().float()
                accelerator.backward(loss)
                # clip gradient norm. don't do this with deepspeed
                if accelerator.sync_gradients and args.clip_grad_norm > 0:
                    accelerator.clip_grad_norm_(model.parameters(), args.clip_grad_norm)
                optimizer.step()
                optimizer.zero_grad()
                lr_scheduler.step() 

            # Checks if the accelerator has performed an optimization step behind the scenes
            if accelerator.sync_gradients:
                progress_bar.update(1)
                completed_steps += 1
                if args.logging_steps and completed_steps % args.logging_steps == 0:
                    avg_loss = accelerator.gather(total_loss).mean().item() / args.gradient_accumulation_steps / args.logging_steps
                    logger.info(f"  Step: {completed_steps}, LR: {lr_scheduler.get_last_lr()[0]}, Loss: {avg_loss}")
                    if args.with_tracking:
                        accelerator.log(
                            {
                                "learning_rate": lr_scheduler.get_last_lr()[0],
                                "train_loss": avg_loss,
                            },
                            step=completed_steps,
                        )
                    total_loss = 0
                    
                if isinstance(checkpointing_steps, int):
                    if completed_steps % checkpointing_steps == 0:
                        output_dir = f"step_{completed_steps}"
                        if args.output_dir is not None:
                            output_dir = os.path.join(args.output_dir, output_dir)
                        save_with_accelerate(accelerator, model, tokenizer, output_dir, args)

                if completed_steps >= args.max_train_steps:
                    break
                

        if args.checkpointing_steps == "epoch":
            output_dir = f"epoch_{epoch}"
            if args.output_dir is not None:
                output_dir = os.path.join(args.output_dir, output_dir)
            save_with_accelerate(accelerator, model, tokenizer, output_dir, args)

    if args.output_dir is not None:
        if accelerator.is_main_process:
            tokenizer.save_pretrained(args.output_dir)
        save_with_accelerate(accelerator, model, tokenizer, args.output_dir, args)

    accelerator.wait_for_everyone()

    if args.with_tracking:
        accelerator.end_training()


def run_finetune(args):
    """
    Run the full LoRA/QLoRA fine-tuning loop.

    Orchestrates the following stages:
    1. Accelerator and logging setup
    2. Raw dataset loading
    3. Model, tokenizer, and LoRA initialisation
    4. Dataset encoding and token selection
    5. Optimiser, scheduler, and accelerator preparation
    6. Training loop with checkpointing

    Args:
        args: Parsed command-line arguments from :func:`parse_args`.
    """
    accelerator = _setup_accelerator(args)
    raw_datasets = _load_raw_datasets(args)
    model, tokenizer, embedding_size = _load_model_and_tokenizer(args, accelerator)
    train_dataset = _encode_and_prepare_dataset(args, raw_datasets, model, tokenizer, accelerator)
    model, optimizer, train_dataloader, lr_scheduler, checkpointing_steps = (
        _build_optimizer_and_scheduler(args, model, tokenizer, train_dataset, accelerator)
    )
    _training_loop(
        args, model, tokenizer, train_dataset, train_dataloader,
        optimizer, lr_scheduler, accelerator, checkpointing_steps,
        embedding_size,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the fine-tuning script."""
    parser = argparse.ArgumentParser()

    # Arguments used by run_pipeline / command line; others keep default values
    parser.add_argument("--model_name_or_path", type=str, required=True)
    parser.add_argument("--tokenizer_name", type=str, default=None)
    parser.add_argument("--train_file", type=str, required=True)
    parser.add_argument("--max_seq_length", type=int, default=1024)
    parser.add_argument("--preprocessing_num_workers", type=int, default=16)
    parser.add_argument("--checkpointing_steps", type=str, default="25")
    parser.add_argument("--per_device_train_batch_size", type=int, default=2)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=2)
    parser.add_argument("--learning_rate", type=float, default=1e-4)
    parser.add_argument(
        "--lr_scheduler_type",
        type=str,
        default="linear",
        choices=[e.value for e in SchedulerType],
    )

    parser.add_argument("--warmup_ratio", type=float, default=0.03)
    parser.add_argument("--weight_decay", type=float, default=0.0)
    parser.add_argument("--num_train_epochs", type=int, default=1)
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--logging_steps", type=int, default=50)

    # Additional arguments passed from run_pipeline
    parser.add_argument("--train_data_tag", type=str, default="default")
    parser.add_argument(
        "--token_select_pattern",
        type=str,
        choices=["default", "random", "token_cleaning"],
        default="default",
    )
    parser.add_argument("--data_prop", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--with_prompt_token", type=str2bool, default=False)
    parser.add_argument("--gradient_checkpointing", action="store_true")
    parser.add_argument("--use_lora", action="store_true")
    parser.add_argument("--lora_rank", type=int, default=64)
    parser.add_argument("--lora_alpha", type=float, default=16)
    parser.add_argument("--lora_dropout", type=float, default=0.1)

    # Arguments used internally by the script with reasonable defaults
    parser.add_argument("--dataset_name", type=str, default=None)
    parser.add_argument("--dataset_config_name", type=str, default=None)
    parser.add_argument("--config_name", type=str, default=None)
    parser.add_argument("--trust_remote_code", type=str2bool, default=True)
    parser.add_argument("--model_revision", type=str, default="main")
    parser.add_argument("--tokenizer_revision", type=str, default=None)
    parser.add_argument("--use_slow_tokenizer", action="store_true")
    parser.add_argument("--use_qlora", action="store_true")
    parser.add_argument("--use_flash_attn", action="store_true")
    parser.add_argument("--low_cpu_mem_usage", type=str2bool, default=True)
    parser.add_argument("--add_bos", type=str2bool, default=False)
    parser.add_argument("--label_path", type=str, default="./")
    parser.add_argument("--overwrite_cache", action="store_true")
    parser.add_argument(
        "--reduce_loss",
        type=str,
        choices=["mean", "sum"],
        default="mean",
    )
    parser.add_argument("--max_train_steps", type=int, default=None)
    parser.add_argument("--resume_from_checkpoint", type=str, default=None)
    parser.add_argument("--clip_grad_norm", type=float, default=0.0)
    parser.add_argument("--with_tracking", action="store_true")
    parser.add_argument("--report_to", type=str, default="tensorboard")
    parser.add_argument("--wandb_entity", type=str, default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--use_8bit_optimizer", action="store_true")

    args = parser.parse_args()
    return args

def main():
    """Parse arguments and run the fine-tuning loop."""
    try:
        args = parse_args()
    except SystemExit as e:
        # argparse calls sys.exit on error; re-raise after logging
        print(f"argparse exited with code={e.code}", file=sys.stderr, flush=True)
        raise
    run_finetune(args)


if __name__ in ("__main__", "__mp_main__"):
    main()
