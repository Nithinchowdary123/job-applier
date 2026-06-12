"""
job_tracker.py
──────────────
SQLite-backed store for:
  - Duplicate application detection (checks URL + company+title pair)
  - Persistent application log (fallback when Excel tracker is missing)
  - Unanswered question log (for human review)
"""
from __future__ import annotations
import sqlite3, os, hashlib
from datetime import datetime

DB_PATH = os.path.expanduser("~/job-applier/job_tracker.db")
UNANSWERED_LOG = os.path.expanduser("~/job-applier/unanswered_questions.log")

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash    TEXT UNIQUE,
            url         TEXT,
            job_title   TEXT,
            company     TEXT,
            platform    TEXT,
            status      TEXT DEFAULT 'Applied',
            applied_at  TEXT,
            resume_used TEXT,
            match_score REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS unanswered_questions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            question     TEXT,
            job_title    TEXT,
            company      TEXT,
            platform     TEXT,
            logged_at    TEXT
        );
        """)

def _url_hash(url: str, company: str, job_title: str) -> str:
    """Stable fingerprint — normalise URL + strip query params."""
    base = url.split("?")[0].rstrip("/").lower()
    key  = f"{base}|{company.lower()}|{job_title.lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]

def already_applied(url: str, company: str, job_title: str) -> bool:
    """Return True if we've already applied to this job."""
    init_db()
    h = _url_hash(url, company, job_title)
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM applications WHERE url_hash = ?", (h,)
        ).fetchone()
    return row is not None

def record_application(url: str, job_title: str, company: str,
                        platform: str, resume_used: str = "",
                        match_score: float = 0.0):
    """Persist a successful application."""
    init_db()
    h = _url_hash(url, company, job_title)
    with _conn() as con:
        con.execute("""
            INSERT OR IGNORE INTO applications
              (url_hash, url, job_title, company, platform, applied_at, resume_used, match_score)
            VALUES (?,?,?,?,?,?,?,?)
        """, (h, url, job_title, company, platform,
              datetime.now().isoformat(), resume_used, match_score))

def log_unanswered_question(question: str, job_title: str,
                             company: str, platform: str):
    """Save a question the bot couldn't confidently answer."""
    init_db()
    with _conn() as con:
        con.execute("""
            INSERT INTO unanswered_questions
              (question, job_title, company, platform, logged_at)
            VALUES (?,?,?,?,?)
        """, (question, job_title, company, platform,
              datetime.now().isoformat()))
    # Also append to human-readable log file
    with open(UNANSWERED_LOG, "a") as f:
        f.write(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
            f"{platform} | {company} | {job_title}\n"
            f"  Q: {question}\n\n"
        )

def get_stats() -> dict:
    init_db()
    with _conn() as con:
        total   = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        by_plat = con.execute(
            "SELECT platform, COUNT(*) FROM applications GROUP BY platform"
        ).fetchall()
        unanswered = con.execute(
            "SELECT COUNT(*) FROM unanswered_questions"
        ).fetchone()[0]
    return {
        "total": total,
        "by_platform": {r[0]: r[1] for r in by_plat},
        "unanswered_questions": unanswered,
    }
