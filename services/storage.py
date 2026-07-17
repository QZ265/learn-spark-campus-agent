import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class AppStorage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS profile_fields (
                    user_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (user_id, field)
                );
                CREATE TABLE IF NOT EXISTS profile_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    old_record_json TEXT,
                    new_record_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS course_profile_fields (
                    user_id TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (user_id, course_id, field)
                );
                CREATE TABLE IF NOT EXISTS course_profile_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    old_record_json TEXT,
                    new_record_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    profile_basis_json TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    claims_json TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    agent_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resources_user_created
                ON resources(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS courses (
                    course_id TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL UNIQUE,
                    domain TEXT NOT NULL,
                    name TEXT NOT NULL,
                    assistant_name TEXT NOT NULL,
                    is_public INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS custom_assistants (
                    assistant_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    course_name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    learning_goal TEXT NOT NULL,
                    answer_preference TEXT NOT NULL,
                    course_id TEXT NOT NULL UNIQUE,
                    workspace TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_custom_assistants_user
                ON custom_assistants(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    assistant_id TEXT,
                    user_id TEXT,
                    filename TEXT NOT NULL,
                    format TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    parsed_path TEXT,
                    parser TEXT,
                    parser_version TEXT,
                    index_status TEXT NOT NULL,
                    error_message TEXT,
                    lightrag_track_id TEXT,
                    created_at TEXT NOT NULL,
                    indexed_at TEXT,
                    UNIQUE(workspace, sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_docs_course
                ON knowledge_documents(course_id, index_status, created_at DESC);
                CREATE TABLE IF NOT EXISTS indexing_jobs (
                    job_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    assistant_id TEXT,
                    course_id TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL,
                    error_message TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_indexing_jobs_status
                ON indexing_jobs(status, updated_at);
                CREATE TABLE IF NOT EXISTS practice_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    question TEXT,
                    answer TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_practice_user_course
                ON practice_records(user_id, course_id, created_at DESC);
                """
            )
            self._ensure_column(connection, "resources", "course_id", "TEXT NOT NULL DEFAULT 'programming_python'")
            self._ensure_column(connection, "resources", "workspace_id", "TEXT NOT NULL DEFAULT 'programming_python'")
            connection.execute(
                """
                INSERT OR IGNORE INTO course_profile_fields (
                    user_id, course_id, field, value_json, evidence, source_type,
                    confidence, updated_at, status
                ) SELECT user_id, 'programming_python', field, value_json, evidence, source_type,
                    confidence, updated_at, status FROM profile_fields
                """
            )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _profile_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "field": row["field"],
            "value": json.loads(row["value_json"]),
            "evidence": row["evidence"],
            "source_type": row["source_type"],
            "confidence": float(row["confidence"]),
            "updated_at": row["updated_at"],
            "status": row["status"],
        }

    def get_profile_records(self, user_id: str, course_id: str = "programming_python") -> Dict[str, Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM course_profile_fields WHERE user_id = ? AND course_id = ?",
                (user_id, course_id),
            ).fetchall()
        return {row["field"]: self._profile_row(row) for row in rows}

    def save_profile_record(
        self,
        user_id: str,
        record: Dict[str, Any],
        reason: str,
        course_id: str = "programming_python",
    ) -> Optional[Dict[str, Any]]:
        old_record = self.get_profile_records(user_id, course_id).get(record["field"])
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO course_profile_fields (
                    user_id, course_id, field, value_json, evidence, source_type,
                    confidence, updated_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, course_id, field) DO UPDATE SET
                    value_json = excluded.value_json,
                    evidence = excluded.evidence,
                    source_type = excluded.source_type,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at,
                    status = excluded.status
                """,
                (
                    user_id,
                    course_id,
                    record["field"],
                    json.dumps(record["value"], ensure_ascii=False),
                    record["evidence"],
                    record["source_type"],
                    float(record["confidence"]),
                    record["updated_at"],
                    record["status"],
                ),
            )
            connection.execute(
                """
                INSERT INTO course_profile_changes (
                    user_id, course_id, field, old_record_json, new_record_json, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    course_id,
                    record["field"],
                    json.dumps(old_record, ensure_ascii=False) if old_record else None,
                    json.dumps(record, ensure_ascii=False),
                    reason,
                    record["updated_at"],
                ),
            )
        return old_record

    def get_profile_changes(
        self, user_id: str, limit: int = 12, course_id: str = "programming_python"
    ) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM course_profile_changes
                WHERE user_id = ? AND course_id = ? ORDER BY id DESC LIMIT ?
                """,
                (user_id, course_id, limit),
            ).fetchall()
        return [
            {
                "field": row["field"],
                "old_record": json.loads(row["old_record_json"]) if row["old_record_json"] else None,
                "new_record": json.loads(row["new_record_json"]),
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_resource(
        self,
        resource: Dict[str, Any],
        user_id: str,
        course_id: str = "programming_python",
        workspace_id: str = "programming_python",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO resources (
                    id, user_id, type, title, content_json, profile_basis_json,
                    citations_json, claims_json, review_status, review_json,
                    agent_mode, created_at, course_id, workspace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource["id"],
                    user_id,
                    resource["type"],
                    resource["title"],
                    json.dumps(resource["content"], ensure_ascii=False),
                    json.dumps(resource["profile_basis"], ensure_ascii=False),
                    json.dumps(resource["citations"], ensure_ascii=False),
                    json.dumps(resource.get("claims", []), ensure_ascii=False),
                    resource["review_status"],
                    json.dumps(resource.get("review", {}), ensure_ascii=False),
                    resource.get("agent_mode", "unknown"),
                    resource["created_at"],
                    course_id,
                    workspace_id,
                ),
            )

    @staticmethod
    def _resource_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "title": row["title"],
            "content": json.loads(row["content_json"]),
            "profile_basis": json.loads(row["profile_basis_json"]),
            "citations": json.loads(row["citations_json"]),
            "claims": json.loads(row["claims_json"]),
            "review_status": row["review_status"],
            "review": json.loads(row["review_json"]),
            "agent_mode": row["agent_mode"],
            "created_at": row["created_at"],
            "course_id": row["course_id"],
            "workspace_id": row["workspace_id"],
        }

    def get_resource(self, resource_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM resources WHERE id = ?", (resource_id,)
            ).fetchone()
        return self._resource_row(row) if row else None

    def list_resources(
        self, user_id: str, limit: int = 30, course_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            if course_id:
                rows = connection.execute(
                    "SELECT * FROM resources WHERE user_id = ? AND course_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, course_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM resources WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return [self._resource_row(row) for row in rows]

    def save_practice_record(
        self,
        user_id: str,
        course_id: str,
        question: Optional[str],
        answer: str,
        score: int,
        result: Dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO practice_records (user_id, course_id, question, answer, score, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, course_id, question, answer, int(score), json.dumps(result, ensure_ascii=False), self.utc_now()),
            )

    def register_courses(self, courses: List[Dict[str, Any]]) -> None:
        now = self.utc_now()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO courses (course_id, workspace, domain, name, assistant_name, is_public, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(course_id) DO UPDATE SET
                    workspace=excluded.workspace,
                    domain=excluded.domain,
                    name=excluded.name,
                    assistant_name=excluded.assistant_name,
                    is_public=excluded.is_public
                """,
                [
                    (
                        item["course_id"], item["workspace"], item["domain"], item["name"],
                        item["assistant_name"], int(item.get("is_public", True)), now,
                    )
                    for item in courses
                ],
            )

    def list_courses(self, include_private: bool = False, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM courses WHERE is_public = 1 ORDER BY domain, name"
        params: tuple = ()
        if include_private and user_id:
            query = """
                SELECT c.* FROM courses c
                LEFT JOIN custom_assistants a ON a.course_id = c.course_id
                WHERE c.is_public = 1 OR a.user_id = ? ORDER BY c.domain, c.name
            """
            params = (user_id,)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def create_custom_assistant(self, assistant: Dict[str, Any]) -> Dict[str, Any]:
        now = self.utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO custom_assistants (
                    assistant_id, user_id, name, course_name, domain, learning_goal,
                    answer_preference, course_id, workspace, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assistant["assistant_id"], assistant["user_id"], assistant["name"],
                    assistant["course_name"], assistant["domain"], assistant.get("learning_goal", ""),
                    assistant.get("answer_preference", ""), assistant["course_id"], assistant["workspace"],
                    assistant.get("status", "awaiting_documents"), now, now,
                ),
            )
            connection.execute(
                """
                INSERT INTO courses (course_id, workspace, domain, name, assistant_name, is_public, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (assistant["course_id"], assistant["workspace"], assistant["domain"], assistant["course_name"], assistant["name"], now),
            )
        return self.get_custom_assistant(assistant["assistant_id"], assistant["user_id"])

    def get_custom_assistant(self, assistant_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM custom_assistants WHERE assistant_id = ?"
        params: tuple = (assistant_id,)
        if user_id is not None:
            query += " AND user_id = ?"
            params = (assistant_id, user_id)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def update_assistant_status(self, assistant_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE custom_assistants SET status = ?, updated_at = ? WHERE assistant_id = ?",
                (status, self.utc_now(), assistant_id),
            )

    def save_knowledge_document(self, document: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_documents (
                    document_id, course_id, workspace, assistant_id, user_id, filename, format,
                    size_bytes, sha256, source_path, original_path, parsed_path, parser,
                    parser_version, index_status, error_message, lightrag_track_id, created_at, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    parsed_path=excluded.parsed_path, parser=excluded.parser,
                    parser_version=excluded.parser_version, index_status=excluded.index_status,
                    error_message=excluded.error_message, lightrag_track_id=excluded.lightrag_track_id,
                    indexed_at=excluded.indexed_at
                """,
                (
                    document["document_id"], document["course_id"], document["workspace"],
                    document.get("assistant_id"), document.get("user_id"), document["filename"],
                    document["format"], int(document["size_bytes"]), document["sha256"],
                    document["source_path"], document["original_path"], document.get("parsed_path"),
                    document.get("parser"), document.get("parser_version"), document["index_status"],
                    document.get("error_message"), document.get("lightrag_track_id"),
                    document.get("created_at") or self.utc_now(), document.get("indexed_at"),
                ),
            )

    def find_document_by_hash(self, workspace: str, sha256: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE workspace = ? AND sha256 = ?",
                (workspace, sha256),
            ).fetchone()
        return dict(row) if row else None

    def get_knowledge_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        return dict(row) if row else None

    def mark_document_deleted(self, document_id: str, message: Optional[str] = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE knowledge_documents SET index_status = 'deleted', error_message = ? WHERE document_id = ?",
                (message, document_id),
            )

    def list_knowledge_documents(
        self,
        course_id: Optional[str] = None,
        assistant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        for field, value in (("course_id", course_id), ("assistant_id", assistant_id), ("user_id", user_id)):
            if value is not None:
                clauses.append(f"{field} = ?")
                params.append(value)
        query = "SELECT * FROM knowledge_documents"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def create_indexing_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        now = self.utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO indexing_jobs (
                    job_id, document_id, assistant_id, course_id, workspace, user_id,
                    status, progress, stage, error_message, attempt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["job_id"], job["document_id"], job.get("assistant_id"), job["course_id"],
                    job["workspace"], job.get("user_id"), job.get("status", "queued"),
                    int(job.get("progress", 0)), job.get("stage", "queued"), job.get("error_message"),
                    int(job.get("attempt_count", 0)), now, now,
                ),
            )
        return self.get_indexing_job(job["job_id"])

    def update_indexing_job(
        self,
        job_id: str,
        status: str,
        progress: int,
        stage: str,
        error_message: Optional[str] = None,
        increment_attempt: bool = False,
    ) -> None:
        completed_at = self.utc_now() if status in {"completed", "failed", "duplicate"} else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE indexing_jobs SET status = ?, progress = ?, stage = ?, error_message = ?,
                    attempt_count = attempt_count + ?, updated_at = ?, completed_at = ?
                WHERE job_id = ?
                """,
                (status, max(0, min(100, progress)), stage, error_message, int(increment_attempt), self.utc_now(), completed_at, job_id),
            )

    def get_indexing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM indexing_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_resumable_jobs(self, retry_failed: bool = False) -> List[Dict[str, Any]]:
        statuses = ("queued", "running", "failed") if retry_failed else ("queued", "running")
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM indexing_jobs WHERE status IN ({placeholders}) ORDER BY created_at", statuses
            ).fetchall()
        return [dict(row) for row in rows]
