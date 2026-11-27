import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "instance" / "mabiblio.sqlite3"
EXPECTED_STUDENTS = {
    1: "admin-preview@example.com",
    2: "mabibliocontactteam@gmail.com",
    3: "simowkr4@gmail.com",
}
DELETE_IDS = (1, 3)
EXPECTED_RESOURCE_COUNT = 600
CASCADE_DEPENDENCIES = {"student_access_grants", "student_activity_events"}


def quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def create_backup(database_path):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = database_path.with_name(
        f"{database_path.stem}.pre-student-cleanup-{timestamp}.bak"
    )
    with closing(sqlite3.connect(database_path)) as source, closing(
        sqlite3.connect(backup_path)
    ) as backup:
        source.backup(backup)
    with closing(sqlite3.connect(backup_path)) as backup:
        integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"Database backup integrity check failed: {integrity}")
    return backup_path


def resource_fingerprint(connection):
    digest = hashlib.sha256()
    for row in connection.execute("SELECT * FROM resources ORDER BY id"):
        digest.update(
            json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def cleanup_student_accounts(
    database_path=DEFAULT_DATABASE,
    *,
    confirm=False,
    delete_linked_account_data=False,
):
    database_path = Path(database_path).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Database not found: {database_path}")

    backup_path = create_backup(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if not {"students", "resources"}.issubset(tables):
                raise RuntimeError("Database is missing the required students or resources table.")

            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(
                    f"Database already has {len(violations)} foreign-key violation(s); no rows were changed."
                )

            students = connection.execute(
                "SELECT id, email, email_verified_at FROM students ORDER BY id"
            ).fetchall()
            actual_students = {
                row["id"]: (row["email"] or "").strip().lower()
                for row in students
            }
            expected_students = {
                student_id: email.lower()
                for student_id, email in EXPECTED_STUDENTS.items()
            }
            if actual_students != expected_students:
                raise RuntimeError(
                    "Student IDs/emails do not match the reviewed cleanup target "
                    f"(found IDs {sorted(actual_students)}); no rows were changed."
                )

            keep_account = next(row for row in students if row["id"] == 2)
            if not keep_account["email_verified_at"]:
                raise RuntimeError(
                    "The account to keep is not verified; verify it before cleanup. No rows were changed."
                )

            resource_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(resources)")
            }
            if not {"id", "owner_id", "access_grant_id"}.issubset(resource_columns):
                raise RuntimeError("Resources table is missing required ownership columns.")
            resource_count, null_owner_count = connection.execute(
                """
                SELECT COUNT(*), SUM(CASE WHEN owner_id IS NULL THEN 1 ELSE 0 END)
                FROM resources
                """
            ).fetchone()
            if resource_count != EXPECTED_RESOURCE_COUNT or null_owner_count != EXPECTED_RESOURCE_COUNT:
                raise RuntimeError(
                    "Resources do not match the expected 600 ownerless documents; no rows were changed."
                )

            dependencies = {}
            grant_ids = []
            for table in sorted(tables):
                quoted_table = quote_identifier(table)
                for foreign_key in connection.execute(
                    f"PRAGMA foreign_key_list({quoted_table})"
                ):
                    if foreign_key["table"] == "students":
                        child_column = quote_identifier(foreign_key["from"])
                        count = connection.execute(
                            f"SELECT COUNT(*) FROM {quoted_table} "
                            f"WHERE {child_column} IN (?, ?)",
                            DELETE_IDS,
                        ).fetchone()[0]
                        if count:
                            if (
                                foreign_key["on_delete"].upper() != "CASCADE"
                                or table not in CASCADE_DEPENDENCIES
                            ):
                                raise RuntimeError(
                                    f"Deletion would affect {count} dependent row(s) in {table}; "
                                    "no rows were changed."
                                )
                            dependencies[table] = dependencies.get(table, 0) + count
                    if (
                        foreign_key["table"] == "student_access_grants"
                        and "student_access_grants" in tables
                    ):
                        grants = connection.execute(
                            "SELECT id FROM student_access_grants WHERE student_id IN (?, ?)",
                            DELETE_IDS,
                        ).fetchall()
                        grant_ids = [row["id"] for row in grants]
                        if grant_ids:
                            placeholders = ", ".join("?" for _ in grant_ids)
                            child_column = quote_identifier(foreign_key["from"])
                            count = connection.execute(
                                f"SELECT COUNT(*) FROM {quoted_table} "
                                f"WHERE {child_column} IN ({placeholders})",
                                grant_ids,
                            ).fetchone()[0]
                            if count:
                                raise RuntimeError(
                                    f"Deletion would affect {count} row(s) in {table} through "
                                    "student access grants; no rows were changed."
                                )

            print(f"Verified backup: {backup_path}")
            print(f"Resources: {resource_count}; all have owner_id NULL.")
            print(
                "Account-linked rows subject to cascade: "
                + (
                    ", ".join(f"{table}={count}" for table, count in sorted(dependencies.items()))
                    if dependencies
                    else "none"
                )
            )
            if dependencies and not delete_linked_account_data:
                raise RuntimeError(
                    "Review the account-linked cascade counts, then rerun with "
                    "--delete-linked-account-data only if you authorize removing them."
                )
            if not confirm:
                raise RuntimeError(
                    "Preflight completed; no rows were changed. Rerun with --confirm to delete "
                    "student IDs 1 and 3."
                )

            original_resource_fingerprint = resource_fingerprint(connection)
            deleted = connection.execute(
                "DELETE FROM students WHERE id IN (?, ?)",
                DELETE_IDS,
            ).rowcount
            if deleted != len(DELETE_IDS):
                raise RuntimeError("Expected exactly two student rows to be deleted; transaction rolled back.")

            remaining = connection.execute(
                "SELECT id, email, email_verified_at FROM students"
            ).fetchall()
            if (
                len(remaining) != 1
                or remaining[0]["id"] != 2
                or remaining[0]["email"].strip().lower() != EXPECTED_STUDENTS[2]
                or not remaining[0]["email_verified_at"]
            ):
                raise RuntimeError("Remaining student account did not match the verified target.")
            if resource_fingerprint(connection) != original_resource_fingerprint:
                raise RuntimeError("Resource metadata changed; transaction rolled back.")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign-key check failed after cleanup; transaction rolled back.")
    finally:
        connection.close()

    print("Cleanup completed. No resource rows or uploaded files were modified.")
    print(
        "Set MABIBLIO_ADMIN_EMAIL=mabibliocontactteam@gmail.com in the app environment "
        "to grant this verified account administrator access."
    )
    return backup_path


def main():
    parser = argparse.ArgumentParser(
        description="Back up and safely remove the two reviewed MaBiblio student accounts."
    )
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        default=DEFAULT_DATABASE,
        help="SQLite database path (defaults to instance/mabiblio.sqlite3)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Authorize deletion after the backup and safety checks pass.",
    )
    parser.add_argument(
        "--delete-linked-account-data",
        action="store_true",
        help="Also authorize cascaded access-grant/activity rows for the deleted accounts.",
    )
    args = parser.parse_args()
    try:
        cleanup_student_accounts(
            args.database,
            confirm=args.confirm,
            delete_linked_account_data=args.delete_linked_account_data,
        )
    except (FileNotFoundError, RuntimeError, sqlite3.Error) as error:
        print(f"Cleanup stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
