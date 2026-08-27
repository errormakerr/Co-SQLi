#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${COSQLI_PROJECT_ROOT:-${SLURM_SUBMIT_DIR:-}}"
if [[ -z "$PROJECT_ROOT" ]]; then
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
RUN_ID="${COSQLI_RUN_ID:?Set COSQLI_RUN_ID through co-sqli-submit.}"
RUN_DIR="${COSQLI_RUN_DIR:?Set COSQLI_RUN_DIR through co-sqli-submit.}"
BENCHMARK_DIR="${COSQLI_BENCHMARK_DIR:?Set COSQLI_BENCHMARK_DIR through co-sqli-submit.}"
ENV_PREFIX="${COSQLI_ENV_PREFIX:?Set COSQLI_ENV_PREFIX to the Python environment.}"
RUNTIME_ROOT="${COSQLI_RUNTIME_ROOT:?Set COSQLI_RUNTIME_ROOT to the external runtime root.}"
MYSQL_ROOT="$RUNTIME_ROOT/mysql"
MYSQL_CNF="${COSQLI_MYSQL_CNF:-$MYSQL_ROOT/my.cnf}"
MYSQLD="${COSQLI_MYSQLD:-}"
LOG_DIR="$RUN_DIR/logs"
TELEMETRY_DIR="$RUN_DIR/telemetry"
MYSQL_PID_FILE="$LOG_DIR/mysql.pid"
# Unix-domain socket paths are capped at 107 bytes on Linux. Keep this
# node-local path independent of the externally managed experiment directory.
MYSQL_SOCKET="/tmp/cosqli-mysql-${SLURM_JOB_ID:-$$}.sock"
MYSQL_ERROR_LOG="$LOG_DIR/mysql.err"
PYTHON_BIN="$ENV_PREFIX/bin/python"
MYSQL_STARTED=0
RESOURCE_MONITOR_PID=""

cleanup() {
    local exit_status=$?
    if [[ -n "$RESOURCE_MONITOR_PID" ]] && kill -0 "$RESOURCE_MONITOR_PID" 2>/dev/null; then
        kill -TERM "$RESOURCE_MONITOR_PID" 2>/dev/null || true
        wait "$RESOURCE_MONITOR_PID" 2>/dev/null || true
    fi
    if [[ "$MYSQL_STARTED" -eq 1 && -f "$MYSQL_PID_FILE" ]]; then
        local mysql_pid
        mysql_pid="$(<"$MYSQL_PID_FILE")"
        if [[ "$mysql_pid" =~ ^[0-9]+$ ]] && kill -0 "$mysql_pid" 2>/dev/null; then
            kill -TERM "$mysql_pid"
            for _ in {1..30}; do
                kill -0 "$mysql_pid" 2>/dev/null || break
                sleep 1
            done
        fi
    fi
    rm -f "$MYSQL_SOCKET"
    "$PYTHON_BIN" "$PROJECT_ROOT/scripts/resource_monitor.py" \
        --output "$TELEMETRY_DIR/resource_samples.csv" \
        --summarize \
        --summary-output "$TELEMETRY_DIR/resource_summary.json" || true
    "$PYTHON_BIN" -m cosqli.reporting --run-dir "$RUN_DIR" || true
    exit "$exit_status"
}
trap cleanup EXIT INT TERM

if [[ -z "$MYSQLD" && -d "$MYSQL_ROOT" ]]; then
    MYSQLD="$(find "$MYSQL_ROOT" -type f -name mysqld -perm -u+x -print -quit)"
fi
if [[ ! -x "$MYSQLD" || ! -f "$MYSQL_CNF" ]]; then
    echo "MySQL runtime is incomplete under $MYSQL_ROOT" >&2
    exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Co-SQLi Python environment not found: $ENV_PREFIX" >&2
    exit 1
fi
if [[ -e "$MYSQL_PID_FILE" || -S "$MYSQL_SOCKET" ]]; then
    echo "Refusing to start MySQL: a prior pid file or socket exists in $LOG_DIR." >&2
    exit 1
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$ENV_PREFIX/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$LOG_DIR" "$TELEMETRY_DIR"

"$PYTHON_BIN" "$PROJECT_ROOT/scripts/resource_monitor.py" \
    --output "$TELEMETRY_DIR/resource_samples.csv" \
    --interval-seconds "${COSQLI_RESOURCE_SAMPLE_SECONDS:-5}" \
    --job-id "${SLURM_JOB_ID:-}" &
RESOURCE_MONITOR_PID=$!

(cd "$MYSQL_ROOT" && "$MYSQLD" --defaults-file="$MYSQL_CNF" --socket="$MYSQL_SOCKET" \
    --pid-file="$MYSQL_PID_FILE" --log-error="$MYSQL_ERROR_LOG" --daemonize)
MYSQL_STARTED=1
for _ in {1..30}; do
    if "$PYTHON_BIN" "$PROJECT_ROOT/scripts/check_mysql_connection.py" --quiet; then
        break
    fi
    sleep 1
done
if ! "$PYTHON_BIN" "$PROJECT_ROOT/scripts/check_mysql_connection.py"; then
    tail -n 50 "$MYSQL_ERROR_LOG" >&2 || true
    exit 1
fi

case "${COSQLI_MODE:-db-check}" in
    db-check)
        echo "MySQL sidecar preflight completed successfully."
        ;;
    generate-smoke)
        "$PYTHON_BIN" "$PROJECT_ROOT/scripts/generate_smoke.py" --samples "${COSQLI_SMOKE_SAMPLES:-12}"
        ;;
    mutation-smoke)
        "$PYTHON_BIN" "$PROJECT_ROOT/scripts/mutation_smoke.py"
        ;;
    synthesis-smoke)
        "$PYTHON_BIN" "$PROJECT_ROOT/scripts/synthesis_smoke.py"
        ;;
    build-benchmarks)
        "$PYTHON_BIN" "$PROJECT_ROOT/scripts/build_benchmarks.py" \
            --output-dir "${COSQLI_BENCHMARK_OUTPUT_DIR:?Set COSQLI_BENCHMARK_OUTPUT_DIR.}" \
            --seed "${COSQLI_BENCHMARK_SEED:-20260827}"
        ;;
    full)
        main_args=(
            --run-id "$RUN_ID"
            --num-rounds "${COSQLI_NUM_ROUNDS:-8}"
            --num-training-sqls "${COSQLI_NUM_TRAINING_SQLS:-400}"
            --benchmark-dir "$BENCHMARK_DIR"
            --experiment-config "${COSQLI_EXPERIMENT_CONFIG:?Set COSQLI_EXPERIMENT_CONFIG through co-sqli-submit.}"
        )
        if [[ "${COSQLI_BREAKPOINT_ROUND:--1}" != "-1" ]]; then
            main_args+=(--breakpoint-round "$COSQLI_BREAKPOINT_ROUND")
        fi
        "$PYTHON_BIN" -m cosqli "${main_args[@]}"
        ;;
    *)
        echo "Unsupported COSQLI_MODE=${COSQLI_MODE:-}." >&2
        exit 2
        ;;
esac
