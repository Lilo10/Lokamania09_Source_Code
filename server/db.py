"""Lokamania 10: SQLite database (the master copy of every application).

The Google Sheet is only a mirror of this file. Every change bumps a row's
`version`; the Sheet sync marks rows as sent by recording `synced_version`.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from lm10_config import DEFAULT_STATUS, REFERENCE_PREFIX

FIELDS = [
    "brand", "launch_year", "registration", "contact", "phone", "email",
    "instagram", "website", "about", "category", "category_key", "subcategory",
    "days", "days_key", "space", "space_key", "products", "drop_offer",
    "price_range", "joined",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    seq            INTEGER PRIMARY KEY,
    reference      TEXT UNIQUE NOT NULL,
    submitted_at   TEXT NOT NULL,
    brand TEXT, launch_year INTEGER, registration TEXT, contact TEXT,
    phone TEXT, email TEXT, instagram TEXT, website TEXT, about TEXT,
    category TEXT, category_key TEXT, subcategory TEXT,
    days TEXT, days_key TEXT, space TEXT, space_key TEXT,
    products TEXT, drop_offer TEXT, price_range TEXT, joined TEXT,
    status         TEXT NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    last_updated   TEXT,
    version        INTEGER NOT NULL DEFAULT 1,
    synced_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS deleted_refs (
    reference TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL,
    synced INTEGER NOT NULL DEFAULT 0
);
"""


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    # ------------------------------------------------------------ writes
    def add(self, data):
        """Insert a new application and return its reference (LM10-0001…)."""
        with self.lock, self._conn() as c:
            # Reference numbers are never reused, so a deleted application's
            # number can't be confused with a new one. The one exception: when
            # every application has been deleted (e.g. after launch-day tests),
            # numbering starts again at 0001.
            count = c.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            last = c.execute("SELECT value FROM meta WHERE key='last_seq'").fetchone()
            seq = 1 if count == 0 else int(last["value"] if last else 0) + 1
            top = c.execute("SELECT MAX(seq) FROM applications").fetchone()[0] or 0
            seq = max(seq, top + 1)
            c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_seq', ?)", (str(seq),))
            reference = f"{REFERENCE_PREFIX}{seq:04d}"
            now = utc_now_iso()
            cols = ["seq", "reference", "submitted_at", "status", "last_updated"] + FIELDS
            vals = [seq, reference, now, DEFAULT_STATUS, now] + [data.get(f) for f in FIELDS]
            c.execute(
                f"INSERT INTO applications ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                vals,
            )
            # A reference that was deleted earlier and is now reused must not be
            # removed from the Sheet by a pending delete.
            c.execute("DELETE FROM deleted_refs WHERE reference=?", (reference,))
            return reference

    def update(self, reference, status=None, notes=None):
        sets, vals = [], []
        if status is not None:
            sets.append("status=?"); vals.append(status)
        if notes is not None:
            sets.append("notes=?"); vals.append(notes)
        if not sets:
            return
        sets += ["last_updated=?", "version=version+1"]
        vals += [utc_now_iso(), reference]
        with self.lock, self._conn() as c:
            cur = c.execute(f"UPDATE applications SET {','.join(sets)} WHERE reference=?", vals)
            if cur.rowcount == 0:
                raise KeyError(reference)

    def bulk_status(self, references, status):
        now = utc_now_iso()
        with self.lock, self._conn() as c:
            n = 0
            for ref in references:
                n += c.execute(
                    "UPDATE applications SET status=?, last_updated=?, version=version+1 WHERE reference=?",
                    (status, now, ref),
                ).rowcount
            return n

    def delete(self, reference):
        with self.lock, self._conn() as c:
            cur = c.execute("DELETE FROM applications WHERE reference=?", (reference,))
            if cur.rowcount == 0:
                raise KeyError(reference)
            c.execute(
                "INSERT OR REPLACE INTO deleted_refs (reference, deleted_at, synced) VALUES (?,?,0)",
                (reference, utc_now_iso()),
            )

    # ------------------------------------------------------------- reads
    def all(self):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM applications ORDER BY seq").fetchall()
        return [dict(r) for r in rows]

    def get(self, reference):
        with self._conn() as c:
            r = c.execute("SELECT * FROM applications WHERE reference=?", (reference,)).fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------- sync helpers
    def pending(self, limit=50):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM applications WHERE version > synced_version ORDER BY seq LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def pending_count(self):
        with self._conn() as c:
            a = c.execute("SELECT COUNT(*) FROM applications WHERE version > synced_version").fetchone()[0]
            d = c.execute("SELECT COUNT(*) FROM deleted_refs WHERE synced=0").fetchone()[0]
        return a + d

    def pending_deletes(self):
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT reference FROM deleted_refs WHERE synced=0")]

    def mark_synced(self, versions):
        """versions: {reference: version that was sent}."""
        with self.lock, self._conn() as c:
            for ref, ver in versions.items():
                c.execute(
                    "UPDATE applications SET synced_version=? WHERE reference=? AND version>=?",
                    (ver, ref, ver),
                )

    def mark_deletes_synced(self, references):
        with self.lock, self._conn() as c:
            for ref in references:
                c.execute("UPDATE deleted_refs SET synced=1 WHERE reference=?", (ref,))

    def backup_to(self, dest):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = self._conn()
        try:
            out = sqlite3.connect(str(dest))
            with out:
                src.backup(out)
            out.close()
        finally:
            src.close()


# ----------------------------------------------------------- duplicates
def _norm_ig(v):
    v = (v or "").strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^(www\.)?instagram\.com/", "", v)
    return v.strip("@/ ").split("?")[0]


def _norm_phone(v):
    d = re.sub(r"\D", "", v or "")
    return d[-10:] if len(d) >= 8 else ""


def _norm_brand(v):
    return re.sub(r"[^a-z0-9؀-ۿ]", "", (v or "").lower())


def find_duplicates(records):
    """{reference: [other references that share brand, Instagram, email or phone]}."""
    keys = {}
    for r in records:
        for kind, val in (("ig", _norm_ig(r.get("instagram"))),
                          ("email", (r.get("email") or "").strip().lower()),
                          ("phone", _norm_phone(r.get("phone"))),
                          ("brand", _norm_brand(r.get("brand")))):
            if val:
                keys.setdefault((kind, val), []).append(r["reference"])
    out = {}
    for refs in keys.values():
        if len(refs) > 1:
            for ref in refs:
                out.setdefault(ref, set()).update(x for x in refs if x != ref)
    return {k: sorted(v) for k, v in out.items()}
