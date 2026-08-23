#!/usr/bin/env bash
#SBATCH --job-name=co-sqli
#SBATCH --partition=debug
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --output=/hpc2hdd/home/hpan285/experiment_results/slurm-%j.out
#SBATCH --error=/hpc2hdd/home/hpan285/experiment_results/slurm-%j.err

set -euo pipefail

PROJECT_ROOT="${COSQLI_PROJECT_ROOT:-${SLURM_SUBMIT_DIR:-}}"
if [[ -z "$PROJECT_ROOT" ]]; then
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
ENV_PREFIX="${COSQLI_ENV_PREFIX:?Set COSQLI_ENV_PREFIX to the Python environment.}"
RUNTIME_ROOT="${COSQLI_RUNTIME_ROOT:?Set COSQLI_RUNTIME_ROOT to the external runtime root.}"
MYSQL_ROOT="$RUNTIME_ROOT/mysql"
MYSQL_CNF="$MYSQL_ROOT/my.cnf"
MYSQLD="$MYSQL_ROOT/mysql-8.0.46-linux-glibc2.17-x86_64-minimal/bin/mysqld"
MYSQL_PID_FILE="$MYSQL_ROOT/mysql.pid"
MYSQL_SOCKET="$MYSQL_ROOT/mysql.sock"
PYTHON_BIN="$ENV_PREFIX/bin/python"
MYSQL_STARTED=0

cleanup() {
    local exit_status=$?
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
    exit "$exit_status"
}
trap cleanup EXIT INT TERM

if [[ ! -x "$MYSQLD" || ! -f "$MYSQL_CNF" ]]; then
    echo "MySQL runtime is incomplete under $MYSQL_ROOT" >&2
    exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Co-SQLi Python environment not found: $ENV_PREFIX" >&2
    exit 1
fi
if [[ -e "$MYSQL_PID_FILE" || -S "$MYSQL_SOCKET" ]]; then
    echo "Refusing to start MySQL: a prior pid file or socket exists in $MYSQL_ROOT." >&2
    exit 1
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$ENV_PREFIX/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1

(cd "$MYSQL_ROOT" && "$MYSQLD" --defaults-file=my.cnf --daemonize)
MYSQL_STARTED=1
for _ in {1..30}; do
    if "$PYTHON_BIN" "$PROJECT_ROOT/scripts/check_mysql_connection.py" --quiet; then
        break
    fi
    sleep 1
done
if ! "$PYTHON_BIN" "$PROJECT_ROOT/scripts/check_mysql_connection.py"; then
    tail -n 50 "$MYSQL_ROOT/logs/mysql.err" >&2 || true
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
            --output-dir "${COSQLI_BENCHMARK_OUTPUT_DIR:?Set COSQLI_BENCHMARK_OUTPUT_DIR.}"
        ;;
    full)
        main_args=()
        if [[ -n "${COSQLI_MAIN_ARGS:-}" ]]; then
            read -r -a main_args <<< "$COSQLI_MAIN_ARGS"
        fi
        "$PYTHON_BIN" -m cosqli "${main_args[@]}"
        ;;
    *)
        echo "Unsupported COSQLI_MODE=${COSQLI_MODE:-}." >&2
        exit 2
        ;;
esac
