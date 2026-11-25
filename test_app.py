import io
import os
import tempfile
import unittest
from pathlib import Path

import app as campus_app


class CampusShareApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = campus_app.DATABASE_PATH
        self.original_uploads = campus_app.UPLOAD_DIR
        self.original_admin_token = os.environ.get("CAMPUSSHARE_ADMIN_TOKEN")
        campus_app.DATABASE_PATH = Path(self.temporary_directory.name) / "test.sqlite3"
        campus_app.UPLOAD_DIR = Path(self.temporary_directory.name) / "uploads"
        campus_app.UPLOAD_DIR.mkdir()
        campus_app.initialize_db()
        campus_app.app.config.update(TESTING=True)
        self.client = campus_app.app.test_client()
        os.environ["CAMPUSSHARE_ADMIN_TOKEN"] = "test-admin-token"
        self.admin_headers = {"X-Admin-Token": "test-admin-token"}

    def tearDown(self):
        campus_app.DATABASE_PATH = self.original_database
        campus_app.UPLOAD_DIR = self.original_uploads
        if self.original_admin_token is None:
            os.environ.pop("CAMPUSSHARE_ADMIN_TOKEN", None)
        else:
            os.environ["CAMPUSSHARE_ADMIN_TOKEN"] = self.original_admin_token
        self.temporary_directory.cleanup()

    def upload_course(self):
        return self.client.post(
            "/api/resources",
            data={
                "title": "Linear algebra notes",
                "academicLevel": "Licence",
                "major": "Computer Science",
                "category": "Courses",
                "academicYear": "2025–2026",
                "semester": "S1",
                "module": "Linear Algebra",
                "documentType": "Course",
                "file": (io.BytesIO(b"%PDF-1.4\n% test document"), "notes.pdf"),
            },
            content_type="multipart/form-data",
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
        self.assertEqual(
            {major["name"] for major in response.get_json()["majors"]},
            {
                "Génie Civil",
                "Génie Digital & Intelligence Artificielle",
                "Génie Informatique",
                "LST – Mathématiques et Sciences des Données",
                "Génie Chimique, Environnement et Digitalisation",
                "Mécatronique",
                "Génie des Procédés, Techniques d'Analyse et Contrôle Qualité",
                "Sciences Biomédicales",
                "Agriculture et Développement Durable",
                "Électronique, Électrotechnique et Automatique",
                "Géophysique Appliquée, Matériaux et Ingénierie Minière",
                "Systèmes Intelligents et Objets Connectés",
                "Système d'Information et Transformation Digitale",
                "Technologie Agroalimentaire",
            },
        )

    def test_master_has_requested_default_majors(self):
        response = self.client.get("/api/majors?level=Master")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {major["name"] for major in response.get_json()["majors"]},
            {
                "Analyses et Gestion Qualité",
                "Analyses et Gestion Qualité Sécurité Hygiène Environnement",
                "Automatique, Traitement de Signal et Informatique Industrielle",
                "Bio-ingénierie",
                "Eau, Sol et Environnement Durable",
                "Génie Civil - Bâtiments, Ponts et Chaussées",
                "Ingénierie Chimique et Sciences des Matériaux",
                "Ingénierie des Réseaux Informatique et Systèmes de Télécoms Intelligents",
                "Ingénierie et Sciences des Matériaux",
                "MECATRONIQUE",
                "MST Ingénierie Logicielle et Cybersécurité",
                "Management et Qualité en Agroalimentaire dans la Grande Distribution",
                "Master Ingénierie et Management Industriel",
                "Master Mathématiques et Sciences des Données",
                "Mathématiques et Technologies Emergentes",
                "Prospection et Valorisation des Ressources Minérales",
                "Réseaux et Systèmes Informatiques",
                "Systèmes Intelligents Connectés, Réseaux Avancés et Télécoms",
            },
        )

    def test_cycle_ingenieur_has_requested_default_majors(self):
        response = self.client.get("/api/majors?level=Cycle%20Ing%C3%A9nieur")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {major["name"] for major in response.get_json()["majors"]},
            {
                "Génie Informatique",
                "Procédés et Ingénierie Chimique",
                "Ingénierie Biomédicale : Instrumentation & Maintenance",
                "Ingénierie de Conception et Productique",
                "Ingénierie des Systèmes Electriques et Systèmes Embarqués",
            },
        )

    def test_only_approved_documents_are_public_and_counts_persist(self):
        self.client.post(
            "/api/admin/majors",
            headers=self.admin_headers,
            json={"academicLevel": "Licence", "name": "Computer Science"},
        )
        upload = self.upload_course()
        self.assertEqual(upload.status_code, 201)
        resource_id = upload.get_json()["id"]
        self.assertEqual(self.client.get("/api/resources").get_json()["total"], 0)
        pending = self.client.get("/api/admin/resources?status=pending", headers=self.admin_headers)
        self.assertEqual(len(pending.get_json()["resources"]), 1)

        review = self.client.post(
            f"/api/admin/resources/{resource_id}/review",
            headers=self.admin_headers,
            json={"status": "approved"},
        )
        self.assertEqual(review.status_code, 200)
        self.assertEqual(self.client.get("/api/resources").get_json()["total"], 1)
        self.assertEqual(self.client.get(f"/api/resources/{resource_id}").get_json()["resource"]["viewerCount"], 1)
        download = self.client.get(f"/api/resources/{resource_id}/download")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(self.client.get(f"/api/resources/{resource_id}").get_json()["resource"]["downloadCount"], 1)

    def test_admin_routes_require_a_token_and_invalid_pdf_is_rejected(self):
        self.assertEqual(self.client.get("/api/admin/resources").status_code, 401)
        self.client.post(
            "/api/admin/majors",
            headers=self.admin_headers,
            json={"academicLevel": "Licence", "name": "Computer Science"},
        )
        response = self.client.post(
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
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/resources").get_json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
