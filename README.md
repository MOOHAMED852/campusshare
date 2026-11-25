# CampusShare

CampusShare is served by the Flask application in `app.py`. SQLite data and private PDF uploads are created in the ignored `instance/` directory the first time the server starts.

## Windows setup

Install Python 3.9 or newer, then open PowerShell in this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:CAMPUSSHARE_ADMIN_TOKEN = "replace-with-a-long-random-admin-token"
$env:CAMPUSSHARE_SESSION_SECRET = "replace-with-a-different-long-random-secret"
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8000`. Keep the server running while using the site. Open `/admin.html` and enter the admin token to manage filières and academic years, review uploads, attach exam corrections, and remove documents. Do not share the token. These environment variables apply only to the current PowerShell session.

Run the API tests with `.\.venv\Scripts\python.exe -m unittest -v test_app.py`.

The local Flask server is for development. Use a production WSGI server and HTTPS before deploying publicly. Back up `instance/campusshare.sqlite3` and `instance/uploads/` together.

## API overview

- `GET /api/levels`, `/api/majors`, `/api/academic-years`, `/api/filters`
- `GET /api/resources` (approved documents only; supports academic filters, `limit`, `offset`, and `search`)
- `POST /api/resources` (PDF upload; submissions are pending until an administrator approves them)
- `GET /api/resources/<id>`, `/preview`, `/download`
- `GET /api/admin/resources` (requires `X-Admin-Token` or an authenticated admin session)
- `POST`, `DELETE /api/admin/session`; `POST /api/admin/resources/<id>/review`, `/correction`; `DELETE /api/admin/resources/<id>`
- `POST /api/admin/majors`, `/api/admin/academic-years`

View and download counts are stored in SQLite. Public endpoints return approved files only; unreviewed PDFs are kept outside the public web directory.
