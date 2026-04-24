"""One-command launcher.

Reads HOST / PORT / RELOAD from `.env` and boots uvicorn. This way the
operator never has to remember flags or export env vars — just:

    python run.py
"""
from __future__ import annotations

from config import load_env, get_bool, get_int, get_str


def main():
    load_env()
    host   = get_str("EXPERT_AUDIT_HOST", "0.0.0.0")
    port   = get_int("EXPERT_AUDIT_PORT", 8000)
    reload = get_bool("EXPERT_AUDIT_RELOAD", False)
    log    = get_str("EXPERT_AUDIT_LOG_LEVEL", "info")
    print(f"[run] http://{host}:{port}  (reload={reload}, log={log})")
    import uvicorn
    uvicorn.run("app:app", host=host, port=port, reload=reload, log_level=log)


if __name__ == "__main__":
    main()
