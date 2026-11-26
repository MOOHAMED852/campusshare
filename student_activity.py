from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, session


ACTIVITY_RETENTION = timedelta(days=180)
ONLINE_WINDOW = timedelta(minutes=2)
MAX_HEARTBEAT_GAP_SECONDS = 90
MIN_HEARTBEAT_GAP_SECONDS = 30


def initialize_student_activity_schema(connection):
    student_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(students)").fetchall()
    }
    student_migrations = {
        "last_seen_at": "TEXT",
        "last_activity_ping_at": "TEXT",
        "active_seconds": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in student_migrations.items():
        if column not in student_columns:
            connection.execute(f"ALTER TABLE students ADD COLUMN {column} {definition}")

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS student_activity_events (
            id INTEGER PRIMARY KEY,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL CHECK (
                event_type IN ('sign_in', 'sign_out', 'download', 'correction_download')
            ),
            resource_title TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS student_activity_events_student_created
            ON student_activity_events (student_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS student_activity_events_created
            ON student_activity_events (created_at);
        """
    )
    prune_activity_events(connection)


def prune_activity_events(connection, now=None):
    cutoff = (now or datetime.now(timezone.utc)) - ACTIVITY_RETENTION
    connection.execute(
        "DELETE FROM student_activity_events WHERE created_at < ?",
        (cutoff.isoformat(),),
    )


def record_student_activity(connection, student_id, event_type, resource_title=None):
    created_at = datetime.now(timezone.utc)
    connection.execute(
        """
        INSERT INTO student_activity_events (student_id, event_type, resource_title, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (student_id, event_type, resource_title, created_at.isoformat()),
    )
    connection.execute(
        "UPDATE students SET last_seen_at = ? WHERE id = ?",
        (created_at.isoformat(), student_id),
    )
    prune_activity_events(connection, created_at)


def _is_online(last_seen_at, last_event_type, now):
    if not last_seen_at or last_event_type == "sign_out":
        return False
    last_seen = datetime.fromisoformat(last_seen_at)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    elapsed = now - last_seen
    return timedelta(0) <= elapsed <= ONLINE_WINDOW


def create_student_activity_blueprint(connect_db, require_admin_response, student_session_id):
    blueprint = Blueprint("student_activity", __name__)

    @blueprint.post("/api/student/activity")
    def update_student_activity():
        student_id = student_session_id()
        if student_id is None:
            return jsonify({"error": "Connectez-vous pour enregistrer votre activité."}), 401

        now = datetime.now(timezone.utc)
        with connect_db() as connection:
            student = connection.execute(
                """
                SELECT email_verified_at, last_activity_ping_at, active_seconds
                FROM students WHERE id = ?
                """,
                (student_id,),
            ).fetchone()
            if not student or not student["email_verified_at"]:
                session.pop("student_id", None)
                return jsonify({"error": "La session étudiante n’est plus valide."}), 401

            elapsed_seconds = 0
            last_ping_at = student["last_activity_ping_at"]
            if last_ping_at:
                previous_ping = datetime.fromisoformat(last_ping_at)
                if previous_ping.tzinfo is None:
                    previous_ping = previous_ping.replace(tzinfo=timezone.utc)
                elapsed = (now - previous_ping).total_seconds()
                if MIN_HEARTBEAT_GAP_SECONDS <= elapsed <= MAX_HEARTBEAT_GAP_SECONDS:
                    elapsed_seconds = round(elapsed)

            connection.execute(
                """
                UPDATE students
                SET last_seen_at = ?, last_activity_ping_at = ?,
                    active_seconds = active_seconds + ?
                WHERE id = ?
                """,
                (now.isoformat(), now.isoformat(), elapsed_seconds, student_id),
            )
            prune_activity_events(connection, now)
            active_seconds = student["active_seconds"] + elapsed_seconds

        return jsonify({"activeSeconds": active_seconds})

    @blueprint.get("/api/admin/students")
    def list_student_activity():
        error = require_admin_response()
        if error:
            return error

        now = datetime.now(timezone.utc)
        with connect_db() as connection:
            prune_activity_events(connection, now)
            rows = connection.execute(
                """
                SELECT students.id, students.username, students.email,
                       students.email_verified_at, students.created_at,
                       students.last_seen_at, students.active_seconds,
                       (
                           SELECT event_type FROM student_activity_events
                           WHERE student_id = students.id
                           ORDER BY id DESC LIMIT 1
                       ) AS last_event_type,
                       (
                           SELECT MAX(created_at) FROM student_activity_events
                           WHERE student_id = students.id AND event_type = 'sign_in'
                       ) AS last_sign_in_at,
                       (
                           SELECT COUNT(*) FROM student_activity_events
                           WHERE student_id = students.id
                             AND event_type IN ('download', 'correction_download')
                       ) AS download_count
                FROM students
                ORDER BY students.created_at DESC, students.id DESC
                """
            ).fetchall()

        return jsonify({
            "students": [
                {
                    "id": row["id"],
                    "username": row["username"],
                    "email": row["email"],
                    "emailVerified": row["email_verified_at"] is not None,
                    "createdAt": row["created_at"],
                    "lastSeenAt": row["last_seen_at"],
                    "lastSignInAt": row["last_sign_in_at"],
                    "activeSeconds": row["active_seconds"],
                    "downloadCount": row["download_count"],
                    "online": _is_online(row["last_seen_at"], row["last_event_type"], now),
                }
                for row in rows
            ],
        })

    @blueprint.get("/api/admin/students/<int:student_id>/activity")
    def get_student_activity(student_id):
        error = require_admin_response()
        if error:
            return error

        with connect_db() as connection:
            prune_activity_events(connection)
            student = connection.execute(
                """
                SELECT id, username, email, email_verified_at, created_at,
                       last_seen_at, active_seconds
                FROM students WHERE id = ?
                """,
                (student_id,),
            ).fetchone()
            if not student:
                return jsonify({"error": "Compte étudiant introuvable."}), 404
            events = connection.execute(
                """
                SELECT event_type, resource_title, created_at
                FROM student_activity_events
                WHERE student_id = ?
                ORDER BY id DESC LIMIT 100
                """,
                (student_id,),
            ).fetchall()

        return jsonify({
            "student": {
                "id": student["id"],
                "username": student["username"],
                "email": student["email"],
                "emailVerified": student["email_verified_at"] is not None,
                "createdAt": student["created_at"],
                "lastSeenAt": student["last_seen_at"],
                "activeSeconds": student["active_seconds"],
            },
            "events": [
                {
                    "eventType": event["event_type"],
                    "resourceTitle": event["resource_title"],
                    "createdAt": event["created_at"],
                }
                for event in events
            ],
        })

    return blueprint
