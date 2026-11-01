"""SQLite storage. One connection per operation (safe across threads), WAL mode."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
  id TEXT PRIMARY KEY,
  received_at TEXT NOT NULL,
  completed_at TEXT,
  channel TEXT NOT NULL,
  channel_ref TEXT,
  input_type TEXT NOT NULL,
  input_text TEXT,
  media_ref TEXT,
  media_path TEXT,
  media_mime TEXT,
  media_bytes INTEGER,
  media_sha256 TEXT,
  language TEXT,
  transcript TEXT,
  status TEXT NOT NULL,
  error TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_id TEXT NOT NULL,
  claim_key TEXT NOT NULL,
  claim_text TEXT NOT NULL,
  exact_quote TEXT,
  numbers_json TEXT
);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_id TEXT NOT NULL,
  engine TEXT NOT NULL,
  kind TEXT NOT NULL,
  strength REAL NOT NULL,
  weight REAL NOT NULL,
  summary TEXT,
  limitation TEXT,
  evidence_json TEXT,
  mock INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdicts (
  check_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  confidence REAL NOT NULL,
  top_reasons_json TEXT,
  contributions_json TEXT,
  by_engine_json TEXT,
  explanation_json TEXT,
  fusion TEXT
);
CREATE TABLE IF NOT EXISTS engine_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_id TEXT NOT NULL,
  engine TEXT NOT NULL,
  status TEXT NOT NULL,
  mock INTEGER NOT NULL DEFAULT 0,
  ms INTEGER,
  attempts INTEGER,
  error TEXT,
  notes_json TEXT
);
CREATE TABLE IF NOT EXISTS media_index (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_sha256 TEXT UNIQUE,
  phash TEXT NOT NULL,
  dhash TEXT,
  first_seen TEXT NOT NULL,
  original_url TEXT,
  title TEXT,
  source TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_check ON claims(check_id);
CREATE INDEX IF NOT EXISTS idx_signals_check ON signals(check_id);
CREATE INDEX IF NOT EXISTS idx_runs_check ON engine_runs(check_id);
CREATE INDEX IF NOT EXISTS idx_checks_received ON checks(received_at);
CREATE INDEX IF NOT EXISTS idx_media_phash ON media_index(phash);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_check_id() -> str:
    return "chk_" + secrets.token_hex(5)


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


class DB:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- writes -------------------------------------------------------
    def create_check(self, *, channel: str, channel_ref: Optional[str], input_type: str,
                     text: str, media: Optional[dict]) -> str:
        cid = new_check_id()
        m = media or {}
        with self._conn() as c:
            c.execute(
                "INSERT INTO checks(id,received_at,channel,channel_ref,input_type,input_text,"
                "media_ref,media_path,media_mime,media_bytes,media_sha256,status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,'received')",
                (cid, now_iso(), channel, channel_ref, input_type, text,
                 m.get("ref"), m.get("path"), m.get("mime"), m.get("bytes"), m.get("sha256")),
            )
        return cid

    def set_status(self, cid: str, status: str, error: Optional[str] = None) -> None:
        done = now_iso() if status in ("done", "failed") else None
        with self._conn() as c:
            c.execute("UPDATE checks SET status=?, error=?, completed_at=COALESCE(?,completed_at) WHERE id=?",
                      (status, error, done, cid))

    def set_text_fields(self, cid: str, language: Optional[str], transcript: Optional[str]) -> None:
        with self._conn() as c:
            if language:
                c.execute("UPDATE checks SET language=? WHERE id=?", (language, cid))
            if transcript:
                c.execute("UPDATE checks SET transcript=? WHERE id=?", (transcript, cid))

    def save_claims(self, cid: str, claims: Iterable[dict]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM claims WHERE check_id=?", (cid,))
            for cl in claims:
                c.execute("INSERT INTO claims(check_id,claim_key,claim_text,exact_quote,numbers_json) VALUES(?,?,?,?,?)",
                          (cid, cl["id"], cl["text"], cl.get("quote", ""), _j(cl.get("numbers", []))))

    def add_signals(self, cid: str, signals: Iterable[dict]) -> None:
        with self._conn() as c:
            for s in signals:
                c.execute(
                    "INSERT INTO signals(check_id,engine,kind,strength,weight,summary,limitation,evidence_json,mock,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (cid, s["engine"], s["kind"], s["strength"], s["weight"], s.get("summary", ""),
                     s.get("limitation", ""), _j(s.get("evidence", {})), 1 if s.get("mock") else 0, now_iso()))

    def add_engine_run(self, cid: str, run: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO engine_runs(check_id,engine,status,mock,ms,attempts,error,notes_json) VALUES(?,?,?,?,?,?,?,?)",
                      (cid, run["engine"], run["status"], 1 if run.get("mock") else 0, run.get("ms"),
                       run.get("attempts"), run.get("error"), _j(run.get("notes", []))))

    def save_verdict(self, cid: str, verdict: dict, explanation: dict, fusion: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO verdicts(check_id,label,confidence,top_reasons_json,contributions_json,"
                      "by_engine_json,explanation_json,fusion) VALUES(?,?,?,?,?,?,?,?)",
                      (cid, verdict["label"], verdict["confidence"], _j(verdict.get("topReasons", [])),
                       _j(verdict.get("contributions", [])), _j(verdict.get("byEngine", {})), _j(explanation), fusion))

    def fail_stale(self, older_than_s: int) -> int:
        """Called at startup: anything still 'received'/'processing' from a dead process is failed."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._conn() as c:
            cur = c.execute("UPDATE checks SET status='failed', error='Server restarted before this check finished', "
                            "completed_at=? WHERE status IN ('received','processing') AND received_at<=?",
                            (now_iso(), cutoff))
            return cur.rowcount

    # ---- reads --------------------------------------------------------
    def get_record(self, cid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone()
            if not r:
                return None
            claims = c.execute("SELECT * FROM claims WHERE check_id=? ORDER BY id", (cid,)).fetchall()
            sigs = c.execute("SELECT * FROM signals WHERE check_id=? ORDER BY id", (cid,)).fetchall()
            runs = c.execute("SELECT * FROM engine_runs WHERE check_id=? ORDER BY id", (cid,)).fetchall()
            v = c.execute("SELECT * FROM verdicts WHERE check_id=?", (cid,)).fetchone()
        rec: dict[str, Any] = {
            "checkId": r["id"],
            "receivedAt": r["received_at"],
            "completedAt": r["completed_at"],
            "channel": r["channel"],
            "input": {
                "type": r["input_type"], "text": r["input_text"] or "", "mediaRef": r["media_ref"],
                "mediaSha256": r["media_sha256"], "mediaMime": r["media_mime"], "mediaBytes": r["media_bytes"],
                "language": r["language"], "transcript": r["transcript"],
            },
            "claims": [{"id": x["claim_key"], "text": x["claim_text"], "quote": x["exact_quote"] or "",
                        "numbers": json.loads(x["numbers_json"] or "[]")} for x in claims],
            "signals": [{"engine": x["engine"], "kind": x["kind"], "strength": x["strength"], "weight": x["weight"],
                         "summary": x["summary"] or "", "limitation": x["limitation"] or "",
                         "evidence": json.loads(x["evidence_json"] or "{}"), "mock": bool(x["mock"])} for x in sigs],
            "engineRuns": [{"engine": x["engine"], "status": x["status"], "mock": bool(x["mock"]), "ms": x["ms"],
                            "attempts": x["attempts"], "error": x["error"],
                            "notes": json.loads(x["notes_json"] or "[]")} for x in runs],
            "verdict": None,
            "explanation": None,
            "status": r["status"],
            "error": r["error"],
        }
        if v:
            rec["verdict"] = {"label": v["label"], "confidence": v["confidence"],
                              "topReasons": json.loads(v["top_reasons_json"] or "[]"),
                              "contributions": json.loads(v["contributions_json"] or "[]"),
                              "byEngine": json.loads(v["by_engine_json"] or "{}"), "fusion": v["fusion"]}
            rec["explanation"] = json.loads(v["explanation_json"] or "null")
        return rec

    def media_path(self, cid: str) -> Optional[tuple[str, str]]:
        with self._conn() as c:
            r = c.execute("SELECT media_path, media_mime FROM checks WHERE id=?", (cid,)).fetchone()
        return (r["media_path"], r["media_mime"]) if r and r["media_path"] else None

    def channel_ref(self, cid: str) -> Optional[str]:
        with self._conn() as c:
            r = c.execute("SELECT channel_ref FROM checks WHERE id=?", (cid,)).fetchone()
        return r["channel_ref"] if r else None

    def list_checks(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT c.id, c.received_at, c.channel, c.input_type, c.input_text, c.status, "
                "v.label, v.confidence FROM checks c LEFT JOIN verdicts v ON v.check_id=c.id "
                "ORDER BY c.received_at DESC, c.rowid DESC LIMIT ?", (limit,)).fetchall()
        return [{"checkId": r["id"], "receivedAt": r["received_at"], "channel": r["channel"],
                 "type": r["input_type"], "preview": (r["input_text"] or "")[:120], "status": r["status"],
                 "label": r["label"], "confidence": r["confidence"]} for r in rows]

    def trending(self, hours: int = 24, limit: int = 5) -> list[dict]:
        """Claims checked more than once on this platform recently (real data from our own checks)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._conn() as c:
            rows = c.execute(
                "SELECT lower(trim(cl.claim_text)) AS k, MIN(cl.claim_text) AS text, COUNT(DISTINCT cl.check_id) AS n, "
                "MAX(ch.received_at) AS last_seen FROM claims cl JOIN checks ch ON ch.id=cl.check_id "
                "WHERE ch.received_at>=? GROUP BY k HAVING n>=2 ORDER BY n DESC, last_seen DESC LIMIT ?",
                (cutoff, limit)).fetchall()
        return [{"claim": r["text"], "checks": r["n"], "lastSeen": r["last_seen"]} for r in rows]

    def index_media(self, sha256: str, phash: str, dhash: str = "", first_seen: str = "",
                    original_url: str = "", title: str = "", source: str = "") -> None:
        """Store a known media perceptual hash in the reverse image/video index."""
        first_seen = first_seen or now_iso()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO media_index (media_sha256, phash, dhash, first_seen, original_url, title, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sha256, phash, dhash, first_seen, original_url, title, source))

    def search_media_by_hash(self, target_phash: str, max_distance: int = 10) -> list[dict]:
        """Find matching known media entries whose perceptual hash Hamming distance <= max_distance."""
        if not target_phash:
            return []
        try:
            target_int = int(target_phash, 16)
        except ValueError:
            return []
        with self._conn() as c:
            rows = c.execute("SELECT * FROM media_index").fetchall()
        matches = []
        for r in rows:
            p = r["phash"]
            try:
                p_int = int(p, 16)
                dist = bin(target_int ^ p_int).count("1")
                if dist <= max_distance:
                    matches.append({
                        "id": r["id"],
                        "sha256": r["media_sha256"],
                        "firstSeen": r["first_seen"],
                        "originalUrl": r["original_url"],
                        "title": r["title"],
                        "source": r["source"],
                        "distance": dist,
                    })
            except ValueError:
                continue
        matches.sort(key=lambda x: (x["distance"], x["firstSeen"]))
        return matches
