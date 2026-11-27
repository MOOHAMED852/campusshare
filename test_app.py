import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter
from werkzeug.security import generate_password_hash

import app as campus_app


class MaBiblioApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = campus_app.DATABASE_PATH
        self.original_uploads = campus_app.UPLOAD_DIR
        self.original_admin_email = os.environ.get("MABIBLIO_ADMIN_EMAIL")
        self.original_admin_token = os.environ.get("MABIBLIO_ADMIN_TOKEN")
        self.original_legacy_admin_token = os.environ.get("MABIBLIO_ADMIN_TOKEN")
        self.original_public_url = os.environ.get("MABIBLIO_PUBLIC_URL")
        os.environ.pop("MABIBLIO_PUBLIC_URL", None)
        os.environ["MABIBLIO_ADMIN_EMAIL"] = "admin@example.com"
        os.environ.pop("MABIBLIO_ADMIN_TOKEN", None)
        os.environ.pop("MABIBLIO_ADMIN_TOKEN", None)
        campus_app.DATABASE_PATH = Path(self.temporary_directory.name) / "test.sqlite3"
        campus_app.UPLOAD_DIR = Path(self.temporary_directory.name) / "uploads"
        campus_app.UPLOAD_DIR.mkdir()
        campus_app.initialize_db()
        campus_app.app.config.update(TESTING=True)
        self.client = campus_app.app.test_client()
        self.admin_client = campus_app.app.test_client()
        with campus_app.connect_db() as connection:
            connection.execute(
                "INSERT INTO majors (academic_level, name) VALUES (?, ?)",
                ("Licence", "Computer Science"),
            )
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO students (email, password_hash, email_verified_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "admin@example.com",
                    generate_password_hash("secure-student-password"),
                    now,
                    now,
                ),
            )
        admin_login = self.admin_client.post(
            "/api/student/session",
            json={"email": "admin@example.com", "password": "secure-student-password"},
        )
        self.assertEqual(admin_login.status_code, 200)

    def tearDown(self):
        campus_app.DATABASE_PATH = self.original_database
        campus_app.UPLOAD_DIR = self.original_uploads
        if self.original_admin_email is None:
            os.environ.pop("MABIBLIO_ADMIN_EMAIL", None)
        else:
            os.environ["MABIBLIO_ADMIN_EMAIL"] = self.original_admin_email
        if self.original_admin_token is None:
            os.environ.pop("MABIBLIO_ADMIN_TOKEN", None)
        else:
            os.environ["MABIBLIO_ADMIN_TOKEN"] = self.original_admin_token
        if self.original_legacy_admin_token is None:
            os.environ.pop("MABIBLIO_ADMIN_TOKEN", None)
        else:
            os.environ["MABIBLIO_ADMIN_TOKEN"] = self.original_legacy_admin_token
        if self.original_public_url is None:
            os.environ.pop("MABIBLIO_PUBLIC_URL", None)
        else:
            os.environ["MABIBLIO_PUBLIC_URL"] = self.original_public_url
        self.temporary_directory.cleanup()

    @staticmethod
    def make_pdf(width=72, page_count=1):
        writer = PdfWriter()
        for index in range(page_count):
            writer.add_blank_page(width=width + index, height=72)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def create_verified_student(self, email="student@example.com"):
        now = datetime.now(timezone.utc).isoformat()
        with campus_app.connect_db() as connection:
            cursor = connection.execute(
                """
                INSERT INTO students (email, password_hash, email_verified_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email, generate_password_hash("secure-student-password"), now, now),
            )
            student_id = cursor.lastrowid
        response = self.client.post(
            "/api/student/session",
            json={"email": email, "password": "secure-student-password"},
        )
        self.assertEqual(response.status_code, 200)
        return student_id

    def upload_course(self, filename="notes.pdf", pdf_data=None, title="Linear algebra notes"):
        return self.client.post(
            "/api/resources",
            data={
                "title": title,
                "academicLevel": "Licence",
                "major": "Computer Science",
                "category": "Courses",
                "academicYear": "2025–2026",
                "semester": "S1",
                "module": "Linear Algebra",
                "documentType": "Course",
                "file": (io.BytesIO(pdf_data or self.make_pdf(width=72 + sum(filename.encode()) % 1000)), filename),
            },
            content_type="multipart/form-data",
        )

    def approve(self, resource_id):
        return self.admin_client.post(
            f"/api/admin/resources/{resource_id}/review",
            json={"status": "approved"},
        )

    def test_tronc_commun_has_default_majors(self):
        response = self.client.get("/api/majors?level=Tronc%20Commun")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {major["name"] for major in response.get_json()["majors"]},
            {
                "Génie Informatique",
                "Génie Chimique",
                "Mathématiques et Sciences des Données",
                "Génie Électrique et Systèmes Embarqués",
                "Génie Mécanique et Systèmes Industriels",
                "Génie Biologie",
            },
        )

    def test_licence_has_requested_default_majors(self):
        response = self.client.get("/api/majors?level=Licence")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Génie Informatique", {major["name"] for major in response.get_json()["majors"]})

    def test_master_has_requested_default_majors(self):
        response = self.client.get("/api/majors?level=Master")

        self.assertEqual(response.status_code, 200)
        self.assertIn("MST Ingénierie Logicielle et Cybersécurité", {
            major["name"] for major in response.get_json()["majors"]
        })

    def test_cycle_ingenieur_has_requested_default_majors(self):
        response = self.client.get("/api/majors?level=Cycle%20Ing%C3%A9nieur")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Génie Informatique", {major["name"] for major in response.get_json()["majors"]})

    def test_public_base_url_uses_localhost_when_running_locally(self):
        with campus_app.app.test_request_context("/", base_url="http://127.0.0.1:8000"):
            self.assertEqual(
                campus_app.get_public_base_url(),
                "http://127.0.0.1:8000",
            )

    def test_public_base_url_uses_pythonanywhere_by_default(self):
        with campus_app.app.test_request_context("/", base_url="https://mabiblio.pythonanywhere.com"):
            self.assertEqual(
                campus_app.get_public_base_url(),
                "https://mabiblio.pythonanywhere.com",
            )

    def test_public_base_url_honors_explicit_environment_override(self):
        os.environ["MABIBLIO_PUBLIC_URL"] = "https://custom.example/"
        with campus_app.app.test_request_context("/", base_url="https://mabiblio.pythonanywhere.com"):
            self.assertEqual(
                campus_app.get_public_base_url(),
                "https://custom.example",
            )

    def test_verification_email_uses_configured_smtp_with_starttls(self):
        smtp = MagicMock()
        smtp_context = MagicMock()
        smtp_context.__enter__.return_value = smtp
        environment = {
            "MABIBLIO_SMTP_HOST": "smtp.gmail.com",
            "MABIBLIO_SMTP_PORT": "587",
            "MABIBLIO_SMTP_USERNAME": "smtp-user@example.com",
            "MABIBLIO_SMTP_PASSWORD": "fake-smtp-app-password",
            "MABIBLIO_FROM_EMAIL": "smtp-user@example.com",
            "MABIBLIO_PUBLIC_URL": "https://mabiblio.pythonanywhere.com",
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(campus_app.smtplib, "SMTP", return_value=smtp_context) as smtp_factory:
                campus_app.send_student_verification_email("student@example.com", "verification-token")

        smtp_factory.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
        smtp.starttls.assert_called_once_with()
        smtp.login.assert_called_once_with("smtp-user@example.com", "fake-smtp-app-password")
        smtp.send_message.assert_called_once()
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "student@example.com")
        self.assertIn(
            "https://mabiblio.pythonanywhere.com/api/student/verify?token=verification-token",
            message.get_content(),
        )

    def test_verification_email_logs_auth_failure_without_credentials(self):
        smtp = MagicMock()
        smtp.login.side_effect = campus_app.smtplib.SMTPAuthenticationError(
            535,
            b"5.7.8 Authentication Credentials Invalid",
        )
        smtp_context = MagicMock()
        smtp_context.__enter__.return_value = smtp
        environment = {
            "MABIBLIO_SMTP_HOST": "smtp.gmail.com",
            "MABIBLIO_SMTP_PORT": "587",
            "MABIBLIO_SMTP_USERNAME": "private-smtp-user@example.com",
            "MABIBLIO_SMTP_PASSWORD": "private-smtp-password",
            "MABIBLIO_FROM_EMAIL": "sender@example.com",
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(campus_app.smtplib, "SMTP", return_value=smtp_context):
                with self.assertLogs(campus_app.app.logger, level="ERROR") as captured:
                    with self.assertRaises(RuntimeError) as raised:
                        campus_app.send_student_verification_email("student@example.com", "token")

        self.assertEqual(
            str(raised.exception),
            "Impossible d’envoyer l’e-mail de vérification. Vérifiez la configuration SMTP.",
        )
        self.assertIn("SMTPAuthenticationError", captured.output[0])
        self.assertIn("535", captured.output[0])
        self.assertNotIn("private-smtp-user@example.com", captured.output[0])
        self.assertNotIn("private-smtp-password", captured.output[0])
        smtp.send_message.assert_not_called()

    def test_registration_requires_email_verification_before_login(self):
        invalid_username = self.client.post(
            "/api/student/register",
            json={"username": "ab", "email": "new@example.com", "password": "secure-student-password"},
        )
        self.assertEqual(invalid_username.status_code, 400)
        with patch.dict(os.environ, {
            "MABIBLIO_SMTP_HOST": "smtp.example.test",
            "MABIBLIO_FROM_EMAIL": "noreply@example.test",
        }):
            with patch.object(campus_app, "send_student_verification_email") as send_email:
                response = self.client.post(
                    "/api/student/register",
                    json={
                        "username": "newstudent",
                        "email": "new@example.com",
                        "password": "secure-student-password",
                    },
                )
        self.assertEqual(response.status_code, 202)
        token = send_email.call_args.args[1]
        before_verification = self.client.post(
            "/api/student/session",
            json={"email": "new@example.com", "password": "secure-student-password"},
        )
        self.assertEqual(before_verification.status_code, 403)

        verified = self.client.get(f"/api/student/verify?token={token}")
        self.assertIn("emailVerified=1", verified.location)
        login = self.client.post(
            "/api/student/session",
            json={"identifier": "newstudent", "password": "secure-student-password"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.get_json()["authenticated"])
        self.assertEqual(login.get_json()["username"], "newstudent")
        with patch.dict(os.environ, {
            "MABIBLIO_SMTP_HOST": "smtp.example.test",
            "MABIBLIO_FROM_EMAIL": "noreply@example.test",
        }):
            duplicate_username = self.client.post(
                "/api/student/register",
                json={
                    "username": "NEWSTUDENT",
                    "email": "another@example.com",
                    "password": "secure-student-password",
                },
            )
        self.assertEqual(duplicate_username.status_code, 409)

    def test_three_approved_unique_pdfs_unlock_student_downloads(self):
        self.create_verified_student()
        ids = []
        for index in range(3):
            upload = self.upload_course(filename=f"notes-{index}.pdf", title=f"Notes {index}")
            self.assertEqual(upload.status_code, 201)
            resource_id = upload.get_json()["id"]
            ids.append(resource_id)
            self.assertEqual(self.client.get("/api/resources").get_json()["total"], index)
            review = self.approve(resource_id)
            self.assertEqual(review.status_code, 200)

        account = self.client.get("/api/student/account").get_json()
        self.assertTrue(account["canDownloadStudentContributions"])
        self.assertEqual(account["approvedForNextAccess"], 0)
        self.assertEqual(account["remainingContributions"], 3)
        expires = datetime.fromisoformat(account["accessUntil"])
        self.assertGreater(expires, datetime.now(timezone.utc) + timedelta(days=2, hours=23))
        preview = self.client.get(f"/api/resources/{ids[0]}/preview")
        self.assertEqual(preview.status_code, 200)
        preview.close()
        download = self.client.get(f"/api/resources/{ids[0]}/download")
        self.assertEqual(download.status_code, 200)
        download.close()

    def test_student_documents_are_locked_until_access_is_granted(self):
        self.create_verified_student()
        upload = self.upload_course()
        resource_id = upload.get_json()["id"]
        self.assertEqual(self.approve(resource_id).status_code, 200)
        self.assertTrue(self.client.get(f"/api/resources/{resource_id}").get_json()["resource"]["downloadLocked"])
        self.client.delete("/api/student/session")
        self.assertEqual(self.client.get(f"/api/resources/{resource_id}/preview").status_code, 401)
        self.assertEqual(self.client.get(f"/api/resources/{resource_id}/download").status_code, 401)
        self.client.post(
            "/api/student/session",
            json={"email": "student@example.com", "password": "secure-student-password"},
        )
        self.assertEqual(self.client.get(f"/api/resources/{resource_id}/preview").status_code, 403)
        self.assertEqual(self.client.get(f"/api/resources/{resource_id}/download").status_code, 403)

    def test_duplicate_pdf_hash_or_name_and_page_count_is_rejected(self):
        self.create_verified_student()
        first = self.upload_course(filename="same-name.pdf", pdf_data=self.make_pdf(width=72))
        self.assertEqual(first.status_code, 201)
        exact_duplicate = self.upload_course(filename="renamed-copy.pdf", pdf_data=self.make_pdf(width=72))
        self.assertEqual(exact_duplicate.status_code, 409)
        same_name_and_pages = self.upload_course(filename="same-name.pdf", pdf_data=self.make_pdf(width=90))
        self.assertEqual(same_name_and_pages.status_code, 409)
        self.assertEqual(len(self.admin_client.get("/api/admin/resources?status=pending").get_json()["resources"]), 1)

    def test_expired_access_can_be_renewed_with_three_new_approved_pdfs(self):
        student_id = self.create_verified_student()
        first_ids = []
        for index in range(3):
            upload = self.upload_course(filename=f"initial-{index}.pdf", title=f"Initial {index}")
            first_ids.append(upload.get_json()["id"])
            self.assertEqual(self.approve(first_ids[-1]).status_code, 200)

        with campus_app.connect_db() as connection:
            connection.execute(
                "UPDATE student_access_grants SET expires_at = ? WHERE student_id = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), student_id),
            )
        expired = self.client.get("/api/student/account").get_json()
        self.assertFalse(expired["canDownloadStudentContributions"])
        self.assertEqual(self.client.get(f"/api/resources/{first_ids[0]}/download").status_code, 403)

        for index in range(3):
            upload = self.upload_course(filename=f"renewal-{index}.pdf", title=f"Renewal {index}")
            self.assertEqual(upload.status_code, 201)
            review = self.approve(upload.get_json()["id"])
            self.assertEqual(review.status_code, 200)
        renewed = self.client.get("/api/student/account").get_json()
        self.assertTrue(renewed["canDownloadStudentContributions"])
        self.assertGreater(
            datetime.fromisoformat(renewed["accessUntil"]),
            datetime.now(timezone.utc) + timedelta(days=2, hours=23),
        )

    def test_admin_published_pdfs_are_immediately_public_and_ungated(self):
        self.create_verified_student()
        response = self.admin_client.post(
            "/api/admin/resources",
            data={
                "title": "Official course notes",
                "academicLevel": "Licence",
                "major": "Computer Science",
                "category": "Courses",
                "academicYear": "2025–2026",
                "semester": "S1",
                "module": "Linear Algebra",
                "documentType": "Course",
                "file": (io.BytesIO(self.make_pdf()), "official.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        resource_id = response.get_json()["id"]
        public = self.client.get(f"/api/resources/{resource_id}").get_json()["resource"]
        self.assertFalse(public["downloadLocked"])
        self.assertFalse(public["requiresSignIn"])
        preview = self.client.get(f"/api/resources/{resource_id}/preview")
        self.assertEqual(preview.status_code, 200)
        preview.close()
        download = self.client.get(f"/api/resources/{resource_id}/download")
        self.assertEqual(download.status_code, 200)
        download.close()
        self.client.delete("/api/student/session")
        anonymous = self.client.get(f"/api/resources/{resource_id}").get_json()["resource"]
        self.assertTrue(anonymous["requiresSignIn"])
        public_preview = self.client.get(f"/api/resources/{resource_id}/preview")
        self.assertEqual(public_preview.status_code, 200)
        public_preview.close()
        self.assertEqual(self.client.get(f"/api/resources/{resource_id}/download").status_code, 401)

    def test_student_activity_and_download_history_are_admin_only(self):
        student_id = self.create_verified_student()
        self.assertEqual(self.client.get("/api/admin/students").status_code, 401)
        self.assertEqual(
            self.client.post("/api/student/activity").status_code,
            200,
        )

        with campus_app.connect_db() as connection:
            previous_ping = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
            connection.execute(
                "UPDATE students SET last_activity_ping_at = ? WHERE id = ?",
                (previous_ping, student_id),
            )
        heartbeat = self.client.post("/api/student/activity")
        self.assertEqual(heartbeat.status_code, 200)
        self.assertGreaterEqual(heartbeat.get_json()["activeSeconds"], 59)

        published = self.admin_client.post(
            "/api/admin/resources",
            data={
                "title": "Official activity notes",
                "academicLevel": "Licence",
                "major": "Computer Science",
                "category": "Courses",
                "academicYear": "2025–2026",
                "semester": "S1",
                "module": "Linear Algebra",
                "documentType": "Course",
                "file": (io.BytesIO(self.make_pdf()), "activity-notes.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(published.status_code, 201)
        resource_id = published.get_json()["id"]
        download = self.client.get(f"/api/resources/{resource_id}/download")
        self.assertEqual(download.status_code, 200)
        download.close()

        students = self.admin_client.get("/api/admin/students")
        self.assertEqual(students.status_code, 200)
        student = students.get_json()["students"][0]
        self.assertEqual(student["email"], "student@example.com")
        self.assertTrue(student["emailVerified"])
        self.assertTrue(student["online"])
        self.assertEqual(student["downloadCount"], 1)
        self.assertNotIn("password_hash", student)
        self.assertNotIn("password", student)

        activity = self.admin_client.get(f"/api/admin/students/{student_id}/activity")
        self.assertEqual(activity.status_code, 200)
        event_types = [event["eventType"] for event in activity.get_json()["events"]]
        self.assertEqual(event_types[:2], ["download", "sign_in"])
        self.assertNotIn("password_hash", activity.get_json()["student"])

        self.assertEqual(self.client.delete("/api/student/session").status_code, 200)
        signed_out = self.admin_client.get("/api/admin/students").get_json()["students"][0]
        self.assertFalse(signed_out["online"])

    def test_admin_routes_require_the_configured_verified_student_account(self):
        self.assertEqual(self.client.get("/api/admin/resources").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/students").status_code, 401)
        self.assertEqual(
            self.client.get("/api/admin/resources", headers={"X-Admin-Token": "test-admin-token"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/api/admin/resources", headers={"X-Admin-Token": "test-admin-token"}).status_code,
            401,
        )
        self.create_verified_student()
        protected_requests = (
            ("GET", "/api/admin/resources"),
            ("POST", "/api/admin/resources"),
            ("GET", "/api/admin/students"),
            ("GET", "/api/admin/students/1/activity"),
            ("GET", "/api/admin/resources/1/preview"),
            ("GET", "/api/admin/resources/1/correction/preview"),
            ("POST", "/api/admin/resources/1/review"),
            ("POST", "/api/admin/resources/1/correction"),
            ("DELETE", "/api/admin/resources/1"),
            ("POST", "/api/admin/majors"),
            ("POST", "/api/admin/academic-years"),
        )
        for method, path in protected_requests:
            response = self.client.open(path, method=method)
            self.assertEqual(response.status_code, 401, f"{method} {path} should require administrator access")

        invalid = self.client.post(
            "/api/resources",
            data={
                "title": "Not a PDF",
                "academicLevel": "Licence",
                "major": "Computer Science",
                "category": "Courses",
                "academicYear": "2025–2026",
                "semester": "S1",
                "module": "Linear Algebra",
                "documentType": "Course",
                "file": (io.BytesIO(b"not a pdf"), "notes.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.get("/api/resources").get_json()["total"], 0)

    def test_administration_roles_are_server_side_and_contact_email_does_not_grant_admin(self):
        with patch.dict(os.environ, {"MABIBLIO_CONTACT_EMAIL": "contact@example.com"}):
            public_info = self.client.get("/api/admin/public-info")
        self.assertEqual(public_info.status_code, 200)
        self.assertEqual(public_info.get_json()["contactEmail"], "contact@example.com")

        self.create_verified_student(email="contact@example.com")
        self.assertEqual(self.client.get("/api/admin/session").get_json()["role"], None)
        self.assertEqual(self.client.get("/api/admin/resources").status_code, 401)
        self.assertEqual(self.client.post("/api/admin/session").status_code, 405)
        self.assertEqual(self.admin_client.get("/api/admin/session").get_json()["role"], "administrator")
        self.assertEqual(self.admin_client.get("/api/admin/resources").status_code, 200)
        with patch.dict(os.environ, {"MABIBLIO_ADMIN_EMAIL": "other@example.com"}):
            self.assertEqual(self.admin_client.get("/api/admin/resources").status_code, 401)

        admin_logout = self.admin_client.delete("/api/admin/session")
        self.assertEqual(admin_logout.status_code, 200)
        self.assertFalse(self.admin_client.get("/api/admin/session").get_json()["authenticated"])
        self.assertEqual(self.admin_client.get("/api/student/account").status_code, 200)

    def test_unverified_configured_admin_account_cannot_access_admin_routes(self):
        now = datetime.now(timezone.utc).isoformat()
        with campus_app.connect_db() as connection:
            connection.execute(
                """
                INSERT INTO students (email, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                ("unverified-admin@example.com", generate_password_hash("secure-student-password"), now),
            )
        with patch.dict(os.environ, {"MABIBLIO_ADMIN_EMAIL": "unverified-admin@example.com"}):
            login = self.client.post(
                "/api/student/session",
                json={
                    "email": "unverified-admin@example.com",
                    "password": "secure-student-password",
                },
            )
            self.assertEqual(login.status_code, 403)
            self.assertEqual(self.client.get("/api/admin/resources").status_code, 401)

    def test_admin_logout_then_different_student_login_clears_all_privileges(self):
        self.assertEqual(self.admin_client.get("/api/admin/session").get_json()["role"], "administrator")
        self.assertEqual(self.admin_client.delete("/api/student/session").status_code, 200)
        self.assertEqual(self.admin_client.get("/api/admin/resources").status_code, 401)

        self.create_verified_student(email="another-student@example.com")
        login = self.admin_client.post(
            "/api/student/session",
            json={
                "email": "another-student@example.com",
                "password": "secure-student-password",
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.admin_client.get("/api/admin/session").get_json()["role"], None)
        self.assertEqual(self.admin_client.get("/api/admin/resources").status_code, 401)


if __name__ == "__main__":
    unittest.main()
