"""
Bulk upload script for MaBiblio.
Uploads Chapitre_1.pdf through Chapitre_5.pdf (+ Chapitre_2+.pdf, Chapitre_3.PDF)
to Tronc Commun, all majors, module "Analyse 1".

BEFORE RUNNING:
1. Start the Flask server: .\.venv\Scripts\python.exe app.py
2. Edit the CONFIG section below with your student credentials and settings.
3. Run: .\.venv\Scripts\python.exe bulk_upload_analyse1.py
"""

import io
import os
import sys
from pathlib import Path

# Add project folder to path so we can import app
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as campus_app

# =============================================================================
# CONFIG — Edit these values before running
# =============================================================================

STUDENT_EMAIL = "your-email@example.com"   # your verified student email
STUDENT_PASSWORD = "your-password"         # your student password

PDF_FOLDER = Path(r"c:\Users\pc\Desktop\simoDV")

# The PDF files to upload (in the order you want them)
PDF_FILES = [
    "Chapitre_1.pdf",
    "Chapitre_2.pdf",
    "Chapitre_2+.pdf",
    "Chapitre_3.PDF",
    "Chapitre_4.pdf",
    "Chapitre_5.pdf",
]

ACADEMIC_LEVEL = "Tronc Commun"
ACADEMIC_YEAR = "2025–2026"   # must match an active academic year in the DB
SEMESTER = "S1"
CATEGORY = "Courses"           # "Exams", "Courses", or "TD & TP"
DOCUMENT_TYPE = "Course"       # must match DOCUMENT_TYPES[category]
EXAM_TYPE = None               # only used if category == "Exams"

# All Tronc Commun majors (from app.py defaults)
MAJORS = [
    "Génie Informatique",
    "Génie Chimique",
    "Mathématiques et Sciences des Données",
    "Génie Électrique et Systèmes Embarqués",
    "Génie Mécanique et Systèmes Industriels",
    "Génie Biologie",
]

# Module name for all uploads
MODULE = "Analyse 1"

# =============================================================================
# END CONFIG
# =============================================================================


def main():
    campus_app.app.config.update(TESTING=True)
    client = campus_app.app.test_client()

    # --- Sign in -----------------------------------------------------------
    login = client.post(
        "/api/student/session",
        json={"email": STUDENT_EMAIL, "password": STUDENT_PASSWORD},
    )
    if login.status_code != 200:
        print(f"Login failed ({login.status_code}): {login.get_json()}")
        print("Make sure the account is verified and the credentials are correct.")
        return 1
    print(f"Signed in as {STUDENT_EMAIL}")

    uploaded = 0
    failed = 0

    for pdf_name in PDF_FILES:
        pdf_path = PDF_FOLDER / pdf_name
        if not pdf_path.is_file():
            print(f"SKIP (not found): {pdf_path}")
            failed += 1
            continue

        pdf_bytes = pdf_path.read_bytes()
        if not pdf_bytes.startswith(b"%PDF-"):
            print(f"SKIP (not a valid PDF): {pdf_name}")
            failed += 1
            continue

        title = f"{MODULE} – {Path(pdf_name).stem}"

        for major in MAJORS:
            data = {
                "title": title,
                "academicLevel": ACADEMIC_LEVEL,
                "major": major,
                "category": CATEGORY,
                "academicYear": ACADEMIC_YEAR,
                "semester": SEMESTER,
                "module": MODULE,
                "documentType": DOCUMENT_TYPE,
            }
            if EXAM_TYPE:
                data["examType"] = EXAM_TYPE

            files = {
                "file": (io.BytesIO(pdf_bytes), pdf_name, "application/pdf"),
            }

            resp = client.post(
                "/api/resources",
                data={**data, "file": (io.BytesIO(pdf_bytes), pdf_name)},
                content_type="multipart/form-data",
            )

            if resp.status_code == 201:
                uploaded += 1
                print(f"OK: {pdf_name} → {major}")
            elif resp.status_code == 409:
                print(f"DUPLICATE (skipped): {pdf_name} → {major}")
                failed += 1
            else:
                print(f"FAIL ({resp.status_code}): {pdf_name} → {major}")
                print(f"  {resp.get_json()}")
                failed += 1

    print(f"\nDone. Uploaded: {uploaded}, Failed/Skipped: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())