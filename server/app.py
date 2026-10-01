"""Lokamania 09 — Flask server.

Serves the public site, the admin page, and a small JSON API that reads and
writes the Lokamania Excel workbook (the database).

Environment variables:
  EXCEL_PATH      path to the workbook (default: the OneDrive workbook)
  ADMIN_PASSWORD  password for /admin (default: lokamania-admin)
  SECRET_KEY      Flask session key (default: dev value — change for anything public)
  PORT            port to listen on (default: 5000)
"""

from __future__ import annotations

import os
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from excel_db import ExcelDatabase, ExcelWriteRefused

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
    """Read a mandatory setting or stop the server with a clear message.

    There are deliberately no default values here. A silently wrong default is
    much worse than not starting: a guessed admin password would be guessable by
    anyone, and a guessed workbook path would look like an empty database.
    """
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


EXCEL_PATH = _required_env(
    "EXCEL_PATH",
    hint="It must point at Lokamania_09_Brand_Applications_FINAL.xlsx "
         "(on Railway this is normally /data/Lokamania_09_Brand_Applications_FINAL.xlsx).",
)
ADMIN_PASSWORD = _required_env(
    "ADMIN_PASSWORD",
    hint="Use a long random password, not a memorable one.",
)
# Refuse an obviously weak password rather than quietly protecting the admin
# page with it.
if len(ADMIN_PASSWORD) < 12:
    raise SystemExit(
        "\nERROR: ADMIN_PASSWORD is too short (minimum 12 characters).\n"
        "       Please choose a longer one.\n"
    )

PORT = int(os.environ.get("PORT", "5000"))

excel_file = Path(EXCEL_PATH)
# Deliberately a warning, not a fatal error. On a brand new deployment the
# volume at /data is empty until the real workbook is uploaded, and that upload
# needs `railway ssh` into this very container. Refusing to boot would make the
# service unreachable and the workbook impossible to put there: a catch-22 with
# no exit. So the server starts, stays reachable, and every endpoint that needs
# the workbook answers with a clear 503 instead.
WORKBOOK_MISSING = not excel_file.exists()

db = ExcelDatabase(EXCEL_PATH)
app = Flask(__name__, static_folder=None)


def require_workbook():
    """Stop a data request cleanly when the workbook has not been uploaded yet."""
    if WORKBOOK_MISSING:
        return jsonify(
            ok=False,
            error=(f"The database is not set up yet: no workbook was found at "
                   f"{EXCEL_PATH}. Upload {excel_file.name} to that location, "
                   f"then reload this page."),
        ), 503
    return None


@app.before_request
def _block_when_no_workbook():
    """Serve the pages, but refuse data requests until the workbook is there.

    The site and admin page still load on purpose: they are how you find out
    what is wrong, and how you confirm the fix once the file is uploaded.
    """
    if not WORKBOOK_MISSING:
        return None
    if request.path.startswith(("/api/applications", "/api/stats")):
        return require_workbook()
    return None

# Admin authentication uses short-lived bearer tokens kept in memory.
# There is no persistent cookie: as soon as the page is refreshed or the
# server restarts the token is gone, so the admin user must sign in again.
TOKEN_TTL_SECONDS = 60 * 60  # sliding 1-hour expiry
ADMIN_TOKENS = {}            # token -> absolute expiry (time.monotonic)

# Brute-force protection for the login endpoint. Without this, /admin is a free
# password oracle: unlimited guesses against a single shared secret.
LOGIN_MAX_ATTEMPTS = 5            # wrong tries before the door is shut
LOGIN_LOCKOUT_SECONDS = 15 * 60   # how long the lockout lasts
LOGIN_ATTEMPTS = {}               # client key -> [count, locked_until]
LOGIN_LOCK = threading.Lock()


def _client_key():
    """Identify the caller. Falls back to a shared bucket if no IP is known."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _login_locked_out(key):
    """Seconds left on a lockout, or 0 if this caller is allowed to try."""
    with LOGIN_LOCK:
        entry = LOGIN_ATTEMPTS.get(key)
        if not entry:
            return 0
        _count, locked_until = entry
        if not locked_until:
            return 0  # has failed tries, but is not currently locked
        remaining = locked_until - time.monotonic()
        if remaining <= 0:
            LOGIN_ATTEMPTS.pop(key, None)  # lockout has now expired
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
        if count >= LOGIN_MAX_ATTEMPTS:
            return int(LOGIN_LOCKOUT_SECONDS) + 1
        return LOGIN_MAX_ATTEMPTS - count


def _clear_login_failures(key):
    with LOGIN_LOCK:
        LOGIN_ATTEMPTS.pop(key, None)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Form values (used by index.html) -> labels stored in the Excel workbook.
# Labels match the Settings sheet exactly.
CATEGORY_LABELS = {
    "fashion": "Fashion—Clothing",
    "beauty": "Beauty",
    "accessories": "Fashion Accessories",
    "home": "Home & Lifestyle",
    "food": "Food & Beverages",
    "art": "Art & Stationery",
    "other": "Other",
}
SPACES_BY_CATEGORY = {
    "fashion": ["Small Booth", "Large Booth"],
    "beauty": ["Kiosk"],
    "accessories": ["Kiosk", "Small Booth"],
    "home": ["Kiosk"],
    "food": ["Kiosk"],
    "art": ["Kiosk"],
    "other": ["Reviewed individually"],
}
DAYS_LABELS = {
    "both": "Both days",
    "6": "6 November 2026 only",
    "7": "7 November 2026 only",
}


# --------------------------------------------------------------------- utils
def validate_application(payload, settings):
    """Return a list of human-readable problems (empty means valid)."""
    errors = []

    def text(key):
        value = payload.get(key)
        return value.strip() if isinstance(value, str) else ""

    if not text("brand"):
        errors.append("Brand name is required")
    try:
        year = int(text("launchYear") or 0)
        if not 1900 <= year <= 2026:
            errors.append("Brand launch year must be between 1900 and 2026")
    except ValueError:
        errors.append("Brand launch year must be a number")

    if text("registration") not in settings["registration"]:
        errors.append("Commercial registration status is invalid")

    contact = text("contact")
    if not contact:
        errors.append("Contact person — full name is required")
    elif len(contact) < 3 or not re.search(r"\s", contact):
        errors.append("Please enter both first and last name")

    if not text("phone"):
        errors.append("Phone / WhatsApp is required")
    if not EMAIL_RE.match(text("email")):
        errors.append("A valid email address is required")
    if not text("instagram"):
        errors.append("Instagram is required")

    website = text("website")
    # Website is optional: plenty of brands do not have one, so a blank value is
    # accepted. When something *is* typed, only check that it plausibly is a
    # link. Deliberately not strict about the scheme, because applicants paste
    # "brand.com" and "instagram.com/brand" into this box far more often than a
    # bare https:// URL, and a rejected submission is worse than an untidy cell
    # in Excel that the admin can tidy later.
    if website and not re.match(r"^[^\s@]+\.[^\s@]{2,}", website):
        errors.append("Website should look like a link, e.g. brand.com")
    if not text("aboutBrand"):
        errors.append("About the brand is required")

    category_key = payload.get("category")
    category_label = CATEGORY_LABELS.get(category_key)
    if not category_label:
        errors.append("Please choose a valid main category")
    else:
        sub = text("subcategory") or text("otherCategory")
        if not sub:
            errors.append("Subcategory is required")
        booth = text("booth")
        allowed = SPACES_BY_CATEGORY.get(category_key, [])
        if not booth:
            errors.append("Available space is required")
        elif allowed and booth not in allowed:
            errors.append(f"Space must be one of: {', '.join(allowed)}")

    if payload.get("days") not in DAYS_LABELS:
        errors.append("Please choose your participation days")
    if not text("products"):
        errors.append("Products you plan to sell are required")
    if not text("prices"):
        errors.append("Typical price range is required")
    if not text("winter"):
        errors.append("Winter collection description is required")
    if text("joined") not in settings["joined"]:
        errors.append("Previous participation answer is invalid")

    return errors


def serialize_records(records):
    """JSON-safe copy of a record (datetimes are already ISO strings)."""
    return [
        {k: v for k, v in record.items() if k != "row"}
        for record in records
    ]


# --------------------------------------------------------------------- site
@app.get("/")
def index():
    return send_from_directory(PROJECT_ROOT, "index.html")


@app.get("/admin")
def admin_page():
    return send_from_directory(PROJECT_ROOT, "admin.html")


@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(PROJECT_ROOT / "assets", filename)


# ----------------------------------------------------------------- endpoints
@app.get("/api/health")
def health():
    # Always 200 while the process is alive, even with no workbook. Railway uses
    # this to decide whether the container is healthy, and the container has to
    # stay healthy so that `railway ssh` can still reach it to upload the file.
    return jsonify(
        ok=True,
        time=datetime.now().isoformat(timespec="seconds"),
        workbook="ready" if not WORKBOOK_MISSING else "not uploaded yet",
    )


@app.post("/api/applications")
def create_application():
    payload = request.get_json(silent=True) or {}
    settings = db.settings()
    errors = validate_application(payload, settings)
    if errors:
        return jsonify(ok=False, error="; ".join(errors), fields=errors), 400

    row_data = {
        "brand": payload.get("brand", "").strip(),
        "launch_year": int(payload.get("launchYear")),
        "registration": payload.get("registration"),
        "contact": payload.get("contact", "").strip(),
        "phone": payload.get("phone", "").strip(),
        "email": payload.get("email", "").strip(),
        "instagram": payload.get("instagram", "").strip(),
        "website": payload.get("website", "").strip(),
        "about_brand": payload.get("aboutBrand", "").strip(),
        "category": CATEGORY_LABELS[payload.get("category")],
        "subcategory": (payload.get("subcategory") or "").strip()
        or (payload.get("otherCategory") or "").strip(),
        "days": DAYS_LABELS[payload.get("days")],
        "booth": payload.get("booth", "").strip(),
        "products": payload.get("products", "").strip(),
        "prices": payload.get("prices", "").strip(),
        "winter": payload.get("winter", "").strip(),
        "exclusive": payload.get("exclusive", "").strip(),
        "joined": payload.get("joined", "").strip(),
        "status": settings["default_status"],
        "payment": settings["default_payment"],
    }
    try:
        reference = db.append_application(row_data)
    except ExcelWriteRefused as exc:
        return jsonify(ok=False, error=str(exc)), 503
    except Exception:
        app.logger.exception("create_application failed")
        return jsonify(ok=False, error="Internal error saving application"), 500
    return jsonify(
        ok=True,
        reference=reference,
        submitted_at=datetime.now().isoformat(timespec="seconds"),
    ), 201


def require_admin():
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    expiry = ADMIN_TOKENS.get(token)
    now = time.monotonic()
    if expiry is None:
        abort(401)
    if now > expiry:
        ADMIN_TOKENS.pop(token, None)
        abort(401)
    ADMIN_TOKENS[token] = now + TOKEN_TTL_SECONDS  # sliding expiry


@app.post("/api/auth/login")
def login():
    key = _client_key()

    # Already locked out? Reject without even looking at the password.
    locked_for = _login_locked_out(key)
    if locked_for:
        return jsonify(
            ok=False,
            error=(f"Too many failed sign-in attempts. Try again in "
                   f"{locked_for // 60} minute(s)."),
        ), 429

    payload = request.get_json(silent=True) or {}
    if not secrets.compare_digest(
        str(payload.get("password") or ""), ADMIN_PASSWORD
    ):
        tries_left = _record_login_failure(key)
        if tries_left > LOGIN_MAX_ATTEMPTS:
            minutes = (tries_left - 1) // 60 + 1
            return jsonify(
                ok=False,
                error=(f"Too many failed sign-in attempts. This address is "
                       f"locked for {minutes} minute(s)."),
            ), 429
        return jsonify(
            ok=False,
            error=(f"Wrong password. {tries_left} attempt(s) left before "
                   f"this address is locked out."),
        ), 401

    _clear_login_failures(key)
    token = secrets.token_urlsafe(32)
    ADMIN_TOKENS[token] = time.monotonic() + TOKEN_TTL_SECONDS
    return jsonify(ok=True, token=token)


@app.post("/api/auth/logout")
def logout():
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    ADMIN_TOKENS.pop(token, None)
    return jsonify(ok=True)


@app.get("/api/applications")
def list_applications():
    require_admin()
    settings = db.settings()
    status = request.args.get("status", "").strip()
    payment = request.args.get("payment", "").strip()
    query = request.args.get("q", "").strip().lower()

    records = db.list_applications()
    if status and status != "all":
        records = [r for r in records if r.get("status") == status]
    if payment and payment != "all":
        records = [r for r in records if r.get("payment") == payment]
    if query:
        def haystack(r):
            return " ".join(
                str(r.get(k) or "")
                for k in ("reference", "brand", "contact", "email", "instagram")
            ).lower()
        records = [r for r in records if query in haystack(r)]

    return jsonify(
        ok=True,
        applications=serialize_records(records),
        status_options=settings["statuses"],
        payment_options=settings["payments"],
    )


@app.patch("/api/applications/<string:reference>")
def update_application(reference):
    require_admin()
    payload = request.get_json(silent=True) or {}
    settings = db.settings()

    status = payload.get("status")
    payment = payload.get("payment")
    notes = payload.get("notes")
    if status is not None and status not in settings["statuses"]:
        return jsonify(ok=False, error=f"Unknown status: {status}"), 400
    if payment is not None and payment not in settings["payments"]:
        return jsonify(ok=False, error=f"Unknown payment status: {payment}"), 400
    if notes is not None and not isinstance(notes, str):
        return jsonify(ok=False, error="Notes must be text"), 400

    try:
        db.update_application(
            reference,
            status=status,
            payment=payment,
            notes=None if notes is None else notes.strip(),
        )
    except KeyError:
        return jsonify(ok=False, error=f"Application {reference} not found"), 404
    except ExcelWriteRefused as exc:
        return jsonify(ok=False, error=str(exc)), 503
    except Exception:
        app.logger.exception("update_application failed")
        return jsonify(ok=False, error="Internal error updating application"), 500
    return jsonify(ok=True, reference=reference)


@app.get("/api/stats")
def stats():
    require_admin()
    return jsonify(ok=True, stats=db.stats())


@app.errorhandler(401)
def unauthorized(_error):
    return jsonify(ok=False, error="Not authenticated"), 401


if __name__ == "__main__":
    # Debug mode is opt-in and off by default. The Werkzeug debugger it enables
    # allows anyone who can reach the error page to run code on the server, so
    # it must never be switched on for a public deployment. Real hosting runs
    # this file under gunicorn instead (see Procfile), which never calls
    # app.run() and so is unaffected either way.
    #
    #   ./server/run.sh                    # normal local use, no debugger
    #   FLASK_DEBUG=1 ./server/run.sh      # only when actively debugging locally
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes")
    host = os.environ.get("HOST", "127.0.0.1")

    print("Lokamania 09 server")
    print(f"  Site:  http://{host}:{PORT}/")
    print(f"  Admin: http://{host}:{PORT}/admin")
    print(f"  Excel: {EXCEL_PATH}")
    print(f"  Debug: {'ON (local only)' if debug else 'off'}")
    if debug and host not in ("127.0.0.1", "localhost", "::1"):
        print("  WARNING: debug is on but the server is not local-only.")

    app.run(host=host, port=PORT, debug=debug, use_reloader=False)
