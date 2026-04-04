# -*- coding: utf-8 -*-
"""
DB에 있는 기업마당(bizinfo) 공고에 대해 상세 URL을 다시 요청해
ministry / executing_agency를 채웁니다 (div/span/strong/li 라벨 구조 파싱).
기존 행은 URL 기준 UPDATE만 하며 INSERT 하지 않습니다.

실행(프로젝트 루트):
  py pipeline/backfill_bizinfo_agency.py
  py pipeline/backfill_bizinfo_agency.py --limit 20
  py pipeline/backfill_bizinfo_agency.py --only-missing
  py pipeline/backfill_bizinfo_agency.py --no-verify-ssl
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.blueprints.connector_www_bizinfo_go_kr import (
    DETAIL_PATTERN,
    HEADERS,
    TIMEOUT,
    build_session,
)

DB_PATH = ROOT / "db" / "biz.db"


def extract_by_label(soup, labels):
    """
    Find value text based on label text.
    Works for div/span/strong/li structures.
    """
    for label in labels:
        node = soup.find(string=lambda t: t and label in t)
        if not node:
            continue

        parent = node.parent

        # next sibling tag
        sib = parent.find_next_sibling()
        if sib and sib.get_text(strip=True):
            return sib.get_text(strip=True)

        # parent's next sibling
        if parent.parent:
            sib2 = parent.parent.find_next_sibling()
            if sib2 and sib2.get_text(strip=True):
                return sib2.get_text(strip=True)

        # same container .txt class
        box = parent.find_parent()
        if box:
            txt = box.find(class_="txt")
            if txt:
                return txt.get_text(strip=True)

    return ""


def _detail_url_from_list_url(url: str) -> str:
    seq_m = re.search(r"pblancId=([^&]+)", url, re.I)
    seq = seq_m.group(1).strip() if seq_m else ""
    if not seq:
        return ""
    return DETAIL_PATTERN.replace("{seq}", str(seq))


def _fetch_detail_html(url: str, session: requests.Session) -> str | None:
    """상세 페이지 HTML (connector와 동일 URL 규칙)."""
    detail_url = _detail_url_from_list_url(url)
    if not detail_url:
        try:
            r = session.get(url, timeout=max(TIMEOUT, 25))
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            return None
    try:
        r = session.get(detail_url, timeout=max(TIMEOUT, 25))
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    names = {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    return col in names


def _debug_stripped_strings(soup: BeautifulSoup) -> None:
    chunks: list[str] = []
    for s in soup.stripped_strings:
        t = str(s).strip()
        if not t:
            continue
        chunks.append(t)
        if len(chunks) >= 20:
            break
    print(f"[debug] stripped_strings (first 20): {chunks!r}", flush=True)


def run(
    *,
    db_path: Path,
    limit: int | None,
    only_missing: bool,
    delay_sec: float,
    verify_ssl: bool,
) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    has_updated = _has_column(conn, "biz_projects", "updated_at")

    sql = """
        SELECT id, url, ministry, executing_agency, organization
        FROM biz_projects
        WHERE LOWER(TRIM(COALESCE(source,''))) = 'bizinfo'
          AND url IS NOT NULL AND TRIM(url) != ''
    """
    if only_missing:
        sql += """
          AND (
            TRIM(COALESCE(ministry,'')) = ''
            OR TRIM(COALESCE(executing_agency,'')) = ''
          )
        """
    sql += " ORDER BY id"
    params: list = []
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))

    rows = conn.execute(sql, params).fetchall()
    session = build_session(verify=verify_ssl)
    session.headers.update(HEADERS)

    updated = 0
    skipped = 0
    errors = 0
    debug_soup: BeautifulSoup | None = None

    for i, row in enumerate(rows, start=1):
        rid = int(row["id"])
        url = str(row["url"] or "").strip()
        old_m = str(row["ministry"] or "").strip()
        old_e = str(row["executing_agency"] or "").strip()

        try:
            html = _fetch_detail_html(url, session)
        except Exception:
            errors += 1
            print(f"[{i}/{len(rows)}] id={rid} HTTP 예외", flush=True)
            time.sleep(delay_sec)
            continue

        if not html:
            errors += 1
            print(f"[{i}/{len(rows)}] id={rid} HTML 없음", flush=True)
            time.sleep(delay_sec)
            continue

        soup = BeautifulSoup(html, "html.parser")

        ministry = extract_by_label(
            soup,
            ["소관부처", "주관부처", "부처"],
        )
        executing_agency = extract_by_label(
            soup,
            [
                "사업수행기관",
                "수행기관",
                "지원기관",
                "주관기관",
                "운영기관",
                "전담기관",
            ],
        )

        if ministry or executing_agency:
            new_m = ministry if ministry else old_m
            new_e = executing_agency if executing_agency else old_e

            if has_updated:
                conn.execute(
                    """
                    UPDATE biz_projects
                    SET ministry = ?, executing_agency = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_m or None, new_e or None, rid),
                )
            else:
                conn.execute(
                    """
                    UPDATE biz_projects
                    SET ministry = ?, executing_agency = ?
                    WHERE id = ?
                    """,
                    (new_m or None, new_e or None, rid),
                )
            conn.commit()
            updated += 1
            print(
                f"[{i}/{len(rows)}] id={rid} ministry={ministry} executing_agency={executing_agency} UPDATE",
                flush=True,
            )
        else:
            skipped += 1
            print(f"[{i}/{len(rows)}] id={rid} 파싱없음 (스킵)", flush=True)
            if debug_soup is None:
                debug_soup = soup

        time.sleep(delay_sec)

    if len(rows) > 0 and updated == 0 and skipped == len(rows) and errors == 0 and debug_soup is not None:
        print("[debug] 전체 행이 파싱 스킵 → 첫 스킵 페이지 레이아웃 샘플:", flush=True)
        _debug_stripped_strings(debug_soup)

    return {"total": len(rows), "updated": updated, "skipped_no_parse": skipped, "errors": errors}


def main() -> int:
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:
                pass

    ap = argparse.ArgumentParser(description="기업마당 상세 재조회 후 ministry/executing_agency UPDATE")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--limit", type=int, default=None, help="처리 최대 건수 (미지정=전체)")
    ap.add_argument("--only-missing", action="store_true", help="ministry/executing 둘 중 하나라도 비었을 때만")
    ap.add_argument("--delay", type=float, default=0.15, help="요청 간 대기(초)")
    ap.add_argument("--no-verify-ssl", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[backfill_bizinfo_agency] ERROR: DB 없음 → {args.db}")
        return 1

    stats = run(
        db_path=args.db.resolve(),
        limit=args.limit,
        only_missing=args.only_missing,
        delay_sec=args.delay,
        verify_ssl=not args.no_verify_ssl,
    )
    print(
        f"[backfill_bizinfo_agency] 완료: 대상 {stats['total']}건, "
        f"UPDATE {stats['updated']}건, 파싱없음 {stats['skipped_no_parse']}건, 오류 {stats['errors']}건",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
