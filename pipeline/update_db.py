import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "db" / "biz.db"
ALL_JSON_PATH = BASE_DIR / "data" / "all_jb" / "all_jb.json"


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            organization TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            url TEXT,
            description TEXT,
            ai_result TEXT,
            pdf_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _load_items() -> List[Dict[str, Any]]:
    if not ALL_JSON_PATH.exists():
        print(f"[update_db] not found: {ALL_JSON_PATH}")
        return []
    try:
        data = json.loads(ALL_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[update_db] load error: {exc}")
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _upsert_one(conn: sqlite3.Connection, item: Dict[str, Any]) -> None:
    title = str(item.get("title") or "").strip()
    organization = str(item.get("organization") or "").strip()
    start_date = str(item.get("start_date") or "").strip()
    end_date = str(item.get("end_date") or "").strip()
    status = str(item.get("status") or "").strip()
    url = str(item.get("url") or "").strip()
    description = str(item.get("description") or "").strip()

    if not title and not url:
        return

    row = None
    if url:
        row = conn.execute("SELECT id FROM biz_projects WHERE url = ?", (url,)).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO biz_projects
            (title, organization, start_date, end_date, status, url, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (title, organization, start_date, end_date, status, url, description),
        )
        return

    conn.execute(
        """
        UPDATE biz_projects
        SET title = ?, organization = ?, start_date = ?, end_date = ?, status = ?, description = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (title, organization, start_date, end_date, status, description, row[0]),
    )


def update_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    items = _load_items()

    conn = sqlite3.connect(DB_PATH)
    try:
        _init_db(conn)
        for item in items:
            _upsert_one(conn, item)
        conn.commit()
    finally:
        conn.close()

    print(f"[update_db] upsert done: {len(items)}건 -> {DB_PATH}")


if __name__ == "__main__":
    update_db()
