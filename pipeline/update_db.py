"""
data/all_jb/all_jb.json → db/biz.db 의 biz_projects upsert
이후 mirror_projects 로 projects 미러링.

실행(프로젝트 루트):
  py pipeline\\update_db.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = Path(__file__).resolve().parent
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

from mirror_projects import mirror_biz_projects_to_projects
from project_quality import (
    infer_source,
    normalize_description,
    normalize_status,
    parse_period_from_item,
)

DB_PATH = ROOT_DIR / "db" / "biz.db"
ALL_JSON_PATH = ROOT_DIR / "data" / "all_jb" / "all_jb.json"

BIZ_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS biz_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    organization TEXT,
    ministry TEXT,
    executing_agency TEXT,
    source TEXT NOT NULL DEFAULT 'unknown',
    start_date TEXT,
    end_date TEXT,
    status TEXT,
    url TEXT,
    description TEXT,
    site TEXT,
    ai_result TEXT,
    pdf_path TEXT,
    collected_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(BIZ_CREATE_SQL)
    _ensure_organization_column(conn, "biz_projects")
    _ensure_organization_column(conn, "projects")
    for col in (
        "source",
        "site",
        "collected_at",
        "ministry",
        "executing_agency",
    ):
        _ensure_column(conn, "biz_projects", col)
    _ensure_column(conn, "projects", "source")
    _ensure_column(conn, "projects", "site")
    _ensure_column(conn, "projects", "collected_at")
    _ensure_column(conn, "projects", "ministry")
    _ensure_column(conn, "projects", "executing_agency")
    conn.execute(
        """
        UPDATE biz_projects
        SET source = 'unknown'
        WHERE source IS NULL OR TRIM(source) = ''
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id, project_id)
        )
        """
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_organization_column(conn: sqlite3.Connection, table_name: str) -> None:
    if not _table_exists(conn, table_name):
        return
    cols = {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if "organization" in cols:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN organization TEXT")
    print(f"[update_db] add column: {table_name}.organization")


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> None:
    if not _table_exists(conn, table_name):
        return
    cols = {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name in cols:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT")
    print(f"[update_db] add column: {table_name}.{column_name}")


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


def _prepare_row(item: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    """파이프라인 필드 정규화. source는 항상 비어 있지 않음."""
    title = str(item.get("title") or "").strip()
    organization = str(item.get("organization") or "").strip()
    ministry = str(item.get("ministry") or "").strip()
    executing_agency = str(item.get("executing_agency") or "").strip()
    site = str(item.get("site") or "").strip()
    url = str(item.get("url") or "").strip()
    sd, ed = parse_period_from_item(item)
    if not sd:
        sd = str(item.get("start_date") or "").strip()
    if not ed:
        ed = str(item.get("end_date") or "").strip()
    status = normalize_status(str(item.get("status") or "").strip())
    description = normalize_description(item)
    explicit_src = str(item.get("source") or "").strip()
    source = infer_source(
        url,
        site,
        explicit_src,
        organization=organization,
        title=title,
    )
    collected_at = str(item.get("collected_at") or "").strip()
    if not collected_at:
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {
        "title": title,
        "organization": organization,
        "ministry": ministry,
        "executing_agency": executing_agency,
        "site": site,
        "start_date": sd,
        "end_date": ed,
        "status": status,
        "url": url,
        "description": description,
        "source": source,
        "collected_at": collected_at,
    }
    return row, title, url


def _find_existing_id(
    conn: sqlite3.Connection, url: str, title: str, organization: str
) -> Optional[int]:
    if url:
        r = conn.execute("SELECT id FROM biz_projects WHERE url = ?", (url,)).fetchone()
        if r:
            return int(r[0])
    if title:
        r = conn.execute(
            """
            SELECT id FROM biz_projects
            WHERE (url IS NULL OR TRIM(url) = '')
              AND title = ?
              AND COALESCE(organization, '') = COALESCE(?, '')
            """,
            (title, organization),
        ).fetchone()
        if r:
            return int(r[0])
    return None


def _upsert_one(conn: sqlite3.Connection, item: Dict[str, Any]) -> None:
    row, title, url = _prepare_row(item)
    if not title and not url:
        return

    eid = _find_existing_id(conn, row["url"], row["title"], row["organization"])

    ai_result = item.get("ai_result")
    pdf_path = item.get("pdf_path")

    if eid is None:
        conn.execute(
            """
            INSERT INTO biz_projects (
                title, organization, ministry, executing_agency, source,
                start_date, end_date, status, url, description, site,
                ai_result, pdf_path, collected_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                row["title"],
                row["organization"],
                row["ministry"],
                row["executing_agency"],
                row["source"],
                row["start_date"],
                row["end_date"],
                row["status"],
                row["url"],
                row["description"],
                row["site"],
                ai_result if ai_result is not None else None,
                pdf_path if pdf_path is not None else None,
                row["collected_at"],
            ),
        )
        return

    cur = conn.execute(
        "SELECT ai_result, pdf_path FROM biz_projects WHERE id = ?",
        (eid,),
    ).fetchone()
    old_ai, old_pdf = (cur or (None, None))

    new_ai = old_ai if ai_result is None else ai_result
    new_pdf = old_pdf if pdf_path is None else pdf_path

    conn.execute(
        """
        UPDATE biz_projects
        SET title = ?, organization = ?, ministry = ?, executing_agency = ?,
            source = ?, start_date = ?, end_date = ?, status = ?, url = ?,
            description = ?, site = ?, ai_result = ?, pdf_path = ?,
            collected_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            row["title"],
            row["organization"],
            row["ministry"],
            row["executing_agency"],
            row["source"],
            row["start_date"],
            row["end_date"],
            row["status"],
            row["url"],
            row["description"],
            row["site"],
            new_ai,
            new_pdf,
            row["collected_at"],
            eid,
        ),
    )


def _backfill_infer_source(conn: sqlite3.Connection) -> None:
    """기존 행 URL·site 기준 source 재추론 (NULL·빈값 금지)."""
    conn.execute(
        """
        UPDATE biz_projects
        SET source = 'unknown'
        WHERE source IS NULL OR TRIM(source) = ''
        """
    )
    for rid, url, site, src, org, title in conn.execute(
        "SELECT id, url, site, source, organization, title FROM biz_projects"
    ).fetchall():
        new_s = infer_source(
            str(url or ""),
            str(site or ""),
            str(src or ""),
            organization=str(org or ""),
            title=str(title or ""),
        )
        conn.execute("UPDATE biz_projects SET source = ? WHERE id = ?", (new_s, rid))


def _print_field_completeness(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) FROM biz_projects").fetchone()
    n = int(row[0]) if row else 0
    if n == 0:
        print("[필드 완성도] 데이터 0건")
        return

    def miss(cond_sql: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM biz_projects WHERE {cond_sql}").fetchone()[0])

    def line(icon: str, label: str, m: int) -> None:
        pct = (m / n * 100) if n else 0.0
        print(f"{icon} {label:14s}: 미채움 {m}건 ({pct:.0f}%)")

    print(f"[필드 완성도] 전체 {n}건")
    m_src = miss("source IS NULL OR TRIM(source) = ''")
    line("[O]" if m_src == 0 else "[!]", "source", m_src)
    m_sd = miss("start_date IS NULL OR TRIM(start_date) = ''")
    line("[O]" if m_sd == 0 else "[!]", "start_date", m_sd)
    m_ed = miss("end_date IS NULL OR TRIM(end_date) = ''")
    line("[O]" if m_ed == 0 else "[!]", "end_date", m_ed)
    m_st = miss(
        "status IS NULL OR TRIM(status) = '' OR status = '확인 필요'"
    )
    line("[O]" if m_st == 0 else "[X]", "status", m_st)

    unk = int(
        conn.execute(
            "SELECT COUNT(*) FROM biz_projects WHERE LOWER(TRIM(COALESCE(source,''))) = 'unknown'"
        ).fetchone()[0]
    )
    print(f"[i] source=unknown: {unk}건 ({unk/n*100:.0f}%)")


def update_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    items = _load_items()

    conn = sqlite3.connect(DB_PATH)
    try:
        _init_db(conn)
        for item in items:
            _upsert_one(conn, item)
        _backfill_infer_source(conn)

        m = mirror_biz_projects_to_projects(conn)
        if m.get("skipped"):
            print("[update_db] mirror_projects: biz_projects 없음, 건너뜀")
        else:
            print(
                f"[update_db] mirror projects <- biz_projects: "
                f"삽입 {m['inserted']}건 (projects 기존 {m['before']}건 삭제 후)"
            )
        conn.commit()
        print(f"[update_db] upsert done: {len(items)}건 -> {DB_PATH}")
        _print_field_completeness(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    update_db()
