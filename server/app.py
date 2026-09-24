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
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, request, send_from_directory

from excel_db import ExcelDatabase, ExcelWriteRefused

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXCEL = (
    "/Users/macbookair/Library/CloudStorage/OneDrive-Personal/"
    "Lokamania Website/Lokamania_09_Brand_Applications_FINAL.xlsx"
)
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

EXCEL_PATH = os.environ.get("EXCEL_PATH", DEFAULT_EXCEL)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "lokamania-admin")
PORT = int(os.environ.get("PORT", "5000"))

db = ExcelDatabase(EXCEL_PATH)
app = Flask(__name__, static_folder=None)

# Admin authentication uses short-lived bearer tokens kept in memory.
# There is no persistent cookie: as soon as the page is refreshed or the
# server restarts the token is gone, so the admin user must sign in again.
TOKEN_TTL_SECONDS = 60 * 60  # sliding 1-hour expiry
ADMIN_TOKENS = {}            # token -> absolute expiry (time.monotonic)

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
    parsed = urlparse(website)
    if not website or parsed.scheme not in ("http", "https") or not parsed.netloc:
        errors.append("Website must be a full URL, e.g. https://yourbrand.com")
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
    return jsonify(ok=True, time=datetime.now().isoformat(timespec="seconds"))


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
    payload = request.get_json(silent=True) or {}
    if payload.get("password") != ADMIN_PASSWORD:
        return jsonify(ok=False, error="Wrong password"), 401
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
    print("Lokamania 09 server")
    print(f"  Site:  http://127.0.0.1:{PORT}/")
    print(f"  Admin: http://127.0.0.1:{PORT}/admin")
    print(f"  Excel: {EXCEL_PATH}")
    app.run(host="127.0.0.1", port=PORT, debug=True, use_reloader=False)
