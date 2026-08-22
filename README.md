<div align="center">

# 🛡️ SQLI
**Adversarial Training Framework for SQL Injection Detection**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![LoRA Support](https://img.shields.io/badge/Fine--Tuning-LoRA%2FQLoRA-orange.svg)]()
[![Model](https://img.shields.io/badge/Base_Model-Qwen2.5--Coder-purple.svg)]()

</div>

---

**SQLI** is a robust adversarial training framework designed to iteratively enhance a Large Language Model's (LLM) ability to detect SQL injection attacks. By simulating a continuous arms race between an **Attacker** and a **Defender**, guided by a Multi-Armed Bandit algorithm, the model naturally focuses its learning on its weakest vulnerabilities.

## 🌟 Core Architecture

The framework operates in an automated, closed-loop cycle consisting of three primary agents:

```mermaid
graph TD
    classDef attacker fill:#ffe8e8,stroke:#ff6b6b,stroke-width:2px,color:#333;
    classDef defender fill:#e8f4fc,stroke:#4dabf7,stroke-width:2px,color:#333;
    classDef verifier fill:#ebfbee,stroke:#51cf66,stroke-width:2px,color:#333;
    classDef formatter fill:#f8f9fa,stroke:#ced4da,stroke-width:2px,stroke-dasharray: 4 4,color:#333;

    A[🗡️ Attacker<br><i>MAB-Guided Generator</i>]:::attacker -->|Generates SQLs + Mutates Payloads| SFT[📄 SFT Formatter<br><i>Schema to OpenAI Msgs</i>]:::formatter
    SFT -->|Formats SFT Data| D[🛡️ Defender<br><i>Model Training & Eval</i>]:::defender
    D -->|1. LoRA Finetune<br>2. Merge Weights| M[(Merged Model)]:::formatter
    M -->|Inference on Valid Set| V[⚖️ Verifier<br><i>Weight Updater</i>]:::verifier
    V -->|Updates EXP3 Weights<br>Reward = 1 - Accuracy| A
```

### How a Round Works:
1. **Attacker**: Samples attack clusters based on EXP3 probabilities. Generates injection SQLs (optionally mutating payloads via an LLM to increase diversity) and mixes them with benign samples.
2. **SFT Formatter**: Pairs each SQL query with its corresponding database schema and formats the data into OpenAI-style conversational SFT data.
3. **Defender**: Fine-tunes the base model (e.g., *Qwen2.5-Coder-1.5B*) using LoRA, merges the trained adapter into the base weights, and runs inference evaluations.
4. **Verifier**: Computes a smoothed per-cluster false-negative reward from the Defender's inference results and updates EXP3 weights, ensuring the next round focuses on missed attacks.

---

## 📂 Directory Structure

```text
SQLI/
├── config/                          # ⚙️ YAML configuration files
│   ├── training_config.yaml         # Fine-tuning hyperparameters
│   ├── inference_config.yaml        # Inference settings
│   ├── gpt_config.yaml              # LLM API config (for payload mutation)
│   ├── database_connection.yaml     # MySQL connection details
│   ├── runtime_config.yaml           # Local model and training-output paths
│   ├── accelerate_single_gpu.yaml   # Current one-GPU Accelerate configuration
│   └── fsdp_config.yaml             # Optional multi-GPU FSDP configuration
├── data/                            # 📊 Datasets and Materials
│   ├── raw_datas_for_generation/    # Raw SQLs, schemas, and payload templates
│   └── benchmark/                   # Training/Testing benchmark datasets
├── ddl/                             # 🗄️ Reference DDL scripts for databases
├── prompt_templates/                # 📝 Prompt files (e.g. generate_comment.j2)
└── src/                             # 💻 Source Code
    ├── main.py                      # Multi-round training entry point
    ├── Attacker/                    # Attack-cluster sampling and generation strategy
    ├── Defender/                    # Model-improvement workflow orchestration
    ├── Verifier/                    # Acc metrics & MAB weight processing
    ├── synthesis/                   # SQL template filling, mutation, and SFT formatting
    ├── model_ops/                   # LoRA fine-tuning, merging, and inference
    └── utils/                       # Shared clients, serialization, and clustering
```

---

## 🚀 Getting Started

### Prerequisites
- **Python:** 3.10 or higher
- **Hardware:** CUDA-capable GPU(s) (Framework tested with multi-GPU setups)
- **Database:** MySQL server (required for template filling with real schema data)
- **API:** Access to an OpenAI-compatible API (required if payload mutation is enabled)

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd SQLI
   ```
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

Before running the framework, ensure the files in the `config/` directory are properly configured:

| Configuration File | Description |
|--------------------|-------------|
| `training_config.yaml` | Controls GPU allocation, batch size, LoRA params (rank/alpha/dropout), learning rate, and accelerate paths. |
| `inference_config.yaml` | Sets inference batch size, temperature, seq length, and target device. |
| `gpt_config.yaml` | Stores LLM API keys and model names used by the Attacker for payload mutation. |
| `database_connection.yaml`| Credentials for the MySQL template database. |
| `runtime_config.yaml` | Local base-model directory and the dedicated directory for round outputs. |
| `accelerate_single_gpu.yaml` | Single-GPU Accelerate configuration used by the current training setup. |
| `fsdp_config.yaml` | Multi-GPU distributed training configuration. |

### Key Training Parameters (`src/main.py`)
You can tweak the core loop behaviour directly in `main.py`:
- `NUM_ROUNDS = 8`: Total adversarial training iterations.
- `NUM_TRAINING_SQLS = 300`: Volume of samples generated per round.
- `ATTACKER_GAMMA = 0.7` / `VERIFIER_GAMMA = 0.3`: MAB exploration/learning rates.
- `ATTACKER_STRATEGY = "by_probability"` / `ATTACKER_K = 6`: Every round samples six attack clusters without replacement according to EXP3 probabilities. `top_k` remains available only as an explicit ablation override.
- `INITIAL_BENIGN_RATIO = 0.25`: Initial share of benign samples in each round. Benign samples are outside the attack-cluster MAB and subsequently follow FPR-based feedback control.
- `ENABLE_PAYLOAD_MUTATION = True`: Toggles dynamic LLM-based SQL payload mutations.

---

## 💻 Usage

### Launching the Full Adversarial Loop
To run the automated Attack-Defend-Verify loop across all configured rounds:
```bash
cd SQLI
python src/main.py
```

On Slurm clusters where MySQL is deployed as a job-local service, first run a
sidecar preflight and then submit the full loop through the provided script:

```bash
SQLI_MODE=db-check sbatch scripts/sqli_slurm_job.sh
SQLI_MODE=generate-smoke sbatch scripts/sqli_slurm_job.sh
SQLI_MODE=mutation-smoke sbatch scripts/sqli_slurm_job.sh
SQLI_MODE=refactor-smoke sbatch scripts/sqli_slurm_job.sh
SQLI_MODE=full SQLI_MAIN_ARGS="--num-rounds 1 --num-training-sqls 12" \
    sbatch scripts/sqli_slurm_job.sh
```

The script starts MySQL on the allocated compute node, checks the configured
read-only account, and shuts down only the MySQL process it started. The MySQL
data directory must not be in use by another server when the job begins.
`refactor-smoke` does not call the LLM API or train a model; it validates the
refactored package boundaries and performs one database-specific synthesis.

*🔥 Tip: You can resume training from a specific breakpoint by modifying the `breakpoint_round` argument in `main.py` -> `run_training_loop(start_round=0, breakpoint_round=3)`.*

### Running Individual Components Manually

If you need to isolate specific behaviors, you can run the Defender scripts individually:

**1. Fine-Tune (via Accelerate):**
```bash
accelerate launch --config_file config/fsdp_config.yaml \
    src/model_ops/finetune.py \
    --model_name_or_path /path/to/model \
    --train_file /path/to/train_data.jsonl \
    --output_dir /path/to/output \
    --use_lora --lora_rank 16
```

**2. Merge LoRA Adapter:**
```bash
python src/model_ops/merge_lora.py \
    --lora_model_name_or_path /path/to/adapter \
    --output_dir /path/to/merged \
    --save_tokenizer
```

**3. Run Inference:**
```bash
python src/model_ops/inference.py \
    --model_path /path/to/merged_model \
    --test_file /path/to/test_data.jsonl \
    --output_file /path/to/results.jsonl
```

---

## 🔬 Technical Deep-Dive

### Attack Cluster Taxonomy
Each malicious sample has a canonical, versioned cluster key:
`technique||reference_scope||comment_state`.

1. **Technique**: `tautology`, `union_query`, `piggy_backed`, `error_based`, `boolean_blind`, or `time_blind`.
2. **Reference scope**: `lor` (literal-only), `tsr` (target-schema reference), or `scr` (system-catalog reference).
3. **Comment state**: `no_comment`, `clean_comment`, or `cepp` (a non-empty CEPP string after `-- `).

Two invalid payload categories, `boolean_blind||lor` and `piggy_backed||lor`, are pruned. The remaining 16 categories crossed with the three comment states form the fixed 48 EXP3 arms. Arms are declared in code, never inferred from benchmark coverage. Benign samples use the separate `benign` key and are controlled outside EXP3.

Comment delimiters are assembled only at injection time: canonical payload templates and mutation outputs are comment-free cores. `clean_comment` always appends `-- `, while `cepp` appends `-- ` followed by one safe, non-empty CEPP string.

### Multi-Armed Bandit (EXP3)
The framework mathematically guarantees the model confronts its weakest areas:
- **Attack Arms**: EXP3 operates over injection clusters only; benign examples are budgeted separately.
- **Reward Function**: $Reward_k = (FN_k + 1) / (n_k + 2)$
- **Weight Update**: $W_{k} = W_{k} \times \exp(\frac{\gamma}{N} \times \frac{Reward_{k}}{Prob_{k}})$
- **Benign Controller**: A smoothed benign FPR is tracked with EMA and adjusts the next-round benign ratio within `[0.15, 0.35]`.
- MAB heavily samples clusters with high weights (low detection accuracy) in subsequent rounds.

### LLM Payload Mutation
When enabled, the Attacker uses LLM capabilities to mutate SQL injection payloads on the fly:
- **Technique-aware Mutation**: Explores alternate payload forms while preserving the declared technique and reference scope.
- **Structure-aware Mutation**: Varies the embedded query structure without changing the payload category.
- Uses category-scoped anti-imitation few-shot prompting: up to five successful mutation templates are sampled first, then original templates fill remaining slots. Successful mutations are retained without a size cap.

---

<div align="center">
<i>This project is developed for academic research and defensive security purposes.</i>
</div>
