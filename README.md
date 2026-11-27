# MaBiblio

MaBiblio is served by the Flask application in `app.py`. SQLite data and private PDF uploads are created in the ignored `instance/` directory the first time the server starts.

## Windows setup

Install Python 3.9 or newer, then open PowerShell in this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:MABIBLIO_ADMIN_EMAIL = "your-existing-verified-student-email@example.com"
$env:MABIBLIO_CONTACT_EMAIL = "mabibliocontactteam@gmail.com"
$env:MABIBLIO_SESSION_SECRET = "replace-with-a-different-long-random-secret"
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8000`. Keep the server running while using the site. Sign in through the normal student login using the verified account whose email matches `MABIBLIO_ADMIN_EMAIL`, then open `/admin.html` to manage documents and student accounts. No separate administrator password is used. These environment variables apply only to the current PowerShell session.

The admin dashboard also lists student accounts, verified-email status, recent sign-ins, PDF download events, approximate active time, and an online indicator based on activity in the last two minutes. Active time is estimated from visible-site heartbeats, not exact attention tracking. Activity events are automatically deleted after 180 days. Passwords and IP addresses are not included in the activity dashboard.

To enable student accounts, set SMTP delivery settings before starting the server. Email verification links are required before students can sign in or contribute:

```powershell
$env:MABIBLIO_SMTP_HOST = "smtp.example.com"
$env:MABIBLIO_SMTP_PORT = "587"
$env:MABIBLIO_SMTP_STARTTLS = "1"
$env:MABIBLIO_SMTP_USERNAME = "smtp-user"
$env:MABIBLIO_SMTP_PASSWORD = "smtp-password"
$env:MABIBLIO_FROM_EMAIL = "noreply@example.com"
$env:MABIBLIO_ADMIN_EMAIL = "your-existing-verified-student-email@example.com"
$env:MABIBLIO_CONTACT_EMAIL = "mabibliocontactteam@gmail.com"
$env:MABIBLIO_PUBLIC_URL = "https://mabiblio.pythonanywhere.com"
```

SMTP port defaults to `587`, and STARTTLS is enabled unless `MABIBLIO_SMTP_STARTTLS` is set to `0`. For Gmail, use `smtp.gmail.com`, port `587`, your full Gmail address as the SMTP username, and a Google app password when required; do not use your regular Google account password. `MABIBLIO_FROM_EMAIL` must be that account or an authorized sender alias. Set environment variables in PythonAnywhere's WSGI configuration before importing the Flask app, then reload the web app.

Keep SMTP credentials private. A verified student account is required to download any PDF. A contribution counts only after administrator approval. Three unique, approved student PDFs unlock downloads of student-contributed PDFs for 72 hours; each further batch of three approved PDFs queues another 72-hour period. Administrator-published documents are approved immediately and do not require contributions, but still require sign-in to download.

## One-time student account cleanup

Stop the app before running the cleanup script. It always creates and verifies a SQLite backup before checking account relationships. The default database is `instance/mabiblio.sqlite3`; pass a different database path as the first argument when needed. Run without `--confirm` first to perform the backup and preflight without deleting student rows:

```powershell
.\.venv\Scripts\python.exe cleanup_student_accounts.py
```

Deletion is allowed only when IDs 1–3 and their configured emails match the reviewed target, ID 2 is verified, and exactly 600 resources have `owner_id` set to NULL. The script refuses if a resource depends on an account's access grant and verifies resource metadata is unchanged. It never accesses or modifies uploaded files. Account activity and access grants are cascaded only when their counts are reviewed and `--delete-linked-account-data` is explicitly supplied:

```powershell
.\.venv\Scripts\python.exe cleanup_student_accounts.py --confirm
```

If preflight reports linked account data, review those counts before deciding whether to add `--delete-linked-account-data`. Each invocation creates a separate backup. The script does not change server environment settings; configure `MABIBLIO_ADMIN_EMAIL=mabibliocontactteam@gmail.com` in the deployed app environment separately.

Run all tests with `.\.venv\Scripts\python.exe -m unittest discover -v`.

The local Flask server is for development. Use a production WSGI server and HTTPS before deploying publicly. Back up `instance/mabiblio.sqlite3` and `instance/uploads/` together.

## API overview

- `GET /api/levels`, `/api/majors`, `/api/academic-years`, `/api/filters`
- `GET /api/resources` (approved documents only; supports academic filters, `limit`, `offset`, and `search`)
- `POST /api/resources` (PDF upload; submissions are pending until an administrator approves them)
- `GET /api/resources/<id>`, `/preview`, `/download`
- `POST /api/student/register`, `GET /api/student/verify`, `GET /api/student/account`, `POST`/`DELETE /api/student/session`
- `POST /api/student/activity` (authenticated visible-page activity heartbeat)
- `GET /api/admin/resources` (requires the verified student session matching `MABIBLIO_ADMIN_EMAIL`)
- `GET /api/admin/students`, `/api/admin/students/<id>/activity` (requires admin authentication)
- `GET`, `DELETE /api/admin/session`; `POST /api/admin/resources` (publish an official PDF immediately); `POST /api/admin/resources/<id>/review`, `/correction`; `DELETE /api/admin/resources/<id>`
- `POST /api/admin/majors`, `/api/admin/academic-years`

`MABIBLIO_ADMIN_EMAIL` is an authorization identity and must match the email of an existing verified student account. `MABIBLIO_CONTACT_EMAIL` is displayed publicly and does not grant administrator access. The legacy `MABIBLIO_ADMIN_TOKEN` variable no longer authorizes admin actions.

View and download counts are stored in SQLite. Public endpoints return approved files only; unreviewed PDFs are kept outside the public web directory.
