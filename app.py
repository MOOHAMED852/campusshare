import hashlib
import io
import os
import re
import secrets
import smtplib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory, session
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError, PdfStreamError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from student_activity import (
    create_student_activity_blueprint,
    initialize_student_activity_schema,
    record_student_activity,
)


ROOT = Path(__file__).resolve().parent
INSTANCE_DIR = ROOT / "instance"
UPLOAD_DIR = INSTANCE_DIR / "uploads"
DATABASE_PATH = INSTANCE_DIR / "campusshare.sqlite3"
LEVELS = ("Tronc Commun", "Licence", "Master", "Cycle Ingénieur")
CATEGORIES = ("Exams", "Courses", "TD & TP")
SEMESTERS = tuple(f"S{number}" for number in range(1, 11))
EXAM_TYPES = ("Normal Session", "Rattrapage")
DOCUMENT_TYPES = {
    "Exams": ("Exam",),
    "Courses": ("Course",),
    "TD & TP": ("TD", "TP", "Correction"),
}
ACADEMIC_YEARS = ("2025–2026", "2024–2025", "2023–2024", "2022–2023")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * MAX_UPLOAD_BYTES + 1024 * 1024
REQUIRED_STUDENT_CONTRIBUTIONS = 3
STUDENT_ACCESS_DURATION = timedelta(days=3)
EMAIL_VERIFICATION_DURATION = timedelta(hours=24)
ALLOWED_PAGES = {
    "index.html",
    "resource.html",
    "library.html",
    "admin.html",
    "style.css",
    "script.js",
    "resource-details.js",
    "library.js",
    "admin.js",
    "activity.js",
}

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("MABIBLIO_SESSION_SECRET") or os.environ.get("CAMPUSSHARE_SESSION_SECRET") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("MABIBLIO_HTTPS") == "1" or os.environ.get("CAMPUSSHARE_HTTPS") == "1"
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)


def normalized_pdf_filename(filename):
    return secure_filename(filename).casefold()


def inspect_pdf(data):
    digest = hashlib.sha256(data).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except (PdfReadError, PdfStreamError, ValueError, OSError) as error:
        raise ValueError("Le fichier téléversé n’est pas un PDF lisible.") from error
    if reader.is_encrypted:
        raise ValueError("Les PDF protégés par mot de passe ne sont pas acceptés.")
    try:
        page_count = len(reader.pages)
    except (FileNotDecryptedError, PdfReadError, PdfStreamError, ValueError, OSError) as error:
        raise ValueError("Le fichier téléversé n’est pas un PDF lisible.") from error
    if page_count < 1:
        raise ValueError("Le PDF doit contenir au moins une page.")
    return digest, page_count


def backfill_pdf_metadata(connection):
    rows = connection.execute(
        """
        SELECT id, file_path, file_name FROM resources
        WHERE file_size IS NULL OR file_name_normalized IS NULL
        """
    ).fetchall()
    for row in rows:
        path = UPLOAD_DIR / row["file_path"]
        if not path.is_file():
            raise FileNotFoundError(f"Le PDF référencé par la ressource {row['id']} est introuvable : {path}")
        connection.execute(
            """
            UPDATE resources
            SET file_size = COALESCE(file_size, ?),
                file_name_normalized = COALESCE(file_name_normalized, ?)
            WHERE id = ?
            """,
            (path.stat().st_size, normalized_pdf_filename(row["file_name"]), row["id"]),
        )


def backfill_matching_pdf_hashes(connection, file_size):
    rows = connection.execute(
        "SELECT id, file_path FROM resources WHERE file_size = ? AND file_sha256 IS NULL",
        (file_size,),
    ).fetchall()
    for row in rows:
        path = UPLOAD_DIR / row["file_path"]
        if not path.is_file():
            raise FileNotFoundError(f"Le PDF référencé par la ressource {row['id']} est introuvable : {path}")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        connection.execute("UPDATE resources SET file_sha256 = ? WHERE id = ?", (digest.hexdigest(), row["id"]))


def backfill_matching_pdf_page_counts(connection, normalized_filename):
    rows = connection.execute(
        """
        SELECT id, file_path FROM resources
        WHERE file_name_normalized = ? AND page_count IS NULL
        """,
        (normalized_filename,),
    ).fetchall()
    for row in rows:
        path = UPLOAD_DIR / row["file_path"]
        if not path.is_file():
            raise FileNotFoundError(f"Le PDF référencé par la ressource {row['id']} est introuvable : {path}")
        _, page_count = inspect_pdf(path.read_bytes())
        connection.execute("UPDATE resources SET page_count = ? WHERE id = ?", (page_count, row["id"]))


@contextmanager
def connect_db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_db():
    with connect_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS majors (
                id INTEGER PRIMARY KEY,
                academic_level TEXT NOT NULL,
                name TEXT NOT NULL,
                UNIQUE (academic_level, name)
            );
            CREATE TABLE IF NOT EXISTS academic_years (
                year TEXT PRIMARY KEY,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY,
                username TEXT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email_verified_at TEXT,
                verification_token_hash TEXT,
                verification_expires_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS student_access_grants (
                id INTEGER PRIMARY KEY,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                academic_level TEXT NOT NULL,
                major TEXT NOT NULL,
                category TEXT NOT NULL,
                academic_year TEXT NOT NULL,
                semester TEXT NOT NULL,
                module TEXT NOT NULL,
                document_type TEXT NOT NULL,
                exam_type TEXT,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                correction_path TEXT,
                correction_name TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                viewer_count INTEGER NOT NULL DEFAULT 0,
                download_count INTEGER NOT NULL DEFAULT 0,
                correction_download_count INTEGER NOT NULL DEFAULT 0,
                owner_id INTEGER REFERENCES students(id),
                access_grant_id INTEGER REFERENCES student_access_grants(id),
                file_sha256 TEXT,
                file_name_normalized TEXT,
                page_count INTEGER,
                file_size INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS resources_public_browse
                ON resources (status, academic_level, major, category, academic_year, semester, module);
            CREATE INDEX IF NOT EXISTS student_access_grants_owner_expiry
                ON student_access_grants (student_id, starts_at, expires_at);
            """
        )
        student_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(students)").fetchall()
        }
        if "username" not in student_columns:
            connection.execute("ALTER TABLE students ADD COLUMN username TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS students_username_unique ON students (username COLLATE NOCASE) WHERE username IS NOT NULL"
        )
        resource_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(resources)").fetchall()
        }
        if "correction_download_count" not in resource_columns:
            connection.execute(
                "ALTER TABLE resources ADD COLUMN correction_download_count INTEGER NOT NULL DEFAULT 0"
            )
        resource_migrations = {
            "owner_id": "INTEGER REFERENCES students(id)",
            "access_grant_id": "INTEGER REFERENCES student_access_grants(id)",
            "file_sha256": "TEXT",
            "file_name_normalized": "TEXT",
            "page_count": "INTEGER",
            "file_size": "INTEGER",
        }
        for column, definition in resource_migrations.items():
            if column not in resource_columns:
                connection.execute(f"ALTER TABLE resources ADD COLUMN {column} {definition}")
        initialize_student_activity_schema(connection)
        connection.execute("CREATE INDEX IF NOT EXISTS resources_file_sha256 ON resources (file_sha256)")
        connection.execute("CREATE INDEX IF NOT EXISTS resources_file_size ON resources (file_size)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS resources_normalized_name_pages ON resources (file_name_normalized, page_count)"
        )
        backfill_pdf_metadata(connection)
        connection.executemany(
            "INSERT OR IGNORE INTO academic_years (year) VALUES (?)",
            ((year,) for year in ACADEMIC_YEARS),
        )
        default_majors = (
            ("Tronc Commun", "Génie Informatique"),
            ("Tronc Commun", "Génie Chimique"),
            ("Tronc Commun", "Mathématiques et Sciences des Données"),
            ("Tronc Commun", "Génie Électrique et Systèmes Embarqués"),
            ("Tronc Commun", "Génie Mécanique et Systèmes Industriels"),
            ("Tronc Commun", "Génie Biologie"),
            ("Licence", "Génie Informatique"),
            ("Licence", "Génie Civil"),
            ("Licence", "Génie Digital & Intelligence Artificielle"),
            ("Licence", "LST – Mathématiques et Sciences des Données"),
            ("Licence", "Génie Chimique, Environnement et Digitalisation"),
            ("Licence", "Mécatronique"),
            ("Licence", "Génie des Procédés, Techniques d'Analyse et Contrôle Qualité"),
            ("Licence", "Sciences Biomédicales"),
            ("Licence", "Agriculture et Développement Durable"),
            ("Licence", "Électronique, Électrotechnique et Automatique"),
            ("Licence", "Géophysique Appliquée, Matériaux et Ingénierie Minière"),
            ("Licence", "Systèmes Intelligents et Objets Connectés"),
            ("Licence", "Système d'Information et Transformation Digitale"),
            ("Licence", "Technologie Agroalimentaire"),
            ("Master", "Analyses et Gestion Qualité"),
            ("Master", "Analyses et Gestion Qualité Sécurité Hygiène Environnement"),
            ("Master", "Automatique, Traitement de Signal et Informatique Industrielle"),
            ("Master", "Bio-ingénierie"),
            ("Master", "Eau, Sol et Environnement Durable"),
            ("Master", "Génie Civil - Bâtiments, Ponts et Chaussées"),
            ("Master", "Ingénierie Chimique et Sciences des Matériaux"),
            ("Master", "Ingénierie des Réseaux Informatique et Systèmes de Télécoms Intelligents"),
            ("Master", "Ingénierie et Sciences des Matériaux"),
            ("Master", "MECATRONIQUE"),
            ("Master", "MST Ingénierie Logicielle et Cybersécurité"),
            ("Master", "Management et Qualité en Agroalimentaire dans la Grande Distribution"),
            ("Master", "Master Ingénierie et Management Industriel"),
            ("Master", "Master Mathématiques et Sciences des Données"),
            ("Master", "Mathématiques et Technologies Emergentes"),
            ("Master", "Prospection et Valorisation des Ressources Minérales"),
            ("Master", "Réseaux et Systèmes Informatiques"),
            ("Master", "Systèmes Intelligents Connectés, Réseaux Avancés et Télécoms"),
            ("Cycle Ingénieur", "Génie Informatique"),
            ("Cycle Ingénieur", "Procédés et Ingénierie Chimique"),
            ("Cycle Ingénieur", "Ingénierie Biomédicale : Instrumentation & Maintenance"),
            ("Cycle Ingénieur", "Ingénierie de Conception et Productique"),
            ("Cycle Ingénieur", "Ingénierie des Systèmes Electriques et Systèmes Embarqués"),
        )
        connection.execute(
            "DELETE FROM majors WHERE academic_level = ? AND name = ?",
            ("Licence", "Sciences Économiques"),
        )
        connection.execute(
            "DELETE FROM majors WHERE academic_level = ? AND name IN (?, ?)",
            ("Master", "Génie Informatique", "Génie Civil"),
        )
        connection.execute(
            "DELETE FROM majors WHERE academic_level = ? AND name = ?",
            ("Cycle Ingénieur", "Génie Civil"),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO majors (academic_level, name) VALUES (?, ?)",
            default_majors,
        )


initialize_db()


def api_error(message, status=400):
    return jsonify({"error": message}), status


def require_admin():
    if session.get("admin_role") != "administrator":
        return False
    student_id = student_session_id()
    admin_email = os.environ.get("MABIBLIO_ADMIN_EMAIL", "").strip().lower()
    if student_id is None or not admin_email:
        return False
    with connect_db() as connection:
        student = connection.execute(
            "SELECT email, email_verified_at FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
    return bool(
        student
        and student["email_verified_at"]
        and student["email"].strip().lower() == admin_email
    )


def require_admin_response():
    if not os.environ.get("MABIBLIO_ADMIN_EMAIL", "").strip():
        return api_error("L’accès administrateur n’est pas configuré. Définissez MABIBLIO_ADMIN_EMAIL avant de démarrer le serveur.", 503)
    if not require_admin():
        return api_error("Connectez-vous avec le compte administrateur vérifié.", 401)
    return None


def student_session_id():
    student_id = session.get("student_id")
    return student_id if isinstance(student_id, int) else None


def has_student_download_access(student_id):
    now = datetime.now(timezone.utc).isoformat()
    with connect_db() as connection:
        grant = connection.execute(
            """
            SELECT 1 FROM student_access_grants
            WHERE student_id = ? AND starts_at <= ? AND expires_at > ?
            LIMIT 1
            """,
            (student_id, now, now),
        ).fetchone()
    return grant is not None


def student_account_status(student_id):
    now = datetime.now(timezone.utc).isoformat()
    with connect_db() as connection:
        student = connection.execute(
            "SELECT id,username,email,email_verified_at FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        if not student:
            return {"authenticated": False}
        approved_count = connection.execute(
            """
            SELECT COUNT(DISTINCT file_sha256) FROM resources
            WHERE owner_id = ? AND status = 'approved'
              AND access_grant_id IS NULL AND file_sha256 IS NOT NULL
            """,
            (student_id,),
        ).fetchone()[0]
        active_grant = connection.execute(
            """
            SELECT expires_at FROM student_access_grants
            WHERE student_id = ? AND starts_at <= ? AND expires_at > ?
            ORDER BY expires_at DESC LIMIT 1
            """,
            (student_id, now, now),
        ).fetchone()
        next_grant = connection.execute(
            """
            SELECT starts_at,expires_at FROM student_access_grants
            WHERE student_id = ? AND starts_at > ?
            ORDER BY starts_at LIMIT 1
            """,
            (student_id, now),
        ).fetchone()
    return {
        "authenticated": True,
        "username": student["username"],
        "email": student["email"],
        "approvedForNextAccess": approved_count,
        "remainingContributions": max(REQUIRED_STUDENT_CONTRIBUTIONS - approved_count, 0),
        "requiredContributions": REQUIRED_STUDENT_CONTRIBUTIONS,
        "accessDurationHours": int(STUDENT_ACCESS_DURATION.total_seconds() // 3600),
        "canDownloadStudentContributions": active_grant is not None,
        "accessUntil": active_grant["expires_at"] if active_grant else None,
        "nextAccessStartsAt": next_grant["starts_at"] if next_grant else None,
    }


def grant_eligible_student_access(connection, student_id):
    created_grants = []
    while True:
        contributions = connection.execute(
            """
            SELECT MIN(id) AS resource_id, file_sha256
            FROM resources
            WHERE owner_id = ? AND status = 'approved'
              AND access_grant_id IS NULL AND file_sha256 IS NOT NULL
            GROUP BY file_sha256
            ORDER BY MIN(id)
            LIMIT ?
            """,
            (student_id, REQUIRED_STUDENT_CONTRIBUTIONS),
        ).fetchall()
        if len(contributions) < REQUIRED_STUDENT_CONTRIBUTIONS:
            return created_grants
        now = datetime.now(timezone.utc)
        previous_expiry = connection.execute(
            "SELECT MAX(expires_at) FROM student_access_grants WHERE student_id = ?",
            (student_id,),
        ).fetchone()[0]
        starts_at = now
        if previous_expiry:
            starts_at = max(starts_at, datetime.fromisoformat(previous_expiry))
        expires_at = starts_at + STUDENT_ACCESS_DURATION
        cursor = connection.execute(
            """
            INSERT INTO student_access_grants (student_id, starts_at, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (student_id, starts_at.isoformat(), expires_at.isoformat(), now.isoformat()),
        )
        grant_id = cursor.lastrowid
        connection.executemany(
            "UPDATE resources SET access_grant_id = ? WHERE id = ?",
            ((grant_id, row["resource_id"]) for row in contributions),
        )
        created_grants.append({"startsAt": starts_at.isoformat(), "expiresAt": expires_at.isoformat()})


def get_public_base_url():
    configured_url = os.environ.get("MABIBLIO_PUBLIC_URL", "").strip()
    if configured_url:
        return configured_url.rstrip("/")

    try:
        host = request.host.lower()
    except RuntimeError:
        host = ""

    if host.startswith(("127.0.0.1", "localhost", "[::1]", "::1")):
        try:
            return request.host_url.rstrip("/")
        except RuntimeError:
            return "http://127.0.0.1:8000"

    return "https://mabiblio.pythonanywhere.com"


def send_student_verification_email(email, token):
    host = os.environ.get("MABIBLIO_SMTP_HOST", "").strip()
    sender = os.environ.get("MABIBLIO_FROM_EMAIL", "").strip()
    if not host or not sender:
        raise RuntimeError("La vérification par e-mail n’est pas configurée sur le serveur.")
    try:
        port = int(os.environ.get("MABIBLIO_SMTP_PORT", "587"))
        message = EmailMessage()
        message["Subject"] = "Vérifiez votre adresse e-mail — MaBiblio"
        message["From"] = sender
        message["To"] = email
        base_url = get_public_base_url()
        verification_url = f"{base_url}/api/student/verify?token={quote(token)}"
        message.set_content(
            f"Confirmez votre adresse e-mail en ouvrant ce lien (valable 24 heures) :\n{verification_url}\n"
        )
        username = os.environ.get("MABIBLIO_SMTP_USERNAME", "")
        password = os.environ.get("MABIBLIO_SMTP_PASSWORD", "")
        if bool(username) != bool(password):
            raise RuntimeError("Le nom d’utilisateur et le mot de passe SMTP doivent être configurés ensemble.")
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if os.environ.get("MABIBLIO_SMTP_STARTTLS", "1") != "0":
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as error:
        raise RuntimeError("Impossible d’envoyer l’e-mail de vérification. Vérifiez la configuration SMTP.") from error


def normalize_category(value):
    aliases = {
        "exams": "Exams",
        "exam": "Exams",
        "courses": "Courses",
        "course": "Courses",
        "td & tp": "TD & TP",
        "td/tp": "TD & TP",
        "td": "TD & TP",
        "tp": "TD & TP",
    }
    return aliases.get(str(value or "").strip().lower())


def serialize_resource(row, include_status=False):
    result = {
        "id": row["id"],
        "title": row["title"],
        "academicLevel": row["academic_level"],
        "major": row["major"],
        "category": row["category"],
        "academicYear": row["academic_year"],
        "semester": row["semester"],
        "module": row["module"],
        "documentType": row["document_type"],
        "examType": row["exam_type"],
        "fileType": "PDF",
        "previewType": "pdf",
        "previewUrl": f"/api/resources/{row['id']}/preview",
        "downloadUrl": f"/api/resources/{row['id']}/download",
        "viewerCount": row["viewer_count"],
        "downloadCount": row["download_count"],
        "correctionDownloadCount": row["correction_download_count"],
        "createdAt": row["created_at"],
        "hasCorrection": bool(row["correction_path"]),
        "correctionPreviewUrl": f"/api/resources/{row['id']}/correction/preview" if row["correction_path"] else None,
        "correctionDownloadUrl": f"/api/resources/{row['id']}/correction/download" if row["correction_path"] else None,
    }
    if include_status:
        result["status"] = row["status"]
        result["fileName"] = row["file_name"]
        result["submittedBy"] = row["student_email"] if "student_email" in row.keys() else None
    else:
        result["status"] = "approved"
    return result


def get_resource(resource_id, approved_only=True):
    with connect_db() as connection:
        row = connection.execute(
            "SELECT * FROM resources WHERE id = ?" + (" AND status = 'approved'" if approved_only else ""),
            (resource_id,),
        ).fetchone()
    return row


def store_pdf(upload, prefix):
    if not upload or not upload.filename:
        raise ValueError("Un document PDF est requis.")
    original_name = secure_filename(upload.filename)
    if not original_name or Path(original_name).suffix.lower() != ".pdf":
        raise ValueError("Seuls les fichiers PDF sont autorisés.")
    data = upload.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Chaque PDF doit faire 20 Mo ou moins.")
    if not data.startswith(b"%PDF-"):
        raise ValueError("Le fichier téléversé n’est pas un PDF valide.")
    digest, page_count = inspect_pdf(data)
    relative_path = f"{uuid.uuid4().hex}-{prefix}.pdf"
    destination = UPLOAD_DIR / relative_path
    with destination.open("wb") as target:
        target.write(data)
    return relative_path, original_name, digest, page_count


def validate_resource_form(form):
    title = form.get("title", "").strip()
    level = form.get("academicLevel", "").strip()
    major = form.get("major", "").strip()
    category = normalize_category(form.get("category"))
    year = form.get("academicYear", "").strip()
    semester = form.get("semester", "").strip()
    module = form.get("module", "").strip()
    document_type = form.get("documentType", "").strip()
    exam_type = form.get("examType", "").strip() or None

    if not title or len(title) > 180:
        raise ValueError("Saisissez un titre de document (180 caractères maximum).")
    if level not in LEVELS:
        raise ValueError("Sélectionnez un niveau académique valide.")
    if not major or len(major) > 120:
        raise ValueError("Sélectionnez ou saisissez une filière valide.")
    with connect_db() as connection:
        known_major = connection.execute(
            "SELECT 1 FROM majors WHERE academic_level = ? AND name = ?",
            (level, major),
        ).fetchone()
    if not known_major:
        raise ValueError("Sélectionnez une filière configurée par l’administrateur pour ce niveau.")
    if not category:
        raise ValueError("Sélectionnez Examens, Cours ou TD & TP.")
    if not re.fullmatch(r"\d{4}[–-]\d{4}", year):
        raise ValueError("Saisissez une année académique telle que 2025–2026.")
    with connect_db() as connection:
        known_year = connection.execute(
            "SELECT 1 FROM academic_years WHERE year = ? AND active = 1",
            (year.replace("-", "–"),),
        ).fetchone()
    if not known_year:
        raise ValueError("Sélectionnez une année académique configurée par l’administrateur.")
    if semester not in SEMESTERS:
        raise ValueError("Sélectionnez un semestre valide.")
    if not module or len(module) > 120:
        raise ValueError("Sélectionnez ou saisissez un module (120 caractères maximum).")
    if document_type not in DOCUMENT_TYPES[category]:
        raise ValueError("Sélectionnez un type de document valide pour la catégorie choisie.")
    if category == "Exams" and exam_type not in EXAM_TYPES:
        raise ValueError("Sélectionnez Session normale ou Rattrapage pour un examen.")
    if category != "Exams":
        exam_type = None

    return {
        "title": title,
        "academic_level": level,
        "major": major,
        "category": category,
        "academic_year": year.replace("-", "–"),
        "semester": semester,
        "module": module,
        "document_type": document_type,
        "exam_type": exam_type,
    }


@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:page>")
def public_page(page):
    if page not in ALLOWED_PAGES:
        abort(404)
    return send_from_directory(ROOT, page)


@app.get("/api/levels")
def get_levels():
    return jsonify({"levels": list(LEVELS)})


@app.get("/api/majors")
def get_majors():
    level = request.args.get("level", "").strip()
    if level and level not in LEVELS:
        return api_error("Niveau académique inconnu.")
    with connect_db() as connection:
        if level:
            rows = connection.execute(
                "SELECT academic_level, name FROM majors WHERE academic_level = ? ORDER BY name COLLATE NOCASE",
                (level,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT academic_level, name FROM majors ORDER BY academic_level, name COLLATE NOCASE"
            ).fetchall()
    return jsonify({"majors": [{"academicLevel": row["academic_level"], "name": row["name"]} for row in rows]})


@app.get("/api/academic-years")
def get_academic_years():
    with connect_db() as connection:
        rows = connection.execute("SELECT year FROM academic_years WHERE active = 1 ORDER BY year DESC").fetchall()
    return jsonify({"academicYears": [row["year"] for row in rows]})


@app.post("/api/student/register")
def register_student():
    values = request.get_json(silent=True) or request.form
    username = str(values.get("username", "")).strip()
    email = str(values.get("email", "")).strip().lower()
    password = str(values.get("password", ""))
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", username):
        return api_error("Le nom d’utilisateur doit contenir 3 à 32 lettres, chiffres, points, tirets ou soulignés.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        return api_error("Saisissez une adresse e-mail valide, personnelle ou institutionnelle.")
    if len(password) < 12 or len(password) > 128:
        return api_error("Le mot de passe doit contenir entre 12 et 128 caractères.")
    if not os.environ.get("MABIBLIO_SMTP_HOST") or not os.environ.get("MABIBLIO_FROM_EMAIL"):
        return api_error("La vérification par e-mail n’est pas encore configurée sur le serveur.", 503)

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    try:
        with connect_db() as connection:
            username_owner = connection.execute(
                "SELECT 1 FROM students WHERE username = ? COLLATE NOCASE AND email != ? LIMIT 1",
                (username, email),
            ).fetchone()
            if username_owner:
                return api_error("Ce nom d’utilisateur est déjà utilisé.", 409)
            student = connection.execute(
                "SELECT id,email_verified_at FROM students WHERE email = ?",
                (email,),
            ).fetchone()
            if student and student["email_verified_at"]:
                return api_error("Un compte existe déjà pour cette adresse e-mail.", 409)
            if student:
                connection.execute(
                    """
                    UPDATE students
                    SET username = ?, password_hash = ?, verification_token_hash = ?,
                        verification_expires_at = ?
                    WHERE id = ?
                    """,
                    (
                        username,
                        generate_password_hash(password),
                        token_hash,
                        (now + EMAIL_VERIFICATION_DURATION).isoformat(),
                        student["id"],
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO students (
                        username, email, password_hash, verification_token_hash,
                        verification_expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        email,
                        generate_password_hash(password),
                        token_hash,
                        (now + EMAIL_VERIFICATION_DURATION).isoformat(),
                        now.isoformat(),
                    ),
                )
    except sqlite3.IntegrityError:
        return api_error("Ce nom d’utilisateur ou cette adresse e-mail est déjà utilisé.", 409)
    try:
        send_student_verification_email(email, token)
    except RuntimeError as error:
        return api_error(str(error), 503)
    return jsonify({"message": "Un lien de vérification a été envoyé par e-mail."}), 202


@app.get("/api/student/verify")
def verify_student_email():
    token = request.args.get("token", "")
    if not token:
        return redirect("/?emailVerified=0#upload")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with connect_db() as connection:
        result = connection.execute(
            """
            UPDATE students
            SET email_verified_at = ?, verification_token_hash = NULL, verification_expires_at = NULL
            WHERE verification_token_hash = ? AND verification_expires_at > ? AND email_verified_at IS NULL
            """,
            (now, token_hash, now),
        )
    return redirect("/?emailVerified=1#upload" if result.rowcount == 1 else "/?emailVerified=0#upload")


@app.get("/api/student/account")
def get_student_account():
    student_id = student_session_id()
    if student_id is None:
        return jsonify({"authenticated": False})
    status = student_account_status(student_id)
    if not status["authenticated"]:
        session.pop("student_id", None)
    return jsonify(status)


@app.post("/api/student/session")
def create_student_session():
    values = request.get_json(silent=True) or request.form
    identifier = str(values.get("identifier") or values.get("email") or values.get("username") or "").strip()
    normalized_identifier = identifier.lower()
    password = str(values.get("password", ""))
    with connect_db() as connection:
        student = connection.execute(
            """
            SELECT id,email,password_hash,email_verified_at FROM students
            WHERE email = ? OR username = ? COLLATE NOCASE
            """,
            (normalized_identifier, identifier),
        ).fetchone()
    if not student or not check_password_hash(student["password_hash"], password):
        return api_error("Adresse e-mail ou mot de passe incorrect.", 401)
    if not student["email_verified_at"]:
        return api_error("Vérifiez votre adresse e-mail avant de vous connecter.", 403)
    session.clear()
    session["student_id"] = student["id"]
    admin_email = os.environ.get("MABIBLIO_ADMIN_EMAIL", "").strip().lower()
    if admin_email and student["email"].strip().lower() == admin_email:
        session["admin_role"] = "administrator"
    with connect_db() as connection:
        record_student_activity(connection, student["id"], "sign_in")
    return jsonify(student_account_status(student["id"]))


@app.delete("/api/student/session")
def destroy_student_session():
    student_id = student_session_id()
    if student_id is not None:
        with connect_db() as connection:
            record_student_activity(connection, student_id, "sign_out")
            connection.execute(
                "UPDATE students SET last_activity_ping_at = NULL WHERE id = ?",
                (student_id,),
            )
    session.clear()
    return jsonify({"authenticated": False})


@app.get("/api/filters")
def get_filters():
    level = request.args.get("academicLevel", "")
    major = request.args.get("major", "")
    category = normalize_category(request.args.get("category")) if request.args.get("category") else ""
    if request.args.get("category") and not category:
        return api_error("Catégorie de ressource inconnue.")
    clauses = ["status = 'approved'"]
    parameters = []
    for column, value in (
        ("academic_level", level),
        ("major", major),
        ("category", category),
        ("academic_year", request.args.get("academicYear", "")),
        ("semester", request.args.get("semester", "")),
        ("module", request.args.get("module", "")),
        ("document_type", request.args.get("documentType", "")),
        ("exam_type", request.args.get("examType", "")),
    ):
        if value:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    where = " AND ".join(clauses)
    with connect_db() as connection:
        rows = connection.execute(
            f"SELECT DISTINCT academic_year, semester, module, document_type, exam_type FROM resources WHERE {where}",
            parameters,
        ).fetchall()
    return jsonify({
        "academicYears": sorted({row["academic_year"] for row in rows}, reverse=True),
        "semesters": sorted({row["semester"] for row in rows}),
        "modules": sorted({row["module"] for row in rows}, key=str.casefold),
        "documentTypes": sorted({row["document_type"] for row in rows}, key=str.casefold),
        "examTypes": sorted({row["exam_type"] for row in rows if row["exam_type"]}, key=str.casefold),
    })


@app.get("/api/resources")
def list_resources():
    category = request.args.get("category", "")
    normalized = normalize_category(category) if category else ""
    if category and not normalized:
        return api_error("Catégorie de ressource inconnue.")
    filters = (
        ("academic_level", "academicLevel"),
        ("major", "major"),
        ("academic_year", "academicYear"),
        ("semester", "semester"),
        ("module", "module"),
        ("document_type", "documentType"),
        ("exam_type", "examType"),
    )
    clauses = ["status = 'approved'"]
    parameters = []
    if normalized:
        clauses.append("category = ?")
        parameters.append(normalized)
    for column, key in filters:
        value = request.args.get(key, "").strip()
        if value:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    search = request.args.get("search", "").strip()
    if search:
        clauses.append("(title LIKE ? OR module LIKE ? OR major LIKE ?)")
        search_pattern = f"%{search[:100]}%"
        parameters.extend((search_pattern, search_pattern, search_pattern))

    try:
        limit = min(max(int(request.args.get("limit", "8")), 1), 100)
        offset = max(int(request.args.get("offset", "0")), 0)
    except ValueError:
        return api_error("La limite et le décalage doivent être des nombres entiers.")

    where = " AND ".join(clauses)
    with connect_db() as connection:
        total = connection.execute(
            f"SELECT COUNT(DISTINCT file_name) FROM resources WHERE {where}",
            parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT * FROM (
                SELECT resources.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY file_name
                           ORDER BY created_at DESC, id DESC
                       ) AS duplicate_rank
                FROM resources
                WHERE {where}
            )
            WHERE duplicate_rank = 1
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
    student_id = student_session_id()
    student_signed_in = student_id is not None and student_account_status(student_id)["authenticated"]
    if student_id is not None and not student_signed_in:
        session.pop("student_id", None)
    can_download_student_resources = False
    if student_id is not None and student_signed_in:
        can_download_student_resources = has_student_download_access(student_id)
    resources = []
    for row in rows:
        resource = serialize_resource(row)
        resource["studentContribution"] = row["owner_id"] is not None
        resource["downloadLocked"] = row["owner_id"] is not None and not can_download_student_resources
        resource["requiresSignIn"] = not student_signed_in
        resources.append(resource)
    return jsonify({"resources": resources, "total": total, "limit": limit, "offset": offset})


@app.post("/api/resources")
def upload_resource():
    file_path = correction_path = None
    try:
        student_id = student_session_id()
        if student_id is None:
            return api_error("Connectez-vous avec un compte étudiant vérifié pour proposer un document.", 401)
        if not student_account_status(student_id)["authenticated"]:
            session.pop("student_id", None)
            return api_error("La session étudiant est invalide. Connectez-vous de nouveau.", 401)
        values = validate_resource_form(request.form)
        correction_file = request.files.get("correction")
        if correction_file and correction_file.filename and values["category"] != "Exams":
            return api_error("Une correction PDF supplémentaire n’est acceptée que pour les examens.")
        file_path, file_name, file_sha256, page_count = store_pdf(request.files.get("file"), "document")
        file_size = (UPLOAD_DIR / file_path).stat().st_size
        correction_name = None
        if correction_file and correction_file.filename:
            correction_path, correction_name, _, _ = store_pdf(correction_file, "correction")
        created_at = datetime.now(timezone.utc).isoformat()
        try:
            with connect_db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                backfill_matching_pdf_hashes(connection, file_size)
                backfill_matching_pdf_page_counts(connection, normalized_pdf_filename(file_name))
                duplicate = connection.execute(
                    """
                    SELECT id FROM resources
                    WHERE file_sha256 = ?
                       OR (file_name_normalized = ? AND page_count = ?)
                    LIMIT 1
                    """,
                    (file_sha256, normalized_pdf_filename(file_name), page_count),
                ).fetchone()
                if duplicate:
                    if file_path:
                        (UPLOAD_DIR / file_path).unlink(missing_ok=True)
                        file_path = None
                    if correction_path:
                        (UPLOAD_DIR / correction_path).unlink(missing_ok=True)
                        correction_path = None
                    return api_error(
                        "Ce PDF existe déjà sur le site (contenu identique, ou même nom et nombre de pages).",
                        409,
                    )
                cursor = connection.execute(
                    """
                    INSERT INTO resources (
                        title, academic_level, major, category, academic_year, semester,
                        module, document_type, exam_type, file_path, file_name,
                        correction_path, correction_name, owner_id, file_sha256,
                        file_name_normalized, page_count, file_size, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        values["title"], values["academic_level"], values["major"], values["category"],
                        values["academic_year"], values["semester"], values["module"],
                        values["document_type"], values["exam_type"], file_path, file_name,
                        correction_path, correction_name, student_id, file_sha256,
                        normalized_pdf_filename(file_name), page_count, file_size, created_at,
                    ),
                )
                resource_id = cursor.lastrowid
        except Exception:
            if file_path:
                (UPLOAD_DIR / file_path).unlink(missing_ok=True)
            if correction_path:
                (UPLOAD_DIR / correction_path).unlink(missing_ok=True)
            raise
        return jsonify({
            "message": "Document reçu et en attente d’approbation. Il comptera après validation de l’administrateur.",
            "status": "pending",
            "id": resource_id,
            "pageCount": page_count,
        }), 201
    except ValueError as error:
        if file_path:
            (UPLOAD_DIR / file_path).unlink(missing_ok=True)
        if correction_path:
            (UPLOAD_DIR / correction_path).unlink(missing_ok=True)
        return api_error(str(error))


@app.get("/api/resources/<int:resource_id>")
def resource_details(resource_id):
    with connect_db() as connection:
        row = connection.execute(
            "SELECT * FROM resources WHERE id = ? AND status = 'approved'",
            (resource_id,),
        ).fetchone()
        if not row:
            return api_error("Ressource introuvable.", 404)
        connection.execute("UPDATE resources SET viewer_count = viewer_count + 1 WHERE id = ?", (resource_id,))
        row = connection.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    resource = serialize_resource(row)
    student_id = student_session_id()
    student_signed_in = student_id is not None and student_account_status(student_id)["authenticated"]
    if student_id is not None and not student_signed_in:
        session.pop("student_id", None)
    can_download = False
    if student_id is not None and student_signed_in:
        can_download = has_student_download_access(student_id)
    resource["studentContribution"] = row["owner_id"] is not None
    resource["downloadLocked"] = row["owner_id"] is not None and not can_download
    resource["requiresSignIn"] = not student_signed_in
    return jsonify({"resource": resource})


def send_resource_file(resource_id, field, filename_field, as_attachment):
    row = get_resource(resource_id)
    if not row:
        abort(404)
    student_id = student_session_id()
    student_signed_in = student_id is not None and student_account_status(student_id)["authenticated"]
    if student_id is not None and not student_signed_in:
        session.pop("student_id", None)
    if as_attachment and not student_signed_in:
        return api_error("Connectez-vous avec un compte étudiant vérifié pour télécharger un document.", 401)
    if row["owner_id"] is not None:
        if student_id is None or not student_signed_in:
            return api_error("Connectez-vous pour accéder aux documents partagés par les étudiants.", 401)
        if not has_student_download_access(student_id):
            return api_error(
                "Les téléchargements des documents étudiants nécessitent trois contributions uniques approuvées, avec un accès actif.",
                403,
            )
    relative_path = row[field]
    if not relative_path:
        abort(404)
    path = UPLOAD_DIR / relative_path
    if not path.is_file():
        abort(404)
    if as_attachment:
        with connect_db() as connection:
            count_column = "correction_download_count" if field == "correction_path" else "download_count"
            connection.execute(
                f"UPDATE resources SET {count_column} = {count_column} + 1 WHERE id = ? AND status = 'approved'",
                (resource_id,),
            )
            record_student_activity(
                connection,
                student_id,
                "correction_download" if field == "correction_path" else "download",
                row["title"],
            )
    return send_file(path, mimetype="application/pdf", as_attachment=as_attachment, download_name=row[filename_field])


@app.get("/api/resources/<int:resource_id>/preview")
def preview_resource(resource_id):
    return send_resource_file(resource_id, "file_path", "file_name", False)


@app.get("/api/resources/<int:resource_id>/download")
def download_resource(resource_id):
    return send_resource_file(resource_id, "file_path", "file_name", True)


@app.get("/api/resources/<int:resource_id>/correction/preview")
def preview_correction(resource_id):
    return send_resource_file(resource_id, "correction_path", "correction_name", False)


@app.get("/api/resources/<int:resource_id>/correction/download")
def download_correction(resource_id):
    return send_resource_file(resource_id, "correction_path", "correction_name", True)


@app.errorhandler(413)
def request_too_large(_error):
    return api_error("La requête est trop volumineuse. Chaque PDF doit faire 20 Mo ou moins.", 413)


@app.get("/api/admin/resources")
def admin_list_resources():
    error = require_admin_response()
    if error:
        return error
    status = request.args.get("status", "pending")
    if status not in ("pending", "approved", "rejected", "all"):
        return api_error("Statut de document inconnu.")
    with connect_db() as connection:
        rows = connection.execute(
            """
            SELECT resources.*, students.email AS student_email
            FROM resources
            LEFT JOIN students ON students.id = resources.owner_id
            """ + ("" if status == "all" else " WHERE resources.status = ?") + " ORDER BY resources.created_at DESC",
            () if status == "all" else (status,),
        ).fetchall()
    resources = []
    for row in rows:
        resource = serialize_resource(row, include_status=True)
        resource["previewUrl"] = f"/api/admin/resources/{row['id']}/preview"
        if row["correction_path"]:
            resource["correctionPreviewUrl"] = f"/api/admin/resources/{row['id']}/correction/preview"
            resource["correctionDownloadUrl"] = f"/api/admin/resources/{row['id']}/correction/download"
        resources.append(resource)
    return jsonify({"resources": resources})


@app.post("/api/admin/resources")
def admin_upload_resource():
    error = require_admin_response()
    if error:
        return error
    file_path = correction_path = None
    try:
        values = validate_resource_form(request.form)
        correction_file = request.files.get("correction")
        if correction_file and correction_file.filename and values["category"] != "Exams":
            return api_error("Une correction PDF supplémentaire n’est acceptée que pour les examens.")
        file_path, file_name, file_sha256, page_count = store_pdf(request.files.get("file"), "document")
        file_size = (UPLOAD_DIR / file_path).stat().st_size
        correction_name = None
        if correction_file and correction_file.filename:
            correction_path, correction_name, _, _ = store_pdf(correction_file, "correction")
        created_at = datetime.now(timezone.utc).isoformat()
        try:
            with connect_db() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO resources (
                        title, academic_level, major, category, academic_year, semester,
                        module, document_type, exam_type, file_path, file_name,
                        correction_path, correction_name, file_sha256, file_name_normalized,
                        page_count, file_size, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?)
                    """,
                    (
                        values["title"], values["academic_level"], values["major"], values["category"],
                        values["academic_year"], values["semester"], values["module"],
                        values["document_type"], values["exam_type"], file_path, file_name,
                        correction_path, correction_name, file_sha256,
                        normalized_pdf_filename(file_name), page_count, file_size, created_at,
                    ),
                )
                resource_id = cursor.lastrowid
        except Exception:
            if file_path:
                (UPLOAD_DIR / file_path).unlink(missing_ok=True)
            if correction_path:
                (UPLOAD_DIR / correction_path).unlink(missing_ok=True)
            raise
        return jsonify({
            "id": resource_id,
            "status": "approved",
            "message": "Document publié directement sur le site.",
            "pageCount": page_count,
        }), 201
    except ValueError as validation_error:
        if file_path:
            (UPLOAD_DIR / file_path).unlink(missing_ok=True)
        if correction_path:
            (UPLOAD_DIR / correction_path).unlink(missing_ok=True)
        return api_error(str(validation_error))


@app.get("/api/admin/session")
def get_admin_session():
    if require_admin():
        return jsonify({"authenticated": True, "role": "administrator"})
    return jsonify({"authenticated": False, "role": None})


@app.get("/api/admin/public-info")
def get_admin_public_info():
    contact_email = (
        os.environ.get("MABIBLIO_CONTACT_EMAIL")
        or os.environ.get("MABIBLIO_FROM_EMAIL")
        or os.environ.get("MABIBLIO_ADMIN_EMAIL")
        or ""
    ).strip()
    return jsonify({
        "contactEmail": contact_email,
        "termsAvailable": True,
        "privacyAvailable": True,
    })


@app.delete("/api/admin/session")
def destroy_admin_session():
    session.pop("admin_role", None)
    return jsonify({"authenticated": False})


def send_admin_file(resource_id, field, filename_field):
    error = require_admin_response()
    if error:
        return error
    row = get_resource(resource_id, approved_only=False)
    if not row or not row[field]:
        abort(404)
    path = UPLOAD_DIR / row[field]
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="application/pdf", download_name=row[filename_field])


@app.get("/api/admin/resources/<int:resource_id>/preview")
def preview_admin_resource(resource_id):
    return send_admin_file(resource_id, "file_path", "file_name")


@app.get("/api/admin/resources/<int:resource_id>/correction/preview")
def preview_admin_correction(resource_id):
    return send_admin_file(resource_id, "correction_path", "correction_name")


@app.post("/api/admin/resources/<int:resource_id>/review")
def review_resource(resource_id):
    error = require_admin_response()
    if error:
        return error
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("approved", "rejected"):
        return api_error("Le statut de vérification doit être approuvé ou rejeté.")
    with connect_db() as connection:
        row = connection.execute("SELECT owner_id FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if not row:
            return api_error("Ressource introuvable.", 404)
        connection.execute("UPDATE resources SET status = ? WHERE id = ?", (status, resource_id))
        grants = grant_eligible_student_access(connection, row["owner_id"]) if status == "approved" and row["owner_id"] else []
    return jsonify({"id": resource_id, "status": status, "accessGrants": grants})


@app.post("/api/admin/resources/<int:resource_id>/correction")
def add_correction(resource_id):
    error = require_admin_response()
    if error:
        return error
    row = get_resource(resource_id, approved_only=False)
    if not row:
        return api_error("Ressource introuvable.", 404)
    if row["category"] != "Exams":
        return api_error("Les corrections PDF ne peuvent être jointes qu’à des examens.")
    try:
        file_path, file_name, _, _ = store_pdf(request.files.get("correction"), "correction")
    except ValueError as validation_error:
        return api_error(str(validation_error))
    try:
        with connect_db() as connection:
            connection.execute(
                "UPDATE resources SET correction_path = ?, correction_name = ? WHERE id = ?",
                (file_path, file_name, resource_id),
            )
    except Exception:
        (UPLOAD_DIR / file_path).unlink(missing_ok=True)
        raise
    if row["correction_path"]:
        (UPLOAD_DIR / row["correction_path"]).unlink(missing_ok=True)
    return jsonify({"id": resource_id, "hasCorrection": True}), 201


@app.delete("/api/admin/resources/<int:resource_id>")
def delete_resource(resource_id):
    error = require_admin_response()
    if error:
        return error
    row = get_resource(resource_id, approved_only=False)
    if not row:
        return api_error("Ressource introuvable.", 404)
    with connect_db() as connection:
        connection.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    (UPLOAD_DIR / row["file_path"]).unlink(missing_ok=True)
    if row["correction_path"]:
        (UPLOAD_DIR / row["correction_path"]).unlink(missing_ok=True)
    return jsonify({"id": resource_id, "deleted": True})


@app.post("/api/admin/majors")
def add_major():
    error = require_admin_response()
    if error:
        return error
    values = request.get_json(silent=True) or {}
    level = str(values.get("academicLevel", "")).strip()
    name = str(values.get("name", "")).strip()
    if level not in LEVELS or not name or len(name) > 120:
        return api_error("Indiquez un niveau académique valide et un nom de filière.")
    try:
        with connect_db() as connection:
            connection.execute("INSERT INTO majors (academic_level, name) VALUES (?, ?)", (level, name))
    except sqlite3.IntegrityError:
        return api_error("Cette filière existe déjà pour ce niveau académique.", 409)
    return jsonify({"academicLevel": level, "name": name}), 201


@app.post("/api/admin/academic-years")
def add_academic_year():
    error = require_admin_response()
    if error:
        return error
    year = str((request.get_json(silent=True) or {}).get("year", "")).strip().replace("-", "–")
    if not re.fullmatch(r"\d{4}–\d{4}", year):
        return api_error("Saisissez une année académique telle que 2025–2026.")
    try:
        with connect_db() as connection:
            connection.execute("INSERT INTO academic_years (year) VALUES (?)", (year,))
    except sqlite3.IntegrityError:
        return api_error("Cette année académique existe déjà.", 409)
    return jsonify({"year": year}), 201


app.register_blueprint(
    create_student_activity_blueprint(connect_db, require_admin_response, student_session_id)
)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
