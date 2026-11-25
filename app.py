import hmac
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory, session
from werkzeug.utils import secure_filename


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
}

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("CAMPUSSHARE_SESSION_SECRET") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("CAMPUSSHARE_HTTPS") == "1"
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)


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
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS resources_public_browse
                ON resources (status, academic_level, major, category, academic_year, semester, module);
            """
        )
        resource_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(resources)").fetchall()
        }
        if "correction_download_count" not in resource_columns:
            connection.execute(
                "ALTER TABLE resources ADD COLUMN correction_download_count INTEGER NOT NULL DEFAULT 0"
            )
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
    if session.get("admin_authenticated") is True:
        return True
    expected = os.environ.get("CAMPUSSHARE_ADMIN_TOKEN", "")
    supplied = request.headers.get("X-Admin-Token", "")
    return bool(expected) and bool(supplied) and hmac.compare_digest(expected, supplied)


def require_admin_response():
    if not os.environ.get("CAMPUSSHARE_ADMIN_TOKEN"):
        return api_error("L’accès administrateur n’est pas configuré. Définissez CAMPUSSHARE_ADMIN_TOKEN avant de démarrer le serveur.", 503)
    if not require_admin():
        return api_error("Le jeton administrateur est manquant ou invalide.", 401)
    return None


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
    relative_path = f"{uuid.uuid4().hex}-{prefix}.pdf"
    destination = UPLOAD_DIR / relative_path
    with destination.open("wb") as target:
        target.write(data)
    return relative_path, original_name


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
        total = connection.execute(f"SELECT COUNT(*) FROM resources WHERE {where}", parameters).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM resources WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*parameters, limit, offset),
        ).fetchall()
    return jsonify({"resources": [serialize_resource(row) for row in rows], "total": total, "limit": limit, "offset": offset})


@app.post("/api/resources")
def upload_resource():
    file_path = correction_path = None
    try:
        values = validate_resource_form(request.form)
        correction_file = request.files.get("correction")
        if correction_file and correction_file.filename and values["category"] != "Exams":
            return api_error("Une correction PDF supplémentaire n’est acceptée que pour les examens.")
        file_path, file_name = store_pdf(request.files.get("file"), "document")
        correction_name = None
        if correction_file and correction_file.filename:
            correction_path, correction_name = store_pdf(correction_file, "correction")
        created_at = datetime.now(timezone.utc).isoformat()
        try:
            with connect_db() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO resources (
                        title, academic_level, major, category, academic_year, semester,
                        module, document_type, exam_type, file_path, file_name,
                        correction_path, correction_name, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        values["title"], values["academic_level"], values["major"], values["category"],
                        values["academic_year"], values["semester"], values["module"],
                        values["document_type"], values["exam_type"], file_path, file_name,
                        correction_path, correction_name, created_at,
                    ),
                )
                resource_id = cursor.lastrowid
        except Exception:
            if file_path:
                (UPLOAD_DIR / file_path).unlink(missing_ok=True)
            if correction_path:
                (UPLOAD_DIR / correction_path).unlink(missing_ok=True)
            raise
        return jsonify({"message": "Document reçu et en attente d’approbation par l’administrateur.", "status": "pending", "id": resource_id}), 201
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
    return jsonify({"resource": serialize_resource(row)})


def send_resource_file(resource_id, field, filename_field, as_attachment):
    row = get_resource(resource_id)
    if not row:
        abort(404)
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
            "SELECT * FROM resources" + ("" if status == "all" else " WHERE status = ?") + " ORDER BY created_at DESC",
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


@app.post("/api/admin/session")
def create_admin_session():
    if not os.environ.get("CAMPUSSHARE_ADMIN_TOKEN"):
        return api_error("L’accès administrateur n’est pas configuré.", 503)
    if not require_admin():
        return api_error("Le jeton administrateur est manquant ou invalide.", 401)
    session["admin_authenticated"] = True
    return jsonify({"authenticated": True})


@app.delete("/api/admin/session")
def destroy_admin_session():
    session.clear()
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
        result = connection.execute("UPDATE resources SET status = ? WHERE id = ?", (status, resource_id))
        if result.rowcount == 0:
            return api_error("Ressource introuvable.", 404)
    return jsonify({"id": resource_id, "status": status})


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
        file_path, file_name = store_pdf(request.files.get("correction"), "correction")
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
