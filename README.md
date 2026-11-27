# MaBiblio

MaBiblio is served by the Flask application in `app.py`. SQLite data and private PDF uploads are created in the ignored `instance/` directory the first time the server starts.

## Windows setup

Install Python 3.9 or newer, then open PowerShell in this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:MABIBLIO_ADMIN_TOKEN = "replace-with-a-long-random-admin-token"
$env:MABIBLIO_SESSION_SECRET = "replace-with-a-different-long-random-secret"
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8000`. Keep the server running while using the site. Open `/admin.html` and enter the admin token to manage filières and academic years, review uploads, attach exam corrections, and remove documents. Do not share the token. These environment variables apply only to the current PowerShell session.

The admin dashboard also lists student accounts, verified-email status, recent sign-ins, PDF download events, approximate active time, and an online indicator based on activity in the last two minutes. Active time is estimated from visible-site heartbeats, not exact attention tracking. Activity events are automatically deleted after 180 days. Passwords and IP addresses are not included in the activity dashboard.

To enable student accounts, set SMTP delivery settings before starting the server. Email verification links are required before students can sign in or contribute:

```powershell
$env:MABIBLIO_SMTP_HOST = "smtp.example.com"
$env:MABIBLIO_SMTP_PORT = "587"
$env:MABIBLIO_SMTP_USERNAME = "smtp-user"
$env:MABIBLIO_SMTP_PASSWORD = "smtp-password"
$env:MABIBLIO_FROM_EMAIL = "noreply@example.com"
$env:MABIBLIO_PUBLIC_URL = "https://mabiblio.pythonanywhere.com"
```

Keep SMTP credentials private. A verified student account is required to download any PDF. A contribution counts only after administrator approval. Three unique, approved student PDFs unlock downloads of student-contributed PDFs for 72 hours; each further batch of three approved PDFs queues another 72-hour period. Administrator-published documents are approved immediately and do not require contributions, but still require sign-in to download.

Run the API tests with `.\.venv\Scripts\python.exe -m unittest -v test_app.py`.

The local Flask server is for development. Use a production WSGI server and HTTPS before deploying publicly. Back up `instance/campusshare.sqlite3` and `instance/uploads/` together.

## API overview

- `GET /api/levels`, `/api/majors`, `/api/academic-years`, `/api/filters`
- `GET /api/resources` (approved documents only; supports academic filters, `limit`, `offset`, and `search`)
- `POST /api/resources` (PDF upload; submissions are pending until an administrator approves them)
- `GET /api/resources/<id>`, `/preview`, `/download`
- `POST /api/student/register`, `GET /api/student/verify`, `GET /api/student/account`, `POST`/`DELETE /api/student/session`
- `POST /api/student/activity` (authenticated visible-page activity heartbeat)
- `GET /api/admin/resources` (requires `X-Admin-Token` or an authenticated admin session)
- `GET /api/admin/students`, `/api/admin/students/<id>/activity` (requires admin authentication)
- `POST`, `DELETE /api/admin/session`; `POST /api/admin/resources` (publish an official PDF immediately); `POST /api/admin/resources/<id>/review`, `/correction`; `DELETE /api/admin/resources/<id>`
- `POST /api/admin/majors`, `/api/admin/academic-years`

View and download counts are stored in SQLite. Public endpoints return approved files only; unreviewed PDFs are kept outside the public web directory.
