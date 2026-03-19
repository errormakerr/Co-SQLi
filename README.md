# SQLI — Adversarial Training for SQL Injection Detection

An adversarial training framework that iteratively improves a language model's ability to detect SQL injection attacks. An **Attacker** generates diverse malicious SQL samples guided by a Multi-Armed Bandit (EXP3) algorithm, a **Defender** fine-tunes the detection model via LoRA, and a **Verifier** updates the bandit weights so that future training automatically focuses on the model's weakest areas.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  Adversarial Training Loop                │
│                                                          │
│   ┌──────────┐     ┌─────────────┐     ┌──────────┐     │
│   │ Attacker │ ──► │CoT Producer │ ──► │ Defender │     │
│   │ (MAB     │     │ (SFT data   │     │ (LoRA    │     │
│   │  guided  │     │  formatter) │     │  fine-   │     │
│   │  sample  │     └─────────────┘     │  tune +  │     │
│   │  gen.)   │                         │  infer)  │     │
│   └────▲─────┘                         └────┬─────┘     │
│        │                                    │           │
│        │         ┌──────────┐               │           │
│        └──────── │ Verifier │ ◄─────────────┘           │
│                  │ (EXP3    │                           │
│                  │  weight  │                           │
│                  │  update) │                           │
│                  └──────────┘                           │
└──────────────────────────────────────────────────────────┘
```

Each round:
1. **Attacker** samples attack clusters based on EXP3 probabilities, generates injection SQLs (optionally with LLM-based payload mutation), and mixes in benign samples.
2. **CoT Producer** pairs each SQL with its database schema and formats the data into OpenAI-style messages for SFT.
3. **Defender** fine-tunes the base model with LoRA, merges the adapter, and runs inference on a validation set.
4. **Verifier** computes per-cluster accuracy, calculates EXP3 rewards (`1 − accuracy`), and updates cluster weights — clusters the model struggles with get higher weight in the next round.

## Directory Structure

```
SQLI/
├── config/                          # YAML configuration files
│   ├── training_config.yaml         #   Fine-tuning hyperparameters
│   ├── inference_config.yaml        #   Inference settings
│   ├── gpt_config.yaml              #   LLM API config (mutation)
│   ├── database_connection.yaml     #   MySQL connection details
│   └── fsdp_config.yaml             #   FSDP / DeepSpeed config
├── data/
│   ├── raw_datas_for_generation/    # Raw materials for sample generation
│   │   ├── payloads.json            #   Payload templates by attack type
│   │   ├── sql_data_with_injection_point.json
│   │   ├── schema.json              #   Database schemas
│   │   ├── system_variables.json    #   MySQL system variables
│   │   ├── comments.json            #   Deceptive comments library
│   │   └── normal_sqls.json         #   Benign SQL samples
│   └── benchmark/                   # Benchmark datasets
│       ├── train_sqls.json / test_sqls.json
│       └── *_openai_format.jsonl    #   Pre-formatted SFT data
├── ddl/                             # DDL scripts for 11 databases
├── prompt_templates/                # Jinja2 prompt templates
│   ├── generate_comment.j2
│   └── CoT_producer/               #   Background knowledge templates
├── src/
│   ├── main.py                      # Training loop entry point
│   ├── Attacker/
│   │   ├── Attacker.py              #   MAB-guided sample generator
│   │   ├── generate_injection_sql.py#   SQL injection pipeline
│   │   └── payload_mutation/        #   LLM-based mutation subsystem
│   ├── CoT_producer/
│   │   ├── CoT_producer.py          #   SFT data formatter
│   │   ├── schema_reprocess.py      #   Schema loading & DDL generation
│   │   └── generate_thinking_of_ground_truth.py
│   ├── Defender/
│   │   ├── defender.py              #   Training pipeline orchestrator
│   │   ├── finetune.py              #   LoRA/QLoRA fine-tuning script
│   │   ├── merge_lora.py            #   LoRA adapter merge script
│   │   └── inference.py             #   Model inference & evaluation
│   ├── Verifier/
│   │   ├── verifier.py              #   EXP3 weight updater
│   │   └── eval.py                  #   Per-cluster accuracy computation
│   └── utils/                       #   Shared utilities
├── .gitignore
├── requirements.txt
└── README.md
```

## Prerequisites

- Python 3.10+
- CUDA-capable GPU(s) (tested with 2× GPUs)
- MySQL server (for template filling with real schema data)
- Access to an OpenAI-compatible LLM API (for payload mutation)

## Installation

```bash
git clone <repository-url>
cd SQLI
pip install -r requirements.txt
```

## Configuration

All configuration files are in the `config/` directory:

| File | Purpose |
|------|---------|
| `training_config.yaml` | GPU allocation, batch size, LoRA rank/alpha/dropout, learning rate, accelerate config path |
| `inference_config.yaml` | Inference batch size, temperature, max sequence length, device |
| `gpt_config.yaml` | LLM API key, base URL, model name (for payload mutation) |
| `database_connection.yaml` | MySQL host, port, user, password, database |
| `fsdp_config.yaml` | FSDP / DeepSpeed distributed training configuration |

### Key Training Parameters (in `main.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `NUM_ROUNDS` | 8 | Total adversarial training rounds |
| `NUM_TRAINING_SQLS` | 300 | Samples generated per round |
| `ATTACKER_GAMMA` | 0.7 | MAB exploration factor for sampling |
| `VERIFIER_GAMMA` | 0.3 | EXP3 learning rate for weight updates |
| `ATTACKER_K` | 8 | Number of clusters selected per round |
| `PROBABILITY_ROUNDS` | 6 | Rounds using probability sampling (rest use top-k) |
| `ENABLE_PAYLOAD_MUTATION` | True | Toggle LLM-based payload mutation |
| `MODIFY_PAYLOAD_PROB_START` | 0.1 | Initial mutation probability |
| `MODIFY_PAYLOAD_PROB_END` | 0.4 | Final mutation probability (linearly interpolated) |

## Usage

### Running the Full Training Loop

```bash
cd SQLI
python src/main.py
```

The training loop can be resumed from a breakpoint by setting `breakpoint_round` in `main.py`:

```python
run_training_loop(start_round=0, breakpoint_round=3)  # Resume from round 3
```

### Running Individual Components

**Fine-tune only** (via `accelerate`):
```bash
accelerate launch --config_file config/fsdp_config.yaml \
    src/Defender/finetune.py \
    --model_name_or_path /path/to/model \
    --train_file /path/to/train_data.jsonl \
    --output_dir /path/to/output \
    --use_lora --lora_rank 16
```

**Merge LoRA adapter**:
```bash
python src/Defender/merge_lora.py \
    --lora_model_name_or_path /path/to/adapter \
    --output_dir /path/to/merged \
    --save_tokenizer
```

**Run inference**:
```bash
python src/Defender/inference.py \
    --model_path /path/to/merged_model \
    --test_file /path/to/test_data.jsonl \
    --output_file /path/to/results.jsonl
```

## Attack Cluster Taxonomy

Each SQL injection sample is characterized by a 4-dimensional key:

| Dimension | Values |
|-----------|--------|
| **Attack Type** | Tautologies, Error-based, Union-query, Piggy-backed, Boolean Inference, Time Inference |
| **Annotator** | True / False |
| **Information Features** | constant, system information, specific database |
| **Comment** | True / False |

Normal (benign) SQL samples use the fixed key `normal||normal||normal||normal`.

## Technical Details

### Base Model
- **Qwen2.5-Coder-1.5B-Instruct** (configurable in `ProjectPaths`)

### Fine-Tuning
- LoRA with rank=16, alpha=32, dropout=0.1
- BF16 mixed precision
- Multi-GPU via HuggingFace Accelerate + DeepSpeed/FSDP

### MAB Algorithm (EXP3)
- Probability update: `p(k) = (1−γ)·w(k)/Σw + γ/N`
- Weight update: `w(k) *= exp(γ/n · reward(k)/prob(k))`
- Reward: `1 − accuracy` (clusters the model already handles well get low reward)

### Payload Mutation
- LLM-driven mutation with two strategies:
  - **Type-focused**: Changes the attack implementation technique
  - **Info-focused**: Changes the SQL query structure
- 18-category memory system (6 attack types × 3 info features)
- Anti-imitation few-shot prompting
- Separate `expected_types` inference for semantic understanding

## License

This project is for academic research purposes.