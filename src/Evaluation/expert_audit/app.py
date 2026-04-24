"""FastAPI backend for the expert audit web app.

Run locally:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Share via cloudflared:
    cloudflared tunnel --url http://localhost:8000

Endpoints
---------
  POST /login              {display_name, token} -> {expert_id, display_name,
                                                     is_new}
  GET  /api/next           ?token=...            -> sample | done
  POST /api/annotate       body: answer + token  -> {action}
  GET  /api/progress       ?token=...            -> {done,total,remaining}
  POST /api/back           ?token=...            -> deletes last + returns it
  GET  /admin/stats        ?admin_key=...        -> stats JSON
  GET  /admin/export       ?admin_key=...        -> CSV download

Static assets (answering UI + admin UI) live under /static.
The default "/" redirects to /static/index.html.
"""
from __future__ import annotations

import csv
import io
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
from config import load_env, get_str

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

# Load .env (once, at import time) so uvicorn workers inherit it too.
load_env()
ADMIN_KEY = get_str("EXPERT_AUDIT_ADMIN_KEY", "letmein")

app = FastAPI(title="SQLi Expert Audit", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/static/index.html", status_code=302)


# ---------------------------------------------------------------------------
# auth helpers

def _expert_from_token(token: str) -> dict:
    if not token:
        raise HTTPException(401, "missing token")
    rec = db.get_or_create_expert_lookup_only(token) if hasattr(
        db, "get_or_create_expert_lookup_only") else None
    # we don't have a dedicated lookup; piggy-back on get_or_create but don't
    # rename: the caller passes display_name=token if they only have a token
    raise HTTPException(500, "use the /login endpoint first")


def _lookup_by_token(token: str) -> Optional[dict]:
    c = db._conn()
    row = c.execute(
        "SELECT expert_id, display_name, token FROM experts WHERE token=?",
        (token,)).fetchone()
    return dict(row) if row else None


def _require_expert(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "missing token")
    rec = _lookup_by_token(token.strip())
    if rec is None:
        raise HTTPException(401, "unknown token; /login first")
    db.touch_expert(rec["expert_id"])
    return rec


# ---------------------------------------------------------------------------
# routes

class LoginBody(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)
    token: str = Field(..., min_length=4, max_length=64)


@app.post("/login")
def login(body: LoginBody):
    try:
        rec = db.get_or_create_expert(body.display_name, body.token)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return rec


@app.get("/api/next")
def api_next(token: str = Query(...)):
    ex = _require_expert(token)
    s = db.next_sample_for(ex["expert_id"])
    prog = db.progress_for(ex["expert_id"])
    if s is None:
        return {"done": True, "progress": prog}
    return {"done": False, "sample": s, "progress": prog}


class AnnotateBody(BaseModel):
    token: str
    sample_id: int
    q1: str
    q2: Optional[str] = None
    q3_attacks: Optional[list] = None
    notes: Optional[str] = None
    time_spent_ms: Optional[int] = None


@app.post("/api/annotate")
def api_annotate(body: AnnotateBody):
    ex = _require_expert(body.token)
    try:
        out = db.save_annotation(
            expert_id=ex["expert_id"],
            sample_id=body.sample_id,
            q1=body.q1,
            q2=body.q2,
            q3_attacks=body.q3_attacks,
            notes=body.notes,
            time_spent_ms=body.time_spent_ms,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return out


@app.get("/api/progress")
def api_progress(token: str = Query(...)):
    ex = _require_expert(token)
    return db.progress_for(ex["expert_id"])


@app.post("/api/back")
def api_back(token: str = Query(...)):
    """Delete last annotation; return the re-surfaced sample."""
    ex = _require_expert(token)
    last = db.last_annotation_for(ex["expert_id"])
    if last is None:
        raise HTTPException(400, "no prior annotation")
    db.delete_annotation(ex["expert_id"], last["sample_id"])
    s = db.sample_by_id(last["sample_id"])
    return {"sample": s, "prior_answer": {
        "q1": last["q1_verdict"], "q2": last["q2_flipping"],
        "q3_attacks": last["q3_attacks"], "notes": last["notes"],
    }}


# ---------------------------------------------------------------------------
# admin

def _check_admin(admin_key: str):
    if admin_key != ADMIN_KEY:
        raise HTTPException(403, "bad admin key")


@app.get("/admin/stats")
def admin_stats(admin_key: str = Query(...)):
    _check_admin(admin_key)
    return db.admin_stats()


@app.get("/admin/export")
def admin_export(admin_key: str = Query(...)):
    _check_admin(admin_key)
    rows = db.export_rows()
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename=expert_audit_export.csv"},
    )
