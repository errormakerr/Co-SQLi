#!/usr/bin/env bash
#SBATCH --job-name=sqli
#SBATCH --partition=debug
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:30:00

set -euo pipefail

# sbatch copies this script to a node-local spool directory. SLURM_SUBMIT_DIR
# retains the directory from which the user submitted the job.
PROJECT_ROOT="${SQLI_PROJECT_ROOT:-${SLURM_SUBMIT_DIR:-}}"
if [[ -z "$PROJECT_ROOT" ]]; then
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
CONDA_ROOT="${CONDA_ROOT:-/hpc2ssd/softwares/anaconda3}"
ENV_PREFIX="${SQLI_ENV_PREFIX:-${HOME}/envs/cosqli}"
MYSQL_ROOT="$PROJECT_ROOT/.local/mysql"
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
            echo "Stopping job-local MySQL (pid=$mysql_pid)"
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
    echo "SQLI Python environment not found: $ENV_PREFIX" >&2
    exit 1
fi
if [[ -e "$MYSQL_PID_FILE" || -S "$MYSQL_SOCKET" ]]; then
    echo "Refusing to start MySQL: $MYSQL_PID_FILE or $MYSQL_SOCKET already exists." >&2
    echo "Stop the existing MySQL server cleanly before submitting this job." >&2
    exit 1
fi

source "$CONDA_ROOT/etc/profile.d/conda.sh"
conda activate "$ENV_PREFIX"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting job-local MySQL on $(hostname)"
"$MYSQLD" --defaults-file="$MYSQL_CNF" --daemonize
MYSQL_STARTED=1

for _ in {1..30}; do
    if "$PYTHON_BIN" "$PROJECT_ROOT/scripts/check_mysql_connection.py" --quiet; then
        break
    fi
    sleep 1
done

if ! "$PYTHON_BIN" "$PROJECT_ROOT/scripts/check_mysql_connection.py"; then
    echo "MySQL did not become ready; recent server log follows:" >&2
    tail -n 50 "$MYSQL_ROOT/logs/mysql.err" >&2 || true
    exit 1
fi

case "${SQLI_MODE:-db-check}" in
    db-check)
        echo "MySQL sidecar preflight completed successfully."
        ;;
    generate-smoke)
        "$PYTHON_BIN" "$PROJECT_ROOT/scripts/generate_smoke.py" \
            --samples "${SQLI_SMOKE_SAMPLES:-12}"
        ;;
    mutation-smoke)
        "$PYTHON_BIN" "$PROJECT_ROOT/scripts/mutation_smoke.py"
        ;;
    full)
        main_args=()
        if [[ -n "${SQLI_MAIN_ARGS:-}" ]]; then
            read -r -a main_args <<< "$SQLI_MAIN_ARGS"
        fi
        "$PYTHON_BIN" "$PROJECT_ROOT/src/main.py" "${main_args[@]}"
        ;;
    *)
        echo "Unsupported SQLI_MODE=${SQLI_MODE:-}. Use db-check, generate-smoke, mutation-smoke, or full." >&2
        exit 2
        ;;
esac
