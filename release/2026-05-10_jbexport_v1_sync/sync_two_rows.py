# -*- coding: utf-8 -*-
"""백로그 052 (임시 우회): jbexport 사이트 66/65번 row 운영 DB 수동 sync.

배경:
  jbexport proxy 미작동(2026-05-08~) → run_all 의 jbexport 수집 실패 →
  운영 DB 새 공고 누적 정지. 5/10 위젯에 사이트 66번 누락 + 65번 broken row
  (title 에 spSeq 만 노출, 백로그 035 detail 추출 실패 row).

본 스크립트 = 단발성 우회. 본질 해결은 백로그 052 별도 진행 (proxy 정상화 +
  운영 DB sync 자동화). v1 로컬 DB 의 정상 row 두 개를 운영 DB 로 수동 동기.

대상:
  - 사이트 66번 (notice_order=1544): "2026년 전북FTA통상진흥센터 설명회" — 신규
    (운영 DB 미존재, INSERT)
  - 사이트 65번 (notice_order=1543): "2026년 FTA통상진흥센터 5차 교육" — 갱신
    (운영 DB 옛 broken row 존재, title=spSeq=... 형태, UPDATE)

실행 (Render Shell 또는 운영 DB 가 있는 환경):
  python release/2026-05-10_jbexport_v1_sync/sync_two_rows.py            # apply
  DRY_RUN=1 python release/2026-05-10_jbexport_v1_sync/sync_two_rows.py  # preview

흐름:
  1) DB 파일 자동 탐색 → SHA256 + 타임스탬프 백업 사본 생성
  2) 두 row 데이터 (v1 로컬 DB 에서 미리 추출한 hardcoded snapshot)
  3) 옛 broken row 정리 (title LIKE 'spSeq=...' AND source='jbexport') —
     같은 spSeq 보유 row 가 다른 url 로 존재하면 삭제 (UNIQUE 충돌 회피)
  4) ON CONFLICT(url) UPSERT — url 일치 시 id 유지 + 모든 필드 갱신,
     url 신규 시 INSERT
  5) 결과 요약 (before/after row 수, oder=1543/1544 매칭 검증)

멱등성: 이미 정확한 데이터면 UPDATE 통계 0. 두 번 실행해도 안전.
사이트 영향: 0 (HTTP 호출 없음, hardcoded snapshot 사용).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# =========================================================
# v1 로컬 DB 에서 추출한 정상 snapshot (2026-05-10)
# =========================================================
ROWS: List[Dict[str, Any]] = [
    {
        "_label": "사이트 66번 (신규 INSERT 예상)",
        "spSeq": "eb876dda1c7949f3b10e0e29685b5b43",
        "title": (
            "[교육/컨설팅] 2026년 전북FTA통상진흥센터 설명회"
            "(미국 관세정책 및 보호무역 시대에 따른 한국 수출기업의 대응 전략과 수출 실무)"
        ),
        "organization": "(재)전북특별자치도 경제통상진흥원",
        "start_date": "2026-05-08",
        "end_date": "2026-05-27",
        "status": "진행",
        "url": (
            "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/detail1.do"
            "?menuUUID=402880867c8174de017c819251e70009"
            "&spSeq=eb876dda1c7949f3b10e0e29685b5b43"
        ),
        "description": "",
        "source": "jbexport",
        "site": "",
        "collected_at": "2026-05-09T11:55:34Z",
        "ministry": "",
        "executing_agency": "",
        "receipt_start": None,
        "receipt_end": None,
        "biz_start": None,
        "biz_end": None,
        "raw_status": "접수중",
        "attachments_json": None,
        "period_text": "2026-05-08 ~ 2026-05-27",
        "ai_summary": None,
        "ai_summary_at": None,
        "recommend_label": "수출기업, 전북지역",
        "recommend_label_at": "2026-05-09T11:35:19Z",
        "attachment_text": None,
        "score": None,
        "reason": None,
        "apply_url": None,
        "notice_create_dt": None,
        "notice_chk": 0,
        "notice_order": 1544,
    },
    {
        "_label": "사이트 65번 (운영 broken row UPDATE 예상)",
        "spSeq": "93b55df14467448399e310540eab2e98",
        "title": "[교육/컨설팅] 2026년 FTA통상진흥센터 5차 교육(수출 바이어 상담 및 협상 전략)",
        "organization": "(재)전북특별자치도 경제통상진흥원",
        "start_date": "2026-04-27",
        "end_date": "2026-05-04",
        "status": "마감",
        "url": (
            "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/detail1.do"
            "?menuUUID=402880867c8174de017c819251e70009"
            "&spSeq=93b55df14467448399e310540eab2e98"
        ),
        "description": None,
        "source": "jbexport",
        "site": None,
        "collected_at": "2026-05-09T23:39:20Z",
        "ministry": None,
        "executing_agency": None,
        "receipt_start": "2026-04-27",
        "receipt_end": "2026-05-04",
        "biz_start": "2026-04-27",
        "biz_end": "2026-05-04",
        "raw_status": "접수마감",
        "attachments_json": None,
        "period_text": "2026-04-27 ~ 2026-05-04",
        "ai_summary": None,
        "ai_summary_at": None,
        "recommend_label": None,
        "recommend_label_at": None,
        "attachment_text": None,
        "score": None,
        "reason": None,
        "apply_url": None,
        "notice_create_dt": None,
        "notice_chk": 0,
        "notice_order": 1543,
    },
]


# 갱신 대상 컬럼 (id, created_at, view_count 는 보존)
UPDATABLE_COLS = (
    "title", "organization", "start_date", "end_date", "status", "url",
    "description", "source", "site", "collected_at", "ministry",
    "executing_agency", "receipt_start", "receipt_end", "biz_start", "biz_end",
    "raw_status", "attachments_json", "period_text", "ai_summary",
    "ai_summary_at", "recommend_label", "recommend_label_at", "attachment_text",
    "score", "reason", "apply_url", "notice_create_dt", "notice_chk",
    "notice_order",
)


def _resolve_db_path() -> Path:
    env = (os.getenv("DB_PATH") or "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "db" / "biz.db",
        here.parent.parent.parent / "db" / "biz.db",
    ]
    for p in candidates:
        if p.exists():
            return p
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
    backup_path = db_path.with_name(f"biz.db.backup_{ts}_052_v1_sync_{digest}")
    shutil.copy2(db_path, backup_path)
    print(f"[sync] DB 백업: {backup_path.name} (sha256={digest})", flush=True)
    return backup_path


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """049/050 백필이 누락된 환경 대비 — 컬럼 자동 추가 (idempotent)."""
    cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()}
    if "notice_chk" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_chk INTEGER DEFAULT 0")
        print("[sync] add column: biz_projects.notice_chk (INTEGER DEFAULT 0)", flush=True)
    if "notice_order" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_order INTEGER DEFAULT 0")
        print("[sync] add column: biz_projects.notice_order (INTEGER DEFAULT 0)", flush=True)
    if "notice_create_dt" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_create_dt INTEGER")
        print("[sync] add column: biz_projects.notice_create_dt (INTEGER)", flush=True)


def _print_existing_state(conn: sqlite3.Connection, label: str) -> None:
    print(f"\n[sync] === {label} ===", flush=True)
    for row in ROWS:
        sp = row["spSeq"]
        cur = conn.execute(
            "SELECT id, title, url, notice_order, notice_chk, status "
            "FROM biz_projects WHERE source='jbexport' AND url LIKE ?",
            (f"%spSeq={sp}%",),
        )
        matches = cur.fetchall()
        print(f"  spSeq={sp[:10]}... → DB row {len(matches)}건", flush=True)
        for m in matches:
            mid, mtitle, murl, mod, mchk, mstatus = m
            t = (mtitle or "")[:55]
            print(
                f"    id={mid} oder={mod} chk={mchk} status={mstatus} "
                f"title={t!r}",
                flush=True,
            )


def _cleanup_broken_rows(
    conn: sqlite3.Connection, dry_run: bool
) -> Dict[str, int]:
    """spSeq 같지만 url 다른 옛 broken row 삭제 (UNIQUE 충돌 회피).

    백로그 035 detail 추출 실패 패턴: title 이 'spSeq=...' 형태로 저장됨.
    같은 spSeq 보유한 row 가 두 개 (정상 url + broken url) 있으면 broken 삭제.
    """
    deleted_total = 0
    for row in ROWS:
        sp = row["spSeq"]
        target_url = row["url"]
        cur = conn.execute(
            "SELECT id, title, url FROM biz_projects "
            "WHERE source='jbexport' AND url LIKE ? AND url != ? "
            "AND (title LIKE 'spSeq=%' OR title IS NULL OR title = '')",
            (f"%spSeq={sp}%", target_url),
        )
        for rid, rtitle, rurl in cur.fetchall():
            print(
                f"[sync] cleanup: id={rid} broken row 삭제 예정 "
                f"(title={(rtitle or '')[:40]!r}, url={rurl[:80]}...)",
                flush=True,
            )
            if not dry_run:
                conn.execute("DELETE FROM biz_projects WHERE id = ?", (rid,))
            deleted_total += 1
    return {"deleted": deleted_total}


def _upsert_rows(
    conn: sqlite3.Connection, dry_run: bool
) -> Dict[str, int]:
    inserted = 0
    updated = 0
    unchanged = 0
    for row in ROWS:
        url = row["url"]
        cur = conn.execute(
            "SELECT id FROM biz_projects WHERE url = ?", (url,)
        )
        existing = cur.fetchone()
        label = row["_label"]
        if existing is None:
            print(f"[sync] INSERT: {label}", flush=True)
            if not dry_run:
                cols = list(UPDATABLE_COLS) + ["created_at", "updated_at"]
                placeholders = ", ".join(["?"] * len(cols))
                vals: List[Any] = [row[c] for c in UPDATABLE_COLS]
                now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                vals.extend([now, now])
                conn.execute(
                    f"INSERT INTO biz_projects ({', '.join(cols)}) "
                    f"VALUES ({placeholders})",
                    vals,
                )
            inserted += 1
        else:
            existing_id = existing[0]
            # 변경 여부 확인 (멱등성)
            cur2 = conn.execute(
                f"SELECT {', '.join(UPDATABLE_COLS)} FROM biz_projects WHERE id = ?",
                (existing_id,),
            )
            cur_vals = cur2.fetchone()
            new_vals = tuple(row[c] for c in UPDATABLE_COLS)
            if cur_vals == new_vals:
                print(
                    f"[sync] UNCHANGED: {label} (id={existing_id})", flush=True
                )
                unchanged += 1
                continue
            print(f"[sync] UPDATE: {label} (id={existing_id})", flush=True)
            if not dry_run:
                set_clause = ", ".join(f"{c} = ?" for c in UPDATABLE_COLS)
                conn.execute(
                    f"UPDATE biz_projects SET {set_clause}, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    list(new_vals) + [existing_id],
                )
            updated += 1
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


def _verify_widget_top5(conn: sqlite3.Connection) -> None:
    """위젯 정렬 (notice_chk DESC, notice_order DESC) 상위 5건 출력."""
    print("\n[sync] === 위젯 정렬 상위 5건 (notice_chk=0 한정) ===", flush=True)
    cur = conn.execute(
        "SELECT id, notice_order, notice_chk, title "
        "FROM biz_projects "
        "WHERE source='jbexport' AND notice_chk = 0 "
        "ORDER BY notice_order DESC LIMIT 5"
    )
    for rid, mod, mchk, mtitle in cur.fetchall():
        t = (mtitle or "")[:55]
        print(f"  id={rid} oder={mod} chk={mchk} title={t!r}", flush=True)


def main() -> int:
    dry_run = os.getenv("DRY_RUN", "").strip() in ("1", "true", "True", "yes")
    db_path = _resolve_db_path()
    print(f"[sync] DB 경로: {db_path} (exists={db_path.exists()})", flush=True)
    print(f"[sync] DRY_RUN={dry_run}", flush=True)
    if not db_path.exists():
        print("[sync] DB 파일 없음 → 종료", flush=True)
        return 1

    if not dry_run:
        backup_path = _backup_db(db_path)
    else:
        backup_path = None
        print("[sync] DRY_RUN → 백업 생략", flush=True)

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_columns(conn)
        _print_existing_state(conn, "BEFORE")
        cleanup = _cleanup_broken_rows(conn, dry_run)
        upsert = _upsert_rows(conn, dry_run)
        if not dry_run:
            conn.commit()
        _print_existing_state(conn, "AFTER" if not dry_run else "AFTER (DRY_RUN, 미반영)")
        _verify_widget_top5(conn)
    finally:
        conn.close()

    print("\n[sync] === 결과 ===", flush=True)
    print(f"  cleanup_deleted: {cleanup['deleted']}", flush=True)
    print(f"  inserted: {upsert['inserted']}", flush=True)
    print(f"  updated: {upsert['updated']}", flush=True)
    print(f"  unchanged: {upsert['unchanged']}", flush=True)
    if backup_path:
        print(f"  backup: {backup_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
