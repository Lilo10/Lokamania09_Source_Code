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
| Admin | http://127.0.0.1:5000/admin | Password from `.env` |

## Admin password (`.env`)

The admin password lives in the **`.env`** file in the project root (already created for you).
The server loads it automatically on startup, and it is **ignored by git** — never commit it.

Change it by editing `.env`, or as an environment variable (env vars always win over `.env`):

```bash
ADMIN_PASSWORD="your-strong-password" ./server/run.sh
```

Supported values in `.env`: `ADMIN_PASSWORD`, `EXCEL_PATH` (path to the workbook), `PORT`.

## Admin security

- The admin page authenticates with a **short-lived token kept in memory only** — a page refresh
  or a server restart signs you out automatically, so you must enter the password again. This is
  intentional: it helps if the admin page is left open on a shared machine.

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

This version needs a real server — GitHub Pages cannot host it (it only serves static files).
Everything needed to launch on a VPS is in **`deploy/`**:

| File | Runs on | What it does |
|---|---|---|
| `deploy/upload.sh` | your Mac | rsyncs the code + workbook, then runs setup |
| `deploy/setup.sh` | the server | installs Caddy, gunicorn, the systemd service, firewall, daily backups |
| `deploy/Caddyfile` | the server | reverse proxy + automatic HTTPS |
| `deploy/lokamania.service` | the server | starts the app on boot and restarts it if it crashes |
| `deploy/backup.sh` | the server | nightly snapshot of the workbook (30-day history) |
| `deploy/fetch-workbook.sh` | your Mac | downloads the live workbook to look at in Excel |

### Going live

```bash
# 1. From the project folder, once the server has an IP address:
./deploy/upload.sh root@YOUR_SERVER_IP

# 2. Point your domain at the server — one DNS "A" record:
#    mylokamania.com      A   YOUR_SERVER_IP

# 3. Check it is healthy:
ssh root@YOUR_SERVER_IP 'systemctl status lokamania --no-pager'
ssh root@YOUR_SERVER_IP 'curl -s http://127.0.0.1:8000/api/health'
```

Later, to push code changes without touching the data:

```bash
./deploy/upload.sh --code-only
```

### How it is laid out on the server

```
/opt/lokamania/          code (rsync'd from this repo)
/srv/lokamania-data/     the workbook + backups  ← the only writable folder
etc/caddy/Caddyfile      HTTPS + reverse proxy
etc/systemd/system/lokamania.service
```

The workbook is deliberately **outside** the web root, so it can never be downloaded over HTTP.
gunicorn runs as an unprivileged user (`lokamania`) on `127.0.0.1:8000` — that port is not reachable
from the internet; Caddy is the only thing that can talk to it.

### Important once it is live

- **The server holds the master workbook.** Do not edit the OneDrive copy and expect it to appear.
  Use `./deploy/fetch-workbook.sh` to pull a read-only copy, and close it in Excel when done.
- The admin password is copied to the server's `/opt/lokamania/.env`. Change it there if you change
  it here, or re-run `./deploy/upload.sh --no-setup` after editing.
- Backups run at 03:17 and are kept 30 days in `/srv/lokamania-data/backups/`.

## Original Google Form

The previous version embedded a Google Form. It is now replaced by this self-hosted form + Excel
database. The Google Form's old response spreadsheet can still be exported and imported into the
same workbook if you want to merge historical data.