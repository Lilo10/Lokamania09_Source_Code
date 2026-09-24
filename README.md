# Lokamania 09 — Website with Excel-backed database

Website + admin for the Lokamania 09 Winter Edition brand applications (6–7 November 2026, U Venues).

## How it works

```
Browser                                                     Server (Flask)
├─ index.html   ──POST /api/applications──▶  validate → generate LM09-XXXX → save
├─ /admin       ──GET  /api/applications──▶  read applications list
│               ──PATCH/api/applications/<ref>──▶ update status / payment / notes
│               ──GET  /api/stats──────────▶  live dashboard counts
└─ (same origin, no CORS needed)              │
                                              ▼
                              Lokamania_09_Brand_Applications_FINAL.xlsx
                                   (the database — OneDrive)
```

- The **Applications sheet** in the workbook is the database. Every submission becomes one row
  (reference `LM09-0001`, timestamps, statuses), with automatic defaults from the **Settings**
  sheet (Application Status → `New`, Payment Status → the first option).
- The **Dashboard sheet** formulas count the new rows automatically (rows 7–1006 are pre-configured
  and counted).
- Editing the **Settings** sheet (categories, spaces, statuses…) updates what the server validates —
  Excel stays the single source of truth.
- **Backups**: a timestamped backup of the workbook is created automatically before the first write
  each time the server starts (in `backups/` inside the Lokamania Website folder).

## Run it

Requires Python 3.9+ (already on this Mac). No Node.js needed.

```bash
./server/run.sh        # first run creates server/.venv and installs dependencies
```

Then open:

| Page | URL | Access |
|---|---|---|
| Public site | http://127.0.0.1:5000 | Everyone |
| Admin | http://127.0.0.1:5000/admin | Password-protected |

The default admin password is `lokamania-admin`. Change it before anything public:

```bash
ADMIN_PASSWORD="pick-a-strong-password" ./server/run.sh
```

Other options: `EXCEL_PATH` (path to the workbook), `PORT` (default 5000), `SECRET_KEY`.

## Files

- `index.html` — public site with the live application form (posts to the server)
- `admin.html` — password-protected admin: review applications, update status/payment, notes
- `server/app.py` — Flask app (site + admin + API)
- `server/excel_db.py` — workbook read/write, references, locks, atomic saves, backups
- `server/requirements.txt`, `server/run.sh`
- `assets/` — logo and event artwork

## ⚠️ Excel / OneDrive notes (important)

- **Close the workbook in Excel/OneDrive while the server is running.** If Excel has the file open,
  it can overwrite what the server wrote (and vice-versa). The server refuses to write while Excel's
  lock file (`~$…xlsx`) is present and returns a friendly error instead of clobbering your data —
  so if you see that error, close Excel and retry.
- The server reloads the workbook from disk for every read/write, so edits made in Excel (while the
  server is stopped) are picked up automatically the next time it runs.
- OneDrive syncs the file in the background; give it a moment after big edit sessions.

## Testing

```bash
./server/run.sh
# then, in another terminal:
curl -s http://127.0.0.1:5000/api/health
```

Submit a test application through the site, then sign in to `/admin` and update its status —
the change lands in the Applications sheet. You can also delete test rows directly in Excel
(remove the row, the table and Dashboard adjust).

## Hosting

This version runs **locally** and needs a server — GitHub Pages can no longer host it (it is static
only). To go online later, deploy `server/` to any small Python host (Render, Railway, Fly.io, or a
VPS) and point `EXCEL_PATH` at the workbook on persistent storage.

## Original Google Form

The previous version embedded a Google Form. It is now replaced by this self-hosted form + Excel
database. The Google Form's old response spreadsheet can still be exported and imported into the
same workbook if you want to merge historical data.