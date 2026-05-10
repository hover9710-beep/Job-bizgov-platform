# -*- coding: utf-8 -*-
"""백로그 050: jbexport organization 컬럼 백필.

문제:
- DB jbexport 65~66건이 organization='전북수출통합지원시스템' (fallback) 로 저장됨
- 실제 detail HTML 에는 진짜 기관명이 td.th='주관기관' 라벨에 적혀있음
- 백로그 032-1 selector 추가 (commit a1c26b2) 이전 INSERT 된 행들이 stale 상태

이 스크립트:
- DB 자동 백업 (sha256 + 타임스탬프)
- 대상 row 의 url → spSeq → detail HTML fetch → organization 추출 → UPDATE
- 멱등성: 같은 결과면 건너뜀
- safe-mode: organization='전북수출통합지원시스템' (fallback) row 만 변경. 진짜 기관명이 들어있는
  row 는 건너뜀 (재추출은 하되 같은 값이면 무변경, 다른 값이면 사용자 시각 사고 방지 위해 LOG 만)

실행 (v1 또는 v2 루트에서):
  py release/2026-05-10_jbexport_org_fix/backfill_organization.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


FALLBACK_ORG = "전북수출통합지원시스템"
TIMEOUT = 60


# =========================================================
# DB 경로 자동 탐색
# =========================================================
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
    backup = db_path.with_name(f"biz.db.backup_{ts}_050_org_fix_{digest}")
    shutil.copy2(db_path, backup)
    print(f"[backfill] DB 백업: {backup.name} (sha256={digest})", flush=True)
    return backup


# =========================================================
# detail HTML 파싱 — jbexport_daily.parse_jbexport_detail_html 와 동일 로직
# (단독 실행 가능하게 inline. 향후 selector 변경 시 jbexport_daily 측만 갱신.)
# =========================================================
ORG_LABELS = (
    "사업주관기관",
    "사업수행기관",
    "주관기관",
    "수행기관",
    "담당기관",
    "지원기관",
)


def _extract_org_from_detail(html: str) -> str:
    if not html or not str(html).strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text("\n", strip=True)
    out = ""

    def _is_clean_value(v: str) -> bool:
        return (
            bool(v)
            and len(v) < 80
            and "function(" not in v
            and not any(lbl in v for lbl in ORG_LABELS)
        )

    # 1) th + td
    for th in soup.find_all("th"):
        label = th.get_text(" ", strip=True)
        td = th.find_next_sibling("td")
        if not td:
            continue
        if any(k in label for k in ORG_LABELS):
            val = td.get_text(" ", strip=True)
            val = " ".join(val.split())
            if _is_clean_value(val):
                out = val
                break

    # 2) dt + dd
    if not out:
        for dt_ in soup.find_all("dt"):
            label = dt_.get_text(" ", strip=True)
            dd = dt_.find_next_sibling("dd")
            if not dd:
                continue
            if any(k in label for k in ORG_LABELS):
                val = " ".join(dd.get_text(" ", strip=True).split())
                if _is_clean_value(val):
                    out = val
                    break

    # 3) td.th + td (jbexport-specific)
    if not out:
        for td_label in soup.select("td.th"):
            label = td_label.get_text(" ", strip=True)
            td_val = td_label.find_next_sibling("td")
            if not td_val:
                continue
            if any(k in label for k in ORG_LABELS):
                val = " ".join(td_val.get_text(" ", strip=True).split())
                if _is_clean_value(val):
                    out = val
                    break

    # 4) regex fallback (Phase 3 selector 보강과 동일)
    if not out:
        import re

        m = re.search(
            r"(?:사업주관기관|사업수행기관|주관기관|수행기관|담당기관|지원기관)\s*[:：]?\s*([^\n\r<]+?)(?:\n|<|$)",
            full_text,
            re.IGNORECASE,
        )
        if m:
            cand = " ".join(m.group(1).split())
            if _is_clean_value(cand):
                out = cand

    return out


# =========================================================
# 대상 행 수집 + 백필
# =========================================================
def _fetch_targets(conn: sqlite3.Connection, only_fallback: bool) -> List[Tuple[int, str, str]]:
    if only_fallback:
        rows = conn.execute(
            """
            SELECT id, organization, url FROM biz_projects
            WHERE source='jbexport'
              AND COALESCE(organization, '') = ?
              AND url IS NOT NULL AND TRIM(url) != ''
            """,
            (FALLBACK_ORG,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, organization, url FROM biz_projects
            WHERE source='jbexport'
              AND url IS NOT NULL AND TRIM(url) != ''
            """
        ).fetchall()
    return [(int(r[0]), str(r[1] or ""), str(r[2] or "")) for r in rows]


def _backfill(conn: sqlite3.Connection, targets: List[Tuple[int, str, str]]) -> Dict[str, int]:
    sess = requests.Session()
    sess.verify = False
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.jbexport.or.kr/index.do",
    }

    stats = {
        "total": len(targets),
        "fetched": 0,
        "fetch_error": 0,
        "extracted": 0,
        "extract_empty": 0,
        "updated_to_real": 0,
        "kept_existing_real": 0,
        "no_change": 0,
    }

    for sid, db_org, url in targets:
        try:
            r = sess.get(url, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
            stats["fetched"] += 1
        except Exception as exc:
            stats["fetch_error"] += 1
            print(f"  [ERR] id={sid} fetch failed: {exc}", flush=True)
            continue

        new_org = _extract_org_from_detail(r.text)
        if not new_org:
            stats["extract_empty"] += 1
            continue
        stats["extracted"] += 1

        # 머지 정책 (049 패턴):
        # - 새 값이 fallback 이고 옛 값이 진짜 기관명 → 옛 값 보존
        # - 새 값이 진짜 기관명 → UPDATE (사실상 fallback row 가 대상)
        # - 새 값 == 옛 값 → no change
        if new_org == FALLBACK_ORG and db_org and db_org != FALLBACK_ORG:
            stats["kept_existing_real"] += 1
            continue
        if new_org == db_org:
            stats["no_change"] += 1
            continue

        conn.execute(
            "UPDATE biz_projects SET organization = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_org, sid),
        )
        stats["updated_to_real"] += 1
        print(f"  [UPD] id={sid:>5} {db_org!r} -> {new_org!r}", flush=True)

    return stats


def main() -> int:
    only_fallback = os.getenv("BACKFILL_ONLY_FALLBACK", "1").strip() not in ("0", "false", "no")
    db_path = _resolve_db_path()
    print(f"[backfill] DB 경로: {db_path} (exists={db_path.exists()})", flush=True)
    print(f"[backfill] only_fallback={only_fallback}", flush=True)
    if not db_path.exists():
        print("[backfill] DB 파일 없음 → 종료", flush=True)
        return 1

    backup = _backup_db(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        targets = _fetch_targets(conn, only_fallback=only_fallback)
        print(f"[backfill] 대상 row: {len(targets)}건", flush=True)
        if not targets:
            print("[backfill] 대상 0건 → 종료 (DB 무변경)", flush=True)
            return 2
        stats = _backfill(conn, targets)
        conn.commit()
    finally:
        conn.close()

    print("\n[backfill] 결과:", flush=True)
    for k, v in stats.items():
        print(f"  {k}: {v}", flush=True)
    print(f"[backfill] 백업: {backup}", flush=True)

    # 분포 후 점검
    conn2 = sqlite3.connect(str(db_path))
    try:
        dist = conn2.execute(
            """
            SELECT COALESCE(organization, '(NULL)'), COUNT(*)
            FROM biz_projects WHERE source='jbexport'
            GROUP BY 1 ORDER BY 2 DESC
            """
        ).fetchall()
        print("\n[backfill] 백필 후 organization 분포:", flush=True)
        for org, n in dist:
            print(f"  {n:>3}건 — {org}", flush=True)
    finally:
        conn2.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
