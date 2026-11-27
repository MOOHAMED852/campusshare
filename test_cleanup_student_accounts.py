import contextlib
import io
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from cleanup_student_accounts import cleanup_student_accounts


EXPECTED_STUDENTS = (
    (1, "admin-preview@example.com", "2026-01-01T00:00:00+00:00"),
    (2, "mabibliocontactteam@gmail.com", "2026-01-01T00:00:00+00:00"),
    (3, "simowkr4@gmail.com", "2026-01-01T00:00:00+00:00"),
)


@contextmanager
def database_connection(database_path):
    connection = sqlite3.connect(database_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class StudentAccountCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database_path = self.root / "mabiblio.sqlite3"
        self.uploads = self.root / "uploads"
        self.uploads.mkdir()
        self.upload_path = self.uploads / "document.pdf"
        self.upload_path.write_bytes(b"preserved document bytes")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_database(self, *, events=False, grant_reference=False, students=EXPECTED_STUDENTS):
        with database_connection(self.database_path) as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE students (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL,
                    email_verified_at TEXT
                );
                CREATE TABLE student_access_grants (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE
                );
                CREATE TABLE student_activity_events (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE
                );
                CREATE TABLE resources (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    owner_id INTEGER REFERENCES students(id),
                    access_grant_id INTEGER REFERENCES student_access_grants(id),
                    metadata TEXT NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT INTO students (id, email, email_verified_at) VALUES (?, ?, ?)",
                students,
            )
            if events:
                connection.executemany(
                    "INSERT INTO student_activity_events (student_id) VALUES (?)",
                    [(1,), (1,), (3,)],
                )
            if grant_reference:
                connection.execute(
                    "INSERT INTO student_access_grants (id, student_id) VALUES (10, 1)"
                )
            connection.executemany(
                """
                INSERT INTO resources (id, title, file_path, owner_id, access_grant_id, metadata)
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                [
                    (
                        resource_id,
                        f"Document {resource_id}",
                        "document.pdf",
                        10 if grant_reference and resource_id == 1 else None,
                        f"metadata-{resource_id}",
                    )
                    for resource_id in range(1, 601)
                ],
            )

    def test_cleanup_preserves_all_resources_and_uploaded_file(self):
        self.create_database()
        with database_connection(self.database_path) as connection:
            original_resources = connection.execute(
                "SELECT * FROM resources ORDER BY id"
            ).fetchall()
        original_file = self.upload_path.read_bytes()

        with contextlib.redirect_stdout(io.StringIO()):
            backup_path = cleanup_student_accounts(self.database_path, confirm=True)

        with database_connection(self.database_path) as connection:
            students = connection.execute("SELECT id, email FROM students").fetchall()
            resources = connection.execute("SELECT * FROM resources ORDER BY id").fetchall()
            self.assertEqual(students, [(2, "mabibliocontactteam@gmail.com")])
            self.assertEqual(resources, original_resources)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.upload_path.read_bytes(), original_file)
        self.assertTrue(backup_path.is_file())
        with database_connection(backup_path) as backup:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM students").fetchone()[0], 3)

    def test_cleanup_requires_explicit_approval_for_cascaded_account_data(self):
        self.create_database(events=True)

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "--delete-linked-account-data"):
                cleanup_student_accounts(self.database_path, confirm=True)

        with database_connection(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM students").fetchone()[0], 3)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM student_activity_events").fetchone()[0],
                3,
            )

        with contextlib.redirect_stdout(io.StringIO()):
            cleanup_student_accounts(
                self.database_path,
                confirm=True,
                delete_linked_account_data=True,
            )
        with database_connection(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM students").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM student_activity_events").fetchone()[0],
                0,
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0], 600)

    def test_cleanup_refuses_if_account_grants_are_referenced_by_resources(self):
        self.create_database(grant_reference=True)

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "through student access grants"):
                cleanup_student_accounts(
                    self.database_path,
                    confirm=True,
                    delete_linked_account_data=True,
                )

        with database_connection(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM students").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0], 600)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM resources WHERE access_grant_id = 10").fetchone()[0],
                1,
            )

    def test_cleanup_refuses_if_account_ids_or_emails_do_not_match(self):
        mismatched_account = (
            EXPECTED_STUDENTS[0],
            EXPECTED_STUDENTS[1],
            (3, "unexpected@example.com", EXPECTED_STUDENTS[2][2]),
        )
        self.create_database(students=mismatched_account)

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "IDs/emails do not match"):
                cleanup_student_accounts(self.database_path, confirm=True)

        with database_connection(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM students").fetchone()[0], 3)
        self.assertEqual(len(list(self.root.glob("*.bak"))), 1)

    def test_cleanup_refuses_if_account_to_keep_is_unverified(self):
        wrong_account = (
            EXPECTED_STUDENTS[0],
            (2, "mabibliocontactteam@gmail.com", None),
            EXPECTED_STUDENTS[2],
        )
        self.create_database(students=wrong_account)

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "account to keep is not verified"):
                cleanup_student_accounts(self.database_path, confirm=True)

        with database_connection(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM students").fetchone()[0], 3)
        self.assertEqual(len(list(self.root.glob("*.bak"))), 1)


if __name__ == "__main__":
    unittest.main()
