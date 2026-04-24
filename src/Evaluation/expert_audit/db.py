"""Thin sqlite3 layer for the expert audit app.

Keeps connections thread-local (FastAPI uses a threadpool for sync routes)
and serializes writes behind a module lock.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "expert_audit.db")

_local = threading.local()
_write_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


@contextmanager
def tx():
    c = _conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


# ---------------------------------------------------------------------------
# expert ops

def get_or_create_expert(display_name: str, token: str) -> dict:
    display_name = (display_name or "").strip()[:64]
    token = (token or "").strip()[:64]
    if not display_name or not token:
        raise ValueError("display_name and token are required")
    with _write_lock, tx() as c:
        row = c.execute("SELECT * FROM experts WHERE token=?", (token,)).fetchone()
        now = _now()
        if row is None:
            cur = c.execute(
                "INSERT INTO experts(display_name, token, started_at, last_seen) "
                "VALUES (?,?,?,?)",
                (display_name, token, now, now),
            )
            expert_id = cur.lastrowid
            return {"expert_id": expert_id, "display_name": display_name,
                    "token": token, "is_new": True}
        c.execute("UPDATE experts SET last_seen=?, display_name=? WHERE expert_id=?",
                  (now, display_name, row["expert_id"]))
        return {"expert_id": row["expert_id"], "display_name": display_name,
                "token": token, "is_new": False}


def touch_expert(expert_id: int):
    with _write_lock, tx() as c:
        c.execute("UPDATE experts SET last_seen=? WHERE expert_id=?",
                  (_now(), expert_id))


# ---------------------------------------------------------------------------
# sample ops

def next_sample_for(expert_id: int) -> Optional[dict]:
    """Return the next unanswered sample for this expert, ordered by
    assigned_order.  None if all 1019 are done."""
    c = _conn()
    row = c.execute(
        """
        SELECT s.sample_id, s.dataset, s.sql, s.is_calibration, s.assigned_order
        FROM samples s
        LEFT JOIN annotations a
             ON a.sample_id = s.sample_id AND a.expert_id = ?
        WHERE a.annotation_id IS NULL
        ORDER BY s.assigned_order
        LIMIT 1
        """,
        (expert_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "sample_id": row["sample_id"],
        "dataset": row["dataset"],
        "sql": row["sql"],
        "is_calibration": bool(row["is_calibration"]),
        "position": row["assigned_order"],
    }


def progress_for(expert_id: int) -> dict:
    c = _conn()
    total = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    done = c.execute(
        "SELECT COUNT(*) FROM annotations WHERE expert_id=?",
        (expert_id,),
    ).fetchone()[0]
    return {"done": done, "total": total, "remaining": total - done}


def sample_by_id(sample_id: int) -> Optional[dict]:
    c = _conn()
    row = c.execute("SELECT sample_id, dataset, sql, is_calibration, "
                    "assigned_order FROM samples WHERE sample_id=?",
                    (sample_id,)).fetchone()
    if row is None:
        return None
    return {
        "sample_id": row["sample_id"],
        "dataset": row["dataset"],
        "sql": row["sql"],
        "is_calibration": bool(row["is_calibration"]),
        "position": row["assigned_order"],
    }


# ---------------------------------------------------------------------------
# annotation ops

VALID_Q1 = {"mal", "ben", "ambiguous", "invalid"}
VALID_Q2 = {"yes", "no", None}


def save_annotation(expert_id: int, sample_id: int,
                    q1: str, q2: Optional[str],
                    q3_attacks: Optional[list], notes: Optional[str],
                    time_spent_ms: Optional[int]) -> dict:
    if q1 not in VALID_Q1:
        raise ValueError(f"invalid q1: {q1!r}")
    if q2 is not None and q2 not in VALID_Q2:
        raise ValueError(f"invalid q2: {q2!r}")
    # q3 only valid when q1 == 'mal'
    q3_json = None
    if q1 == "mal" and q3_attacks:
        q3_json = json.dumps(list(q3_attacks), ensure_ascii=False)
    # q2 only makes sense when q1 in {'mal','ben'} (ambiguous/invalid don't flip)
    if q1 not in {"mal", "ben"}:
        q2 = None
    notes = (notes or "")[:4000] or None

    with _write_lock, tx() as c:
        exists = c.execute(
            "SELECT 1 FROM annotations WHERE sample_id=? AND expert_id=?",
            (sample_id, expert_id)).fetchone()
        if exists:
            c.execute(
                """UPDATE annotations SET q1_verdict=?, q2_flipping=?,
                   q3_attacks=?, notes=?, submitted_at=?, time_spent_ms=?
                   WHERE sample_id=? AND expert_id=?""",
                (q1, q2, q3_json, notes, _now(), time_spent_ms,
                 sample_id, expert_id),
            )
            action = "updated"
        else:
            c.execute(
                """INSERT INTO annotations(sample_id, expert_id, q1_verdict,
                   q2_flipping, q3_attacks, notes, submitted_at, time_spent_ms)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (sample_id, expert_id, q1, q2, q3_json, notes, _now(),
                 time_spent_ms),
            )
            action = "inserted"
    return {"action": action, "sample_id": sample_id, "expert_id": expert_id}


def last_annotation_for(expert_id: int) -> Optional[dict]:
    c = _conn()
    row = c.execute(
        """SELECT a.*, s.dataset, s.sql, s.is_calibration, s.assigned_order
           FROM annotations a JOIN samples s USING(sample_id)
           WHERE a.expert_id=?
           ORDER BY a.submitted_at DESC LIMIT 1""",
        (expert_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def delete_annotation(expert_id: int, sample_id: int):
    with _write_lock, tx() as c:
        c.execute("DELETE FROM annotations WHERE expert_id=? AND sample_id=?",
                  (expert_id, sample_id))


# ---------------------------------------------------------------------------
# admin

def admin_stats() -> dict:
    c = _conn()
    total_samples = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    experts = [dict(r) for r in c.execute(
        """SELECT e.expert_id, e.display_name, e.started_at, e.last_seen,
                  (SELECT COUNT(*) FROM annotations a WHERE a.expert_id=e.expert_id) AS done
           FROM experts e ORDER BY e.expert_id""").fetchall()]
    per_dataset = [dict(r) for r in c.execute(
        """SELECT s.dataset,
                  COUNT(DISTINCT s.sample_id) AS n_samples,
                  COUNT(a.annotation_id) AS n_annotations
           FROM samples s LEFT JOIN annotations a USING(sample_id)
           GROUP BY s.dataset ORDER BY s.dataset""").fetchall()]
    return {"total_samples": total_samples,
            "experts": experts,
            "per_dataset": per_dataset}


def export_rows():
    c = _conn()
    rows = c.execute(
        """SELECT a.annotation_id, a.sample_id, a.expert_id,
                  e.display_name AS expert_name,
                  s.dataset, s.row_idx, s.sql, s.orig_label, s.is_calibration,
                  a.q1_verdict, a.q2_flipping, a.q3_attacks, a.notes,
                  a.submitted_at, a.time_spent_ms
           FROM annotations a
           JOIN samples s USING(sample_id)
           JOIN experts e USING(expert_id)
           ORDER BY a.submitted_at""").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
