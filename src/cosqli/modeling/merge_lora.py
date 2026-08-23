"""
LoRA Merge Script

Merges a LoRA adapter (produced by ``finetune.py``) back into the base model
weights and saves the result as a standard HuggingFace model directory.

QLoRA (4-bit quantized) adapters require a dequantization step before merging;
pass ``--qlora`` to enable this path.

Usage:
    python merge_lora.py \\
        --lora_model_name_or_path /path/to/adapter \\
        --base_model_name_or_path /path/to/base_model \\
        --output_dir              /path/to/output \\
        [--qlora] [--save_tokenizer] [--use_fast_tokenizer] \\
        [--device auto|cuda|cpu]
"""

import argparse
import copy
import os
from typing import Dict, Optional

import bitsandbytes as bnb
import torch
from bitsandbytes.functional import dequantize_4bit
from peft import PeftConfig, PeftModel
from peft.utils import _get_submodules
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from cosqli.paths import require_external_path


# ---------------------------------------------------------------------------
# QLoRA de-quantization helper
# ---------------------------------------------------------------------------

def dequantize_model(
    model: torch.nn.Module,
    dtype: torch.dtype = torch.bfloat16,
    device: str = "cuda",
) -> torch.nn.Module:
    """
    Convert 4-bit quantized Linear layers back to full-precision ``nn.Linear``.

    This step is required before merging a QLoRA adapter because the standard
    ``merge_and_unload()`` routine expects full-precision base weights.

    Args:
        model:  A PEFT model loaded with 4-bit quantization.
        dtype:  Target floating-point dtype for the dequantized weights.
        device: Device to place the new linear modules on.

    Returns:
        The model with all ``bnb.nn.Linear4bit`` modules replaced by standard
        ``torch.nn.Linear`` modules.
    """
    cls = bnb.nn.Linear4bit
    with torch.no_grad():
        for name, module in model.named_modules():
            if not isinstance(module, cls):
                continue

            quant_state = copy.deepcopy(module.weight.quant_state)
            # ``quant_state`` was a list in older bitsandbytes versions.
            if isinstance(quant_state, list):
                quant_state[2] = dtype
            else:
                quant_state.dtype = dtype

            weights = dequantize_4bit(
                module.weight.data,
                quant_state=quant_state,
                quant_type="nf4",
            ).to(dtype)

            new_module = torch.nn.Linear(
                module.in_features,
                module.out_features,
                bias=None,
                dtype=dtype,
            )
            new_module.weight = torch.nn.Parameter(weights)
            new_module.to(device=device, dtype=dtype)

            parent, target, target_name = _get_submodules(model, name)
            setattr(parent, target_name, new_module)

        # Must be unset so that ``save_pretrained`` does not attempt to
        # serialise the (now-removed) quantization state.
        model.is_loaded_in_4bit = False

    return model


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Merge a LoRA adapter into the base model."
    )
    parser.add_argument(
        "--lora_model_name_or_path",
        type=str,
        required=True,
        help="Path to the LoRA adapter directory.",
    )
    parser.add_argument(
        "--base_model_name_or_path",
        type=str,
        required=False,
        help=(
            "Path to the base model. Defaults to the value stored in "
            "adapter_config.json if not specified."
        ),
    )
    parser.add_argument(
        "--tokenizer_name_or_path",
        type=str,
        required=False,
        help="Path to the tokenizer. Resolved automatically if not given.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=False,
        help="Directory to save the merged model. Defaults to lora_model_name_or_path.",
    )
    parser.add_argument(
        "--qlora",
        action="store_true",
        help="Enable the QLoRA (4-bit) dequantization path before merging.",
    )
    parser.add_argument(
        "--save_tokenizer",
        action="store_true",
        help="Copy the tokenizer into the output directory.",
    )
    parser.add_argument(
        "--use_fast_tokenizer",
        action="store_true",
        help="Use the fast tokenizer variant when loading.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help=(
            "Device for the merge operation: 'auto', 'cuda', 'cpu', "
            "'cuda:0', 'cuda:1', etc."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------

def run_merge_lora(args: argparse.Namespace) -> None:
    """
    Execute the full LoRA merge pipeline.

    Steps:
    1. Resolve the target device.
    2. Load the PEFT config and base model (with optional QLoRA dequantization).
    3. Load the tokenizer (from adapter dir, base model dir, or explicit path).
    4. Resize token embeddings if the tokenizer vocabulary grew during SFT.
    5. Attach and merge the LoRA adapter weights.
    6. Save the merged model (and optionally the tokenizer).

    Args:
        args: Parsed command-line arguments from :func:`parse_args`.
    """
    # 1. Determine the device and device_map
    if args.device == "auto":
        if torch.cuda.is_available():
            device = "cuda:0"
            device_map: Optional[Dict[str, int]] = {"": 0}
        else:
            device = "cpu"
            device_map = None
    elif args.device.startswith("cuda"):
        device = args.device
        device_id = int(args.device.split(":")[1]) if ":" in args.device else 0
        device_map = {"": device_id}
    else:
        device = "cpu"
        device_map = None

    print(f"Using device: {device}")

    peft_config = PeftConfig.from_pretrained(args.lora_model_name_or_path)
    base_model_path = (
        args.base_model_name_or_path or peft_config.base_model_name_or_path
    )
    print(f"Loading base model from: {base_model_path}")

    # 2. Load base model
    if args.qlora:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            torch_dtype=torch.bfloat16,
            quantization_config=bnb_config,
            device_map=device_map,
        )
        base_model = dequantize_model(base_model, device=device)
    else:
        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            torch_dtype=torch.bfloat16 if device.startswith("cuda") else None,
            device_map=device_map,
        )

    # 3. Load tokenizer
    if args.tokenizer_name_or_path:
        print(f"Loading tokenizer from: {args.tokenizer_name_or_path}")
        tokenizer = AutoTokenizer.from_pretrained(
            args.tokenizer_name_or_path,
            use_fast=args.use_fast_tokenizer,
        )
    else:
        try:
            print("Attempting to load tokenizer from LoRA adapter directory...")
            tokenizer = AutoTokenizer.from_pretrained(
                args.lora_model_name_or_path,
                use_fast=args.use_fast_tokenizer,
            )
        except Exception:
            print("Tokenizer not found in adapter dir; loading from base model...")
            tokenizer = AutoTokenizer.from_pretrained(
                base_model_path,
                use_fast=args.use_fast_tokenizer,
            )

    # 4. Resize embeddings if the tokenizer vocabulary grew during SFT
    #    (Certain base models also have known offsets that must be accounted for.)
    embedding_size = base_model.get_input_embeddings().weight.shape[0]
    lower_name = base_model_path.lower()

    # Known embedding-size corrections for specific base models
    if "mistral" in lower_name:
        embedding_size = 32776
    elif "llama-2-7b-hf" in lower_name or "llama-2-13b-hf" in lower_name:
        embedding_size = 32008
    elif "llama-3" in lower_name:
        embedding_size = 128264

    if len(tokenizer) > embedding_size:
        print(
            f"Tokenizer vocabulary ({len(tokenizer)}) exceeds embedding size "
            f"({embedding_size}). Resizing token embeddings..."
        )
        base_model.resize_token_embeddings(len(tokenizer))
    else:
        base_model.resize_token_embeddings(embedding_size)

    # 5. Load LoRA adapter and merge
    print("Loading LoRA adapter...")
    lora_model = PeftModel.from_pretrained(base_model, args.lora_model_name_or_path)
    print("Merging LoRA modules into base model...")
    merged_model = lora_model.merge_and_unload()

    # 6. Save
    output_dir = require_external_path(
        args.output_dir or args.lora_model_name_or_path,
        purpose="merged-model output",
    )
    os.makedirs(output_dir, exist_ok=True)
    print(f"Saving merged model to: {output_dir}")
    merged_model.save_pretrained(output_dir, safe_serialization=True)

    if args.save_tokenizer:
        print(f"Saving tokenizer to: {output_dir}")
        tokenizer.save_pretrained(output_dir)

    print("Merge complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and run the merge pipeline."""
    args = parse_args()
    run_merge_lora(args)


if __name__ == "__main__":
    main()
