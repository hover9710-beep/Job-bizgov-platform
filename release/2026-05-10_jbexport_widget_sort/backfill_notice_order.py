# -*- coding: utf-8 -*-
"""백로그 049: jbexport 위젯 정렬 컬럼 백필.

사이트 jbexport.or.kr 의 정렬 키 (notiChk DESC, oder DESC) 를
biz_projects.notice_chk / biz_projects.notice_order 컬럼에 채운다.

실행 (v1 또는 v2 루트에서):
  py release/2026-05-10_jbexport_widget_sort/backfill_notice_order.py

흐름:
  1) DB 파일 자동 탐색 → SHA256 + 타임스탬프 백업 사본 생성 (백업 필수)
  2) jbexport.or.kr 목록 API 직접 호출 (work_year=2026, length=200)
  3) 응답 row 의 SP_SEQ → DB 행 url LIKE '%spSeq=' || SP_SEQ 매칭
  4) notice_chk = notiChk, notice_order = oder UPDATE
  5) 결과 요약 (매칭/미매칭/UPDATE 건수)

사이트 영향: GET 1회 (HTTP POST 1회), DB 영향 없음 (로컬 사본만).
운영 DB 는 별도 — 본 스크립트는 로컬 사본만 갱신함.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =========================================================
# 사이트 호출 — proxy 없이 upstream 직접 (백필 1회용)
# =========================================================
JBEXPORT_LIST_URL = (
    "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/getWork1Search.do"
)
LIST_REFERER = (
    "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/spWorkSupportBusinessList.do"
)
LIST_VIEW_URL = (
    "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/view1.do"
    "?menuUUID=402880867c8174de017c819251e70009"
)

DEFAULT_LENGTH = 200
WORK_YEARS = ("2026", "2025")  # 2026 우선, 2025 도 시도(지난해 등록·연속 공고 대비)
TIMEOUT = 60


def _build_payload(start: int, length: int, draw: int, work_year: str) -> Dict[str, str]:
    payload: Dict[str, str] = {
        "draw": str(draw),
        "start": str(start),
        "length": str(length),
        "work_year": work_year,
        "tsGubun": "",
        "stat": "",
        "js": "",
        "js_input": "",
        "su": "",
        "search[value]": "",
        "search[regex]": "false",
    }
    payload["columns[0][data]"] = "0"
    payload["columns[1][data]"] = "CODE_K"
    payload["columns[2][data]"] = "CATEGO"
    payload["columns[3][data]"] = "js_title"
    payload["columns[4][data]"] = "STS_TXT"
    for i in range(5):
        payload[f"columns[{i}][name]"] = ""
        payload[f"columns[{i}][searchable]"] = "true"
        payload[f"columns[{i}][orderable]"] = "true"
        payload[f"columns[{i}][search][value]"] = ""
        payload[f"columns[{i}][search][regex]"] = "false"
    payload["order[0][column]"] = "0"
    payload["order[0][dir]"] = "desc"
    return payload


def _fetch_one_year(work_year: str, length: int = DEFAULT_LENGTH) -> List[Dict[str, Any]]:
    """work_year 의 모든 공고를 1회 또는 페이지네이션으로 수집."""
    sess = requests.Session()
    sess.verify = False
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": LIST_REFERER,
        "Origin": "https://www.jbexport.or.kr",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    # 세션 워밍 (목록 HTML 쿠키 선획득)
    try:
        sess.get(LIST_VIEW_URL, headers={"Referer": LIST_REFERER, "User-Agent": headers["User-Agent"]}, timeout=TIMEOUT)
    except requests.RequestException:
        pass

    all_rows: List[Dict[str, Any]] = []
    start = 0
    draw = 1
    records_total: Optional[int] = None
    while True:
        payload = _build_payload(start=start, length=length, draw=draw, work_year=work_year)
        r = sess.post(JBEXPORT_LIST_URL, data=payload, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        try:
            j = r.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"upstream 응답이 JSON 아님 (work_year={work_year}, status={r.status_code}): {exc}"
            )
        rows = j.get("data") or j.get("aaData") or []
        if not isinstance(rows, list) or not rows:
            break
        all_rows.extend([row for row in rows if isinstance(row, dict)])
        if records_total is None:
            try:
                records_total = int(j.get("recordsTotal") or j.get("recordsFiltered") or 0)
            except (TypeError, ValueError):
                records_total = None
        if records_total is not None and len(all_rows) >= records_total:
            break
        start += len(rows)
        draw += 1
        if draw > 50:
            break
    return all_rows


def _collect_all_rows() -> List[Dict[str, Any]]:
    seen_seq: set = set()
    out: List[Dict[str, Any]] = []
    for year in WORK_YEARS:
        try:
            rows = _fetch_one_year(year)
        except Exception as exc:
            print(f"[backfill] work_year={year} 수집 실패: {exc}", flush=True)
            continue
        for row in rows:
            sp = str(row.get("SP_SEQ") or row.get("spSeq") or "").strip()
            if not sp or sp in seen_seq:
                continue
            seen_seq.add(sp)
            out.append(row)
        print(f"[backfill] work_year={year} → {len(rows)}건 (누적 {len(out)})", flush=True)
    return out


# =========================================================
# DB 경로 자동 탐색
# =========================================================
def _resolve_db_path() -> Path:
    env = (os.getenv("DB_PATH") or "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    # 후보: 작업 폴더 우선 → release 폴더 부모(=프로젝트 루트)
    candidates = [
        Path.cwd() / "db" / "biz.db",
        here.parent.parent.parent / "db" / "biz.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    # 마지막 fallback
    return Path.cwd() / "db" / "biz.db"


def _backup_db(db_path: Path) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"DB 파일 없음: {db_path}")
    h = hashlib.sha256()
    with open(db_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()[:12]
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"biz.db.backup_{ts}_049_widget_sort_{digest}")
    shutil.copy2(db_path, backup_path)
    print(f"[backfill] DB 백업: {backup_path.name} (sha256={digest})", flush=True)
    return backup_path


# =========================================================
# 매칭 + UPDATE
# =========================================================
def _build_seq_to_values(rows: List[Dict[str, Any]]) -> Dict[str, Tuple[int, int]]:
    out: Dict[str, Tuple[int, int]] = {}
    for r in rows:
        sp = str(r.get("SP_SEQ") or r.get("spSeq") or "").strip()
        if not sp:
            continue
        try:
            chk = int(r.get("notiChk") or r.get("NOTICHK") or 0)
        except (TypeError, ValueError):
            chk = 0
        try:
            order = int(r.get("oder") or r.get("ODER") or 0)
        except (TypeError, ValueError):
            order = 0
        out[sp] = (chk, order)
    return out


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()}
    if "notice_chk" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_chk INTEGER DEFAULT 0")
        print("[backfill] add column: biz_projects.notice_chk (INTEGER DEFAULT 0)", flush=True)
    if "notice_order" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_order INTEGER DEFAULT 0")
        print("[backfill] add column: biz_projects.notice_order (INTEGER DEFAULT 0)", flush=True)


def _update_db(
    conn: sqlite3.Connection, seq_to_values: Dict[str, Tuple[int, int]]
) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT id, url FROM biz_projects WHERE source = 'jbexport' AND url IS NOT NULL"
    ).fetchall()
    matched = 0
    updated = 0
    no_seq_in_url = 0
    no_match_on_site = 0
    for rid, url in rows:
        s = str(url or "")
        idx = s.rfind("spSeq=")
        if idx < 0:
            no_seq_in_url += 1
            continue
        seq = s[idx + len("spSeq="):]
        # spSeq 뒤에 다른 파라미터 붙은 경우 잘라냄
        for sep in ("&", "#", "?"):
            j = seq.find(sep)
            if j >= 0:
                seq = seq[:j]
        seq = seq.strip()
        if not seq:
            no_seq_in_url += 1
            continue
        vals = seq_to_values.get(seq)
        if vals is None:
            no_match_on_site += 1
            continue
        matched += 1
        chk, order = vals
        cur = conn.execute(
            "UPDATE biz_projects SET notice_chk = ?, notice_order = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (chk, order, int(rid)),
        )
        if cur.rowcount > 0:
            updated += 1
    return {
        "rows_in_db": len(rows),
        "site_rows": len(seq_to_values),
        "matched": matched,
        "updated": updated,
        "no_seq_in_url": no_seq_in_url,
        "no_match_on_site": no_match_on_site,
    }


def main() -> int:
    db_path = _resolve_db_path()
    print(f"[backfill] DB 경로: {db_path} (exists={db_path.exists()})", flush=True)
    if not db_path.exists():
        print("[backfill] DB 파일 없음 → 종료", flush=True)
        return 1

    backup_path = _backup_db(db_path)

    print("[backfill] 사이트 list API 호출 중...", flush=True)
    site_rows = _collect_all_rows()
    seq_to_values = _build_seq_to_values(site_rows)
    print(f"[backfill] 사이트 수집 완료: {len(seq_to_values)}건 (SP_SEQ 기준 dedupe 후)", flush=True)

    if not seq_to_values:
        print("[backfill] 사이트 응답 0건 → 백필 중단 (DB 무변경)", flush=True)
        return 2

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_columns(conn)
        stats = _update_db(conn, seq_to_values)
        conn.commit()
    finally:
        conn.close()

    print("[backfill] 결과:", flush=True)
    for k, v in stats.items():
        print(f"  {k}: {v}", flush=True)
    print(f"[backfill] 백업 위치: {backup_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
