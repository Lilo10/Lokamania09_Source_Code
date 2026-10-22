"""Lokamania 10: Flask server.

Serves the public site, the admin page and a small JSON API. Applications are
stored in a SQLite database (the master copy) and mirrored one way to the
Lokamania 10 Google Sheet.

Environment variables:
  ADMIN_PASSWORD         password for /admin (required, 12+ characters)
  DATABASE_PATH          SQLite file (Railway: /data/lokamania10.db)
  SHEET_WEBAPP_URL       Apps Script web app link (…/exec); empty = no Sheet sync
  SHEET_SECRET           secret code shared with the Apps Script
  MAINTENANCE_MODE       1 = show the "website on hold" page and stop applications
  PREVIEW_KEY            lets the team open the real site while on hold: /?preview=<key>
  APPLICATIONS_CLOSE_AT  deadline in Cairo time (default 2026-11-12T23:59:59)
  BACKUP_DIR             where nightly database backups go (default: next to the database)
  PORT                   port to listen on (default: 5000)
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

import lm10_config as cfg
from db import Database, find_duplicates
from sheet_sync import SheetSync

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env(path):
    """Tiny dependency-free .env loader. Real env vars always win."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_env(PROJECT_ROOT / ".env")


def _required_env(name, *, hint):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"\nERROR: {name} is not set, so the server cannot start safely.\n"
            f"       {hint}\n\n"
            f"       Local machine? Check the .env file in the project root:\n"
            f"         {PROJECT_ROOT / '.env'}\n"
            f"       Deployed on Railway? Set it under Settings -> Variables.\n"
        )
    return value


def _flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


ADMIN_PASSWORD = _required_env("ADMIN_PASSWORD", hint="Use a long random password.")
if len(ADMIN_PASSWORD) < 12:
    raise SystemExit("\nERROR: ADMIN_PASSWORD is too short (minimum 12 characters).\n")

DATABASE_PATH = os.environ.get("DATABASE_PATH", "").strip() or str(
    PROJECT_ROOT / "local-data" / "lokamania10.db")
PORT = int(os.environ.get("PORT", "5000"))
MAINTENANCE_MODE = _flag("MAINTENANCE_MODE")
PREVIEW_KEY = os.environ.get("PREVIEW_KEY", "").strip()
PREVIEW_COOKIE = "lm_preview"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lokamania")


# ------------------------------------------------------------------ time
try:
    from zoneinfo import ZoneInfo
    CAIRO = ZoneInfo("Africa/Cairo")
except Exception:  # no time-zone data on this machine: Egypt in November is UTC+2
    CAIRO = timezone(timedelta(hours=2))
    log.warning("Time-zone data not found; using UTC+2 for Cairo.")


def to_cairo(iso):
    """'2026-10-22T10:05:00+00:00' -> '2026-10-22 13:05' (Cairo)."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone(CAIRO).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def _close_at():
    raw = os.environ.get("APPLICATIONS_CLOSE_AT", "").strip() or cfg.DEFAULT_CLOSE_AT
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CAIRO)
    return dt


CLOSE_AT = _close_at()


def applications_open():
    return datetime.now(timezone.utc) <= CLOSE_AT


# ------------------------------------------------------------- database
db = Database(DATABASE_PATH)
sync = SheetSync(db, os.environ.get("SHEET_WEBAPP_URL"), os.environ.get("SHEET_SECRET"),
                 to_cairo, log)
sync.start()

app = Flask(__name__, static_folder=None)


def _backup_loop():
    """Copy the database once a day; keep 30 days of copies."""
    backup_dir = Path(os.environ.get("BACKUP_DIR", "").strip()
                      or Path(DATABASE_PATH).parent / "backups")
    while True:
        try:
            stamp = datetime.now(CAIRO).strftime("%Y%m%d")
            dest = backup_dir / f"lokamania10_{stamp}.db"
            if not dest.exists():
                db.backup_to(dest)
                log.info("Database backup written: %s", dest)
            copies = sorted(backup_dir.glob("lokamania10_*.db"))
            for old in copies[:-30]:
                old.unlink()
        except Exception:
            log.exception("Database backup failed")
        time.sleep(6 * 60 * 60)


threading.Thread(target=_backup_loop, name="backup", daemon=True).start()


# --------------------------------------------------------- admin login
TOKEN_TTL_SECONDS = 60 * 60
ADMIN_TOKENS = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()


def _client_key():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _login_locked_out(key):
    with LOGIN_LOCK:
        entry = LOGIN_ATTEMPTS.get(key)
        if not entry or not entry[1]:
            return 0
        remaining = entry[1] - time.monotonic()
        if remaining <= 0:
            LOGIN_ATTEMPTS.pop(key, None)
            return 0
        return int(remaining) + 1


def _record_login_failure(key):
    with LOGIN_LOCK:
        entry = LOGIN_ATTEMPTS.get(key)
        count = entry[0] + 1 if entry else 1
        locked_until = entry[1] if entry else 0.0
        if count >= LOGIN_MAX_ATTEMPTS:
            locked_until = time.monotonic() + LOGIN_LOCKOUT_SECONDS
        LOGIN_ATTEMPTS[key] = [count, locked_until]
        return LOGIN_MAX_ATTEMPTS - count


def require_admin():
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    expiry = ADMIN_TOKENS.get(token)
    now = time.monotonic()
    if expiry is None or now > expiry:
        ADMIN_TOKENS.pop(token, None)
        abort(401)
    ADMIN_TOKENS[token] = now + TOKEN_TTL_SECONDS


# ------------------------------------------------------------ helpers
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONTACT_EMAIL = "connect@mylokamania.com"


def _has_preview():
    return bool(PREVIEW_KEY) and secrets.compare_digest(
        request.cookies.get(PREVIEW_COOKIE, ""), PREVIEW_KEY)


def validate(payload):
    """Return (clean data, list of problems)."""
    errors = []

    def text(key, limit=2000):
        v = payload.get(key)
        return v.strip()[:limit] if isinstance(v, str) else ""

    d = {}
    d["brand"] = text("brand", 200) or errors.append("Brand name is required")
    try:
        year = int(text("launchYear") or 0)
        if not 1900 <= year <= datetime.now().year:
            raise ValueError
        d["launch_year"] = year
    except ValueError:
        errors.append(f"Brand launch year must be a year between 1900 and {datetime.now().year}")
    d["registration"] = text("registration")
    if d["registration"] not in cfg.REGISTRATION:
        errors.append("Please choose your commercial registration status")
    d["contact"] = text("contact", 200)
    if not d["contact"]:
        errors.append("Contact person full name is required")
    elif not re.search(r"\S\s+\S", d["contact"]):
        errors.append("Please enter the contact person's first and last name")
    d["phone"] = text("phone", 40)
    if len(re.sub(r"\D", "", d["phone"])) < 8:
        errors.append("A valid phone / WhatsApp number is required")
    d["email"] = text("email", 200)
    if not EMAIL_RE.match(d["email"]):
        errors.append("A valid email address is required")
    d["instagram"] = text("instagram", 200)
    if not d["instagram"]:
        errors.append("Instagram is required")
    d["website"] = text("website", 300)
    if d["website"] and not re.match(r"^[^\s@]+\.[^\s@]{2,}", d["website"]):
        errors.append("Website should look like a link, e.g. brand.com")
    d["about"] = text("about")
    if not d["about"]:
        errors.append("About the brand is required")

    cat = payload.get("category")
    if cat not in cfg.CATEGORIES:
        errors.append("Please choose a main category")
    else:
        d["category_key"], d["category"] = cat, cfg.CATEGORIES[cat]
        if cat == "other":
            d["subcategory"] = text("otherCategory", 200)
            if not d["subcategory"]:
                errors.append("Please describe your category")
        else:
            d["subcategory"] = text("subcategory", 200)
            if d["subcategory"] not in cfg.SUBCATEGORIES[cat]:
                errors.append("Please choose a subcategory")
        space = payload.get("space")
        if space not in cfg.SPACES_BY_CATEGORY[cat]:
            errors.append("Please choose a space available for your category")
        else:
            d["space_key"], d["space"] = space, cfg.SPACES[space]

    days = payload.get("days")
    if days not in cfg.DAYS:
        errors.append("Please choose your participation days")
    else:
        d["days_key"], d["days"] = days, cfg.DAYS[days]

    d["products"] = text("products")
    if not d["products"]:
        errors.append("Products you plan to sell are required")
    d["drop_offer"] = text("dropOffer")
    if not d["drop_offer"]:
        errors.append("Please describe your Black Friday drop and/or offer")
    d["price_range"] = text("priceRange")
    if d["price_range"] not in cfg.PRICE_RANGES:
        errors.append("Please choose a typical price range")
    d["joined"] = text("joined")
    if d["joined"] not in cfg.JOINED:
        errors.append("Please tell us if you've joined Lokamania before")
    if payload.get("confirmAccurate") is not True or payload.get("agreeContact") is not True:
        errors.append("Please tick both confirmation boxes")
    return d, errors


def public_record(r, dups):
    out = {k: v for k, v in r.items() if k not in ("seq", "version", "synced_version")}
    out["submitted_cairo"] = to_cairo(r.get("submitted_at"))
    out["updated_cairo"] = to_cairo(r.get("last_updated"))
    out["duplicates"] = dups.get(r["reference"], [])
    return out


# --------------------------------------------------------------- pages
@app.before_request
def _gatekeeper():
    """While on hold, refuse new applications unless the team preview is on."""
    if (MAINTENANCE_MODE and request.method == "POST"
            and request.path.rstrip("/") == "/api/applications" and not _has_preview()):
        return jsonify(ok=False, error=f"Applications are paused right now. Contact {CONTACT_EMAIL}."), 503
    return None


def _index_page():
    html = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")
    if not applications_open():
        html = html.replace('data-apply="open"', 'data-apply="closed"', 1)
    return Response(html, mimetype="text/html")


@app.get("/")
def index():
    key = request.args.get("preview", "")
    if MAINTENANCE_MODE:
        if PREVIEW_KEY and key and secrets.compare_digest(key, PREVIEW_KEY):
            resp = _index_page()
            resp.set_cookie(PREVIEW_COOKIE, PREVIEW_KEY, max_age=12 * 3600,
                            httponly=True, samesite="Lax", secure=request.is_secure)
            return resp
        if not _has_preview():
            return send_from_directory(PROJECT_ROOT, "hold.html")
    return _index_page()


@app.get("/admin")
def admin_page():
    return send_from_directory(PROJECT_ROOT, "admin.html")


@app.get("/pass")
@app.get("/pass/")
def frost_list_page():
    """Frost List pre-registration page (unchanged)."""
    return send_from_directory(PROJECT_ROOT, "pass.html")


@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(PROJECT_ROOT / "assets", filename)


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(PROJECT_ROOT / "assets" / "lm10", "favicon.png")


# ------------------------------------------------------------ public API
@app.get("/api/health")
def health():
    return jsonify(ok=True, time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   applications_open=applications_open(), maintenance=MAINTENANCE_MODE,
                   sheet_sync=sync.state["configured"])


@app.post("/api/applications")
def create_application():
    if not applications_open():
        return jsonify(ok=False, error=f"Applications closed on November 12. Contact {CONTACT_EMAIL}."), 403
    payload = request.get_json(silent=True) or {}
    if payload.get("company"):  # hidden field only bots fill in
        return jsonify(ok=True, reference="LM10-0000"), 201
    data, errors = validate(payload)
    if errors:
        return jsonify(ok=False, error=errors[0], fields=errors), 400
    try:
        reference = db.add(data)
    except Exception:
        log.exception("Saving an application failed")
        return jsonify(ok=False, error="We couldn't save your application. Please try again in a moment."), 500
    sync.nudge()
    return jsonify(ok=True, reference=reference), 201


# ------------------------------------------------------------- admin API
@app.post("/api/auth/login")
def login():
    key = _client_key()
    locked_for = _login_locked_out(key)
    if locked_for:
        return jsonify(ok=False, error=f"Too many failed sign-in attempts. Try again in {locked_for // 60 + 1} minute(s)."), 429
    payload = request.get_json(silent=True) or {}
    if not secrets.compare_digest(str(payload.get("password") or ""), ADMIN_PASSWORD):
        left = _record_login_failure(key)
        if left <= 0:
            return jsonify(ok=False, error="Too many failed sign-in attempts. This address is locked for 15 minutes."), 429
        return jsonify(ok=False, error=f"Wrong password. {left} attempt(s) left before a 15-minute lock."), 401
    with LOGIN_LOCK:
        LOGIN_ATTEMPTS.pop(key, None)
    token = secrets.token_urlsafe(32)
    ADMIN_TOKENS[token] = time.monotonic() + TOKEN_TTL_SECONDS
    return jsonify(ok=True, token=token)


@app.post("/api/auth/logout")
def logout():
    auth = request.headers.get("Authorization", "")
    ADMIN_TOKENS.pop(auth[7:] if auth.startswith("Bearer ") else "", None)
    return jsonify(ok=True)


@app.get("/api/applications")
def list_applications():
    require_admin()
    records = db.all()
    dups = find_duplicates(records)
    return jsonify(
        ok=True,
        applications=[public_record(r, dups) for r in records],
        options={"statuses": cfg.STATUSES, "categories": list(cfg.CATEGORIES.values()),
                 "days": list(cfg.DAYS.values()), "spaces": list(cfg.SPACES.values())},
        deadline=CLOSE_AT.astimezone(CAIRO).strftime("%B %d, %I:%M %p").replace(" 0", " "),
        applications_open=applications_open(),
    )


@app.patch("/api/applications/<string:reference>")
def update_application(reference):
    require_admin()
    payload = request.get_json(silent=True) or {}
    status, notes = payload.get("status"), payload.get("notes")
    if status is not None and status not in cfg.STATUSES:
        return jsonify(ok=False, error=f"Unknown status: {status}"), 400
    if notes is not None and not isinstance(notes, str):
        return jsonify(ok=False, error="Notes must be text"), 400
    try:
        db.update(reference, status=status, notes=None if notes is None else notes.strip()[:5000])
    except KeyError:
        return jsonify(ok=False, error=f"Application {reference} not found"), 404
    sync.nudge()
    return jsonify(ok=True)


@app.post("/api/applications/bulk-status")
def bulk_status():
    require_admin()
    payload = request.get_json(silent=True) or {}
    refs, status = payload.get("references") or [], payload.get("status")
    if status not in cfg.STATUSES:
        return jsonify(ok=False, error=f"Unknown status: {status}"), 400
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs):
        return jsonify(ok=False, error="Choose at least one application"), 400
    n = db.bulk_status(refs[:1000], status)
    sync.nudge()
    return jsonify(ok=True, updated=n)


@app.delete("/api/applications/<string:reference>")
def delete_application(reference):
    require_admin()
    try:
        db.delete(reference)
    except KeyError:
        return jsonify(ok=False, error=f"Application {reference} not found"), 404
    sync.nudge()
    return jsonify(ok=True)


@app.get("/api/sync")
def sync_status():
    require_admin()
    return jsonify(ok=True, sync=sync.status(), now=time.time())


@app.post("/api/sync")
def sync_now():
    require_admin()
    if not sync.state["configured"]:
        return jsonify(ok=False, error="The Google Sheet link isn't set up on the server yet."), 400
    sync.resync()
    return jsonify(ok=True)


@app.errorhandler(Exception)
def unexpected_error(exc):
    """Answer API errors as JSON the admin page can show, and log them."""
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return exc
    log.exception("Unexpected error on %s", request.path)
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="The server hit an error reading the database. "
                                       "Please try again in a minute; if it keeps happening, check the server logs."), 500
    return "Something went wrong. Please try again in a minute.", 500


@app.errorhandler(401)
def unauthorized(_error):
    return jsonify(ok=False, error="Your session has ended. Please sign in again."), 401


if __name__ == "__main__":
    debug = _flag("FLASK_DEBUG")
    host = os.environ.get("HOST", "127.0.0.1")
    print("Lokamania 10 server")
    print(f"  Site:     http://{host}:{PORT}/")
    print(f"  Admin:    http://{host}:{PORT}/admin")
    print(f"  Database: {DATABASE_PATH}")
    print(f"  Sheet:    {'sync on' if sync.state['configured'] else 'not configured'}")
    print(f"  Closes:   {CLOSE_AT.isoformat()}")
    app.run(host=host, port=PORT, debug=debug, use_reloader=False)
