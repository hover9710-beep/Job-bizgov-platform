from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_JSON_PATH = BASE_DIR / "data" / "bizinfo" / "json" / "bizinfo_all.json"
DB_PATH = Path(__file__).resolve().parent / "bizgov.db"


def read_items(json_path: Path) -> list[dict[str, Any]]:
    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("list_sample"), list):
            return [item for item in payload["list_sample"] if isinstance(item, dict)]
        if isinstance(payload.get("items"), list):
            return [item for item in payload["items"] if isinstance(item, dict)]
    return []


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT,
            summary TEXT,
            date TEXT,
            source TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()


def save_items(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> int:
    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = 0
    for item in items:
        title = str(item.get("title") or "")
        url = str(item.get("url") or item.get("link") or item.get("seq") or "")
        summary = str(item.get("summary") or item.get("description") or "")
        date = str(item.get("date") or item.get("pubDate") or "")
        source = str(item.get("source") or "bizinfo")
        if not url:
            continue
        cur = conn.execute(
            """
            INSERT INTO projects (title, url, summary, date, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, url, summary, date, source, now),
        )
        if cur.rowcount > 0:
            inserted += 1
    conn.commit()
    return inserted


def count_rows(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM projects").fetchone()
    return int(row[0]) if row else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Save bizinfo JSON data into SQLite.")
    parser.add_argument("--json-path", default=str(DEFAULT_JSON_PATH), help="path to source JSON file")
    args = parser.parse_args()

    json_path = Path(args.json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    items = read_items(json_path)
    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)
        before = count_rows(conn)
        print(f"db_rows_before={before}")
        # Temporary mode: disable duplicate effect by resetting table contents.
        conn.execute("DELETE FROM projects")
        conn.commit()
        before_insert = count_rows(conn)
        inserted = save_items(conn, items)
        after = count_rows(conn)
        print(f"db_rows_after={after}")
    print(f"saved={inserted} total_input={len(items)} inserted_rows={after - before_insert} db={DB_PATH}")


if __name__ == "__main__":
    main()
