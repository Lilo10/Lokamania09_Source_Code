# Lokamania 10 — website, admin and Google Sheet

Black Friday edition · November 26–28 · Majarrah, Sheikh Zayed · applications close November 12, 11:59 pm Cairo time.

## How it works

```
Applicant ── index.html ──POST /api/applications──▶ Flask server (Railway)
                                                     │ saves to SQLite (the master copy)
Admin ────── /admin ──────login, list, edit, bulk──▶ │
                                                     ▼ background sync (seconds; full refresh every 15 min)
                                     Google Apps Script web app ──▶ Lokamania 10 Google Sheet
                                                                    Dashboard · Applications · one tab per category
```

* The **database** (`DATABASE_PATH`, on Railway `/data/lokamania10.db`) is the master copy. A copy is
  written to `backups/` next to it once a day; 30 days are kept.
* The **Google Sheet** is a read-only mirror. Its tabs are protected; edit applications in `/admin`.
  If Google is slow or down, nothing is lost: changes queue up and are retried automatically.
* Categories, spaces, days, statuses and the deadline live in `server/lm10_config.py`.
  The form in `index.html` offers the same choices.

## Railway variables

| Variable | Value |
|---|---|
| `ADMIN_PASSWORD` | the shared admin password (unchanged from Lokamania 09) |
| `DATABASE_PATH` | `/data/lokamania10.db` |
| `SHEET_WEBAPP_URL` | the Apps Script web app link (ends in `/exec`) |
| `SHEET_SECRET` | the secret code, identical to `SECRET` in the Apps Script |
| `MAINTENANCE_MODE` | `1` shows the "website on hold" page; remove it to go live |
| `PREVIEW_KEY` | optional: open `https://mylokamania.com/?preview=<key>` to see the real site while on hold |
| `APPLICATIONS_CLOSE_AT` | optional override, e.g. `2026-11-12T23:59:59` (Cairo time) |

## Google Sheet script

`google-sheet/Code.gs` goes into the Sheet under **Extensions → Apps Script**. Set `SECRET`, then
**Deploy → New deployment → Web app**, Execute as **Me**, Who has access **Anyone**. After changing the
script: **Deploy → Manage deployments → Edit → New version** (the link stays the same).

## Run it on your Mac

```bash
./server/run.sh
```

Then open http://127.0.0.1:5000 and http://127.0.0.1:5000/admin. Locally the database is
`local-data/lokamania10.db` unless `DATABASE_PATH` is set in `.env`.

## Files

* `index.html` — public site and application form (shows "Applications are closed" after the deadline)
* `admin.html` — admin page: status counts, breakdowns, search, filters, bulk status change, notes, delete
* `hold.html` — "website on hold" page used while `MAINTENANCE_MODE=1`
* `pass.html` — Frost List page (unchanged)
* `server/app.py` — web server and API · `server/db.py` — database · `server/sheet_sync.py` — Sheet mirror
* `server/lm10_config.py` — form choices and deadline · `assets/lm10/` — Lokamania 10 artwork
* `google-sheet/Code.gs` — the Apps Script for the Sheet

Lokamania 09's data was exported to `Lokamania09_FINAL_EXPORT_2026-10-21.xlsx`; the 09 workbook also
remains untouched on the Railway volume. `server/excel_db.py`, `make_plan.py` and `deploy/vps/` are
Lokamania 09 leftovers and are no longer used.
