"""Lokamania 10: one-way mirror from the database to the Google Sheet.

The website never waits for Google. Every new application or admin change is
saved in the database first; this background thread then pushes it to the
Apps Script web app attached to the Sheet:

  * changed rows are sent within a few seconds ("upsert"),
  * deleted rows are removed ("delete"),
  * every 15 minutes the whole table is re-sent ("replace_all"), which also
    repairs anything someone typed into the protected tabs.

If Google is down, nothing is lost: rows stay marked as unsent and are retried.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from lm10_config import SHEET_COLUMNS

FULL_REFRESH_SECONDS = 15 * 60
CHECK_SECONDS = 2
TIMEOUT_SECONDS = 60


class SheetSync:
    def __init__(self, db, url, secret, to_cairo, logger):
        self.db = db
        self.url = (url or "").strip()
        self.secret = (secret or "").strip()
        self.to_cairo = to_cairo
        self.log = logger
        self.wake = threading.Event()
        self.force_full = threading.Event()
        self.state = {
            "configured": bool(self.url and self.secret),
            "last_ok": None, "last_full": None, "last_error": None,
            "last_error_at": None, "in_progress": False,
        }
        self._thread = None

    # --------------------------------------------------------- public API
    def start(self):
        if not self.state["configured"] or self._thread:
            return
        self.force_full.set()  # mirror everything once at start-up
        self._thread = threading.Thread(target=self._run, name="sheet-sync", daemon=True)
        self._thread.start()

    def nudge(self):
        self.wake.set()

    def resync(self):
        self.force_full.set()
        self.wake.set()

    def status(self):
        s = dict(self.state)
        s["pending"] = self.db.pending_count()
        return s

    # ----------------------------------------------------------- internals
    def _row(self, r):
        out = []
        for key, _label in SHEET_COLUMNS:
            v = r.get(key)
            if key in ("submitted_at", "last_updated"):
                v = self.to_cairo(v)
            out.append("" if v is None else v)
        return out

    def _post(self, payload):
        payload = dict(payload, secret=self.secret,
                       headers=[label for _k, label in SHEET_COLUMNS])
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        # Apps Script answers a POST with a redirect to the result page;
        # urllib follows it with a GET, which is exactly what Google expects.
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", "replace")
        try:
            data = json.loads(body)
        except ValueError:
            raise RuntimeError("The Sheet script did not answer with JSON. "
                               "Check the web app link and that access is set to 'Anyone'.")
        if not data.get("ok"):
            raise RuntimeError(f"Sheet script error: {data.get('error') or 'unknown'}")
        return data

    def _full(self):
        rows = self.db.all()
        self._post({"action": "replace_all", "rows": [self._row(r) for r in rows]})
        self.db.mark_synced({r["reference"]: r["version"] for r in rows})
        self.db.mark_deletes_synced(self.db.pending_deletes())
        self.state["last_full"] = time.time()

    def _incremental(self):
        deletes = self.db.pending_deletes()
        if deletes:
            self._post({"action": "delete", "references": deletes})
            self.db.mark_deletes_synced(deletes)
        while True:
            rows = self.db.pending(limit=50)
            if not rows:
                break
            self._post({"action": "upsert", "rows": [self._row(r) for r in rows]})
            self.db.mark_synced({r["reference"]: r["version"] for r in rows})

    def _run(self):
        backoff = CHECK_SECONDS
        while True:
            self.wake.wait(timeout=backoff)
            self.wake.clear()
            try:
                self.state["in_progress"] = True
                due = (self.state["last_full"] is None
                       or time.time() - self.state["last_full"] >= FULL_REFRESH_SECONDS)
                if self.force_full.is_set() or due:
                    self._full()
                    self.force_full.clear()  # only once it has really gone through
                elif self.db.pending_count():
                    self._incremental()
                self.state["last_ok"] = time.time()
                self.state["last_error"] = None
                backoff = CHECK_SECONDS
            except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
                self.state["last_error"] = str(exc)[:300]
                self.state["last_error_at"] = time.time()
                self.log.warning("Sheet sync failed: %s", exc)
                backoff = min(max(backoff * 2, 10), 300)  # retry: 10 s … 5 min
            except Exception as exc:  # never let the thread die
                self.state["last_error"] = f"Unexpected error: {exc}"[:300]
                self.state["last_error_at"] = time.time()
                self.log.exception("Sheet sync crashed")
                backoff = 60
            finally:
                self.state["in_progress"] = False
