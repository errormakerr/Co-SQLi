#!/usr/bin/env bash
# ==============================================================================
# run_ablation.sh — Batch runner for bandit strategy ablation experiments
#
# Usage:
#   bash scripts/run_ablation.sh --minimal               # 5 strategies × 1 seed = 5 experiments
#   bash scripts/run_ablation.sh --minimal3              # 5 strategies × 3 seeds = 15 experiments
#   bash scripts/run_ablation.sh --full                  # 9 strategies × 3 seeds = 27 experiments
#   bash scripts/run_ablation.sh --strategy exp3 --seed 42  # Single run
#   bash scripts/run_ablation.sh --aggregate             # Aggregate results only
# ==============================================================================

set -euo pipefail

# ── Configurable parameters ──────────────────────────────────────────────────
BASE_MODEL="${BASE_MODEL:-/home/panhao/model/base_model/Qwen2.5-Coder-1.5B-Instruct}"
OUTPUT_ROOT="${OUTPUT_ROOT:-/home/panhao/model/ablation_results}"
GPU="${GPU:-6,7}"
PORT="${PORT:-29522}"
MUTATION="${MUTATION:-on}"
PYTHON="${PYTHON:-/home/panhao/anaconda3/envs/finetuning_test/bin/python}"

# Ensure conda env binaries (accelerate, etc.) are on PATH
CONDA_BIN_DIR="$(dirname "$PYTHON")"
export PATH="$CONDA_BIN_DIR:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$PROJECT_DIR/src"

# Strategy sets
CORE_STRATEGIES=("uniform" "greedy" "softmax_0.3" "thompson_0.7" "exp3")
ALL_STRATEGIES=(
    "uniform" "greedy"
    "softmax_0.1" "softmax_0.3" "softmax_0.5"
    "thompson_0.5" "thompson_0.7" "thompson_0.9"
    "exp3"
)
CORE_SEEDS=(42 123 456)

# ── Parse arguments ──────────────────────────────────────────────────────────
MODE=""
SINGLE_STRATEGY=""
SINGLE_SEED=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --minimal)    MODE="minimal"; shift ;;
        --minimal3)   MODE="minimal3"; shift ;;
        --full)       MODE="full"; shift ;;
        --aggregate)  MODE="aggregate"; shift ;;
        --strategy)   SINGLE_STRATEGY="$2"; shift 2 ;;
        --seed)       SINGLE_SEED="$2"; shift 2 ;;
        --gpu)        GPU="$2"; shift 2 ;;
        --port)       PORT="$2"; shift 2 ;;
        --base_model) BASE_MODEL="$2"; shift 2 ;;
        --output)     OUTPUT_ROOT="$2"; shift 2 ;;
        --mutation)   MUTATION="$2"; shift 2 ;;
        *)            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Helper: run a single experiment ──────────────────────────────────────────
run_one() {
    local strategy=$1
    local seed=$2
    echo ""
    echo "================================================================"
    echo " Running: strategy=$strategy  seed=$seed  mutation=$MUTATION"
    echo "================================================================"
    $PYTHON "$SRC_DIR/ablation_main.py" \
        --strategy "$strategy" \
        --seed "$seed" \
        --mutation "$MUTATION" \
        --base_model "$BASE_MODEL" \
        --output_root "$OUTPUT_ROOT" \
        --gpu "$GPU" \
        --port "$PORT"
}

# ── Main dispatch ────────────────────────────────────────────────────────────
if [[ -n "$SINGLE_STRATEGY" && -n "$SINGLE_SEED" ]]; then
    # Single run mode
    run_one "$SINGLE_STRATEGY" "$SINGLE_SEED"

elif [[ "$MODE" == "minimal" ]]; then
    echo "Running minimal experiment set: ${#CORE_STRATEGIES[@]} strategies × 1 seed"
    for strategy in "${CORE_STRATEGIES[@]}"; do
        run_one "$strategy" 42
    done

elif [[ "$MODE" == "minimal3" ]]; then
    echo "Running experiment set: ${#CORE_STRATEGIES[@]} strategies × ${#CORE_SEEDS[@]} seeds"
    for strategy in "${CORE_STRATEGIES[@]}"; do
        for seed in "${CORE_SEEDS[@]}"; do
            run_one "$strategy" "$seed"
        done
    done

elif [[ "$MODE" == "full" ]]; then
    echo "Running full experiment set: ${#ALL_STRATEGIES[@]} strategies × ${#CORE_SEEDS[@]} seeds"
    for strategy in "${ALL_STRATEGIES[@]}"; do
        for seed in "${CORE_SEEDS[@]}"; do
            run_one "$strategy" "$seed"
        done
    done

elif [[ "$MODE" == "aggregate" ]]; then
    echo "Aggregating results from: $OUTPUT_ROOT"
    $PYTHON "$SRC_DIR/aggregate_results.py" --results_dir "$OUTPUT_ROOT"

else
    echo "Usage:"
    echo "  bash scripts/run_ablation.sh --minimal                    # 5 strategies × 1 seed  =  5 experiments"
    echo "  bash scripts/run_ablation.sh --minimal3                   # 5 strategies × 3 seeds = 15 experiments"
    echo "  bash scripts/run_ablation.sh --full                       # 9 strategies × 3 seeds = 27 experiments"
    echo "  bash scripts/run_ablation.sh --strategy exp3 --seed 42    # Single run"
    echo "  bash scripts/run_ablation.sh --aggregate                  # Aggregate results"
    echo ""
    echo "Environment variables:"
    echo "  BASE_MODEL   Path to base model (default: $BASE_MODEL)"
    echo "  OUTPUT_ROOT  Output directory (default: $OUTPUT_ROOT)"
    echo "  GPU          GPU IDs (default: $GPU)"
    echo "  PORT         Dist. training port (default: $PORT)"
    echo "  MUTATION     on|off (default: $MUTATION)"
    exit 1
fi

echo ""
echo "All experiments completed. Aggregating results..."
$PYTHON "$SRC_DIR/aggregate_results.py" --results_dir "$OUTPUT_ROOT"
