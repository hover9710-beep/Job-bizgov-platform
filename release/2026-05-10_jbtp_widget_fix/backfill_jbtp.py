# -*- coding: utf-8 -*-
"""백로그 053: jbtp 위젯 정렬/start_date 백필.

목적:
  v2 connector_jbtp.py 가 새 row 부터 notice_chk + notice_order + start_date 를
  채우지만, 기존 128 row (5/10 v2 로컬 기준) 는 모두 0/공란. 위젯이
  start_date >= '2026-01-01' 필터로 95/128 (74%) 탈락 + 정렬 키 부재로 사이트
  vs 위젯 0/5 매칭. 본 스크립트가 사이트 list 를 9페이지 fetch → DB row 와
  dataSid 로 매칭 → 누락 3 필드 UPDATE.

매칭 키: url 내 'dataSid=XXX' (정수)

실행:
  py release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py            # apply
  set DRY_RUN=1 && py release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py  # preview

흐름:
  1) DB 자동 탐색 → SHA256 + 타임스탬프 백업 사본 (DRY_RUN 시 생략)
  2) 컬럼 자동 보장 (notice_chk + notice_order, INTEGER DEFAULT 0)
  3) 사이트 fetch (인라인 fetch + parse, self-contained) — MAX_PAGES=9 + 0.5s sleep
  4) RawRow → {data_sid: {is_notice, reg_date, end_date, status, title}} 인덱싱
  5) DB row 순회 → url 의 dataSid 추출 → 매칭 → UPDATE (변경된 필드만)
  6) 결과 요약 (matched / updated / unchanged / no_match) + 위젯 분포

멱등성: 같은 값이면 UPDATE 0. 두 번 실행해도 안전.
사이트 영향: list API 9 페이지 fetch (proxy 무관, requests.get 200).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parent.parent.parent

# 백로그 029 (v1/v2 connector sync) 통째 보류 → backfill self-contained.
# v1 legacy connector (fetch_list_page) 와 v2 4단계 분리 (fetch/parse) 둘 다
# 호환되도록 사이트 fetch/parse 를 인라인. connector_jbtp module 의존 없음.
import requests  # noqa: E402
import urllib3  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


_BASE_LIST = (
    "https://www.jbtp.or.kr/board/list.jbtp?"
    "boardId=BBS_0000006&menuCd=DOM_000000102001000000&paging=ok&pageNo={page}"
)
_MAX_PAGES = 9
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

_DATASID_RE = re.compile(r"dataSid=(\d+)")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _fetch_page(page_no: int) -> str:
    url = _BASE_LIST.format(page=page_no)
    r = requests.get(url, headers=_HEADERS, timeout=15, verify=False)
    r.raise_for_status()
    return r.text


def _parse_page(html: str) -> List[Dict[str, Any]]:
    """list HTML → [{data_sid, title, is_notice, reg_date_text, seq_text}].

    백필에 필요한 필드만 추출 (v2 connector_jbtp.parse 의 부분집합):
      - data_sid     : a[href] 의 dataSid=NNN (매칭 키)
      - is_notice    : tr td[0].class 에 'notice'
      - reg_date_text: td[6] (등록일 → start_date)
      - seq_text     : td[0] (일반글 sort 키, 공지는 '[공지]')
    """
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    for row in soup.select("table tbody tr"):
        a = row.select_one("td.txt_left a") or row.select_one("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        href = (a.get("href") or "").strip()
        m = _DATASID_RE.search(href)
        if not m:
            continue
        tds = row.select("td")
        td0_cls = tds[0].get("class") if tds else None
        is_notice = bool(td0_cls and "notice" in td0_cls)
        reg_date_text = tds[6].get_text(" ", strip=True) if len(tds) >= 7 else ""
        seq_text = tds[0].get_text(strip=True) if tds else ""
        out.append(
            {
                "data_sid": m.group(1),
                "title": title,
                "is_notice": is_notice,
                "reg_date_text": reg_date_text,
                "seq_text": seq_text,
            }
        )
    return out


def _resolve_db_path() -> Path:
    env = (os.getenv("DB_PATH") or "").strip()
    if env:
        return Path(env)
    candidates = [
        Path.cwd() / "db" / "biz.db",
        _ROOT / "db" / "biz.db",
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
    backup_path = db_path.with_name(f"biz.db.backup_{ts}_053_jbtp_widget_{digest}")
    shutil.copy2(db_path, backup_path)
    print(f"[b053] DB 백업: {backup_path.name} (sha256={digest})", flush=True)
    return backup_path


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()}
    if "notice_chk" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_chk INTEGER DEFAULT 0")
        print("[b053] add column: biz_projects.notice_chk (INTEGER DEFAULT 0)", flush=True)
    if "notice_order" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_order INTEGER DEFAULT 0")
        print("[b053] add column: biz_projects.notice_order (INTEGER DEFAULT 0)", flush=True)


def _fetch_site_index() -> Dict[str, Dict[str, Any]]:
    """사이트 9페이지 fetch → {data_sid: {is_notice, reg_date, ...}}."""
    import time
    out: Dict[str, Dict[str, Any]] = {}
    for page_no in range(1, _MAX_PAGES + 1):
        try:
            html = _fetch_page(page_no)
        except Exception as e:
            print(f"[b053] page {page_no} fetch 실패: {e!r} → skip", flush=True)
            continue
        items = _parse_page(html)
        new_count = 0
        for it in items:
            sid = it["data_sid"]
            if sid in out:
                continue
            is_notice = bool(it.get("is_notice"))
            seq_raw = (it.get("seq_text") or "").strip()
            try:
                seq_int = int(seq_raw) if seq_raw and seq_raw.isdigit() else 0
            except (TypeError, ValueError):
                seq_int = 0
            # 정렬 키: 공지=dataSid, 일반=seq (사이트 표시 순서 일치)
            try:
                sid_int = int(sid)
            except (TypeError, ValueError):
                sid_int = 0
            order = sid_int if is_notice else (seq_int or sid_int)
            out[sid] = {
                "is_notice": is_notice,
                "reg_date": _normalize_date(it.get("reg_date_text", "")),
                "title": it.get("title", ""),
                "order": order,
            }
            new_count += 1
        print(f"[b053] page {page_no}: {len(items)}건 (신규 {new_count}건)", flush=True)
        if page_no < _MAX_PAGES:
            time.sleep(0.5)
    print(f"[b053] 사이트 인덱스 총: {len(out)}건", flush=True)
    return out


def _normalize_date(s: str) -> str:
    m = _DATE_RE.search(s or "")
    return m.group(1) if m else ""


def _backfill(
    conn: sqlite3.Connection,
    site_index: Dict[str, Dict[str, Any]],
    dry_run: bool,
) -> Dict[str, int]:
    cur = conn.execute(
        "SELECT id, url, start_date, notice_chk, notice_order "
        "FROM biz_projects WHERE source='jbtp'"
    )
    rows = cur.fetchall()
    print(f"[b053] DB jbtp row: {len(rows)}건", flush=True)

    matched = 0
    updated = 0
    unchanged = 0
    no_match: List[int] = []

    for rid, url, sd_old, nchk_old, nord_old in rows:
        m = _DATASID_RE.search(url or "")
        if not m:
            no_match.append(rid)
            continue
        sid = m.group(1)
        site = site_index.get(sid)
        if not site:
            no_match.append(rid)
            continue
        matched += 1

        # 새 값 산출 (백로그 049 머지 패턴: 새값 0 + 옛값 비-0 → 옛값 보존)
        new_nchk = 1 if site["is_notice"] else 0
        new_nord = int(site["order"])
        new_sd = site["reg_date"]

        sd_old_v = (sd_old or "").strip()
        merged_sd = new_sd if new_sd else sd_old_v
        merged_nchk = new_nchk
        try:
            old_nchk_int = int(nchk_old) if nchk_old is not None else 0
        except (TypeError, ValueError):
            old_nchk_int = 0
        # nchk: 사이트 fetch 가 권위 → 새 값 그대로. (jbexport 049 와 다름:
        # jbtp 는 사이트 fetch 자체가 신뢰할 수 있는 정렬 키 ground-truth)
        merged_nord = new_nord
        try:
            old_nord_int = int(nord_old) if nord_old is not None else 0
        except (TypeError, ValueError):
            old_nord_int = 0

        # 멱등성 체크
        if (
            merged_sd == sd_old_v
            and merged_nchk == old_nchk_int
            and merged_nord == old_nord_int
        ):
            unchanged += 1
            continue

        # DRY_RUN 도 UPDATE 실행 (시뮬레이션용) — 호출자가 ROLLBACK
        conn.execute(
            "UPDATE biz_projects SET "
            "start_date = ?, notice_chk = ?, notice_order = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (merged_sd, merged_nchk, merged_nord, rid),
        )
        updated += 1

    if no_match:
        print(f"[b053] 사이트에서 사라진 row {len(no_match)}건 (예: 깊은 페이지)", flush=True)

    return {
        "matched": matched,
        "updated": updated,
        "unchanged": unchanged,
        "no_match": len(no_match),
    }


def _print_distribution(conn: sqlite3.Connection, label: str) -> None:
    print(f"\n[b053] === {label} 분포 ===", flush=True)
    total = conn.execute("SELECT COUNT(*) FROM biz_projects WHERE source='jbtp'").fetchone()[0]
    nchk1 = conn.execute(
        "SELECT COUNT(*) FROM biz_projects WHERE source='jbtp' AND COALESCE(notice_chk,0)=1"
    ).fetchone()[0]
    sd_filled = conn.execute(
        "SELECT COUNT(*) FROM biz_projects WHERE source='jbtp' AND COALESCE(start_date,'')!=''"
    ).fetchone()[0]
    sd_2026 = conn.execute(
        "SELECT COUNT(*) FROM biz_projects WHERE source='jbtp' AND COALESCE(start_date,'')>='2026-01-01'"
    ).fetchone()[0]
    print(f"  total: {total}", flush=True)
    print(f"  notice_chk=1: {nchk1}", flush=True)
    print(f"  start_date 채워짐: {sd_filled}", flush=True)
    print(f"  start_date >= 2026-01-01: {sd_2026}", flush=True)


def _print_widget_top(conn: sqlite3.Connection, include_notices: bool) -> None:
    """현재 위젯 SQL 시뮬레이션 — 백필 후 분포 진단용."""
    where_extra = "" if include_notices else " AND COALESCE(notice_chk,0)=0"
    label = "공지 포함" if include_notices else "공지 제외"
    print(f"\n[b053] === 위젯 시뮬레이션 (top 5, {label}) ===", flush=True)
    cur = conn.execute(
        f"""
        SELECT id, notice_chk, notice_order, start_date, title
        FROM biz_projects
        WHERE source='jbtp'{where_extra}
          AND COALESCE(start_date,'') >= '2026-01-01'
        ORDER BY COALESCE(notice_chk,0) DESC,
                 COALESCE(notice_order,0) DESC,
                 COALESCE(created_at,'') DESC, id DESC
        LIMIT 5
        """
    )
    for rid, nchk, nord, sd, title in cur.fetchall():
        t = (title or "")[:50]
        print(f"  id={rid} chk={nchk} oder={nord} sd={sd} title={t!r}", flush=True)


def main() -> int:
    dry_run = os.getenv("DRY_RUN", "").strip() in ("1", "true", "True", "yes")
    db_path = _resolve_db_path()
    print(f"[b053] DB 경로: {db_path} (exists={db_path.exists()})", flush=True)
    print(f"[b053] DRY_RUN={dry_run}", flush=True)
    if not db_path.exists():
        print("[b053] DB 파일 없음 → 종료", flush=True)
        return 1

    if not dry_run:
        _backup_db(db_path)
    else:
        print("[b053] DRY_RUN → 백업 생략", flush=True)

    site_index = _fetch_site_index()
    if not site_index:
        print("[b053] 사이트 인덱스 0건 → 백필 중단", flush=True)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_columns(conn)
        _print_distribution(conn, "BEFORE")
        result = _backfill(conn, site_index, dry_run)
        # DRY_RUN: UPDATE 실행 → 분포/시뮬 출력 → ROLLBACK (DB 미반영)
        # apply: COMMIT
        _print_distribution(conn, "AFTER" if not dry_run else "AFTER (DRY_RUN 시뮬)")
        _print_widget_top(conn, include_notices=True)
        _print_widget_top(conn, include_notices=False)
        if dry_run:
            conn.rollback()
            print("[b053] DRY_RUN → ROLLBACK (DB 미반영)", flush=True)
        else:
            conn.commit()
    finally:
        conn.close()

    print(f"\n[b053] === 결과 ===", flush=True)
    print(f"  matched: {result['matched']}", flush=True)
    print(f"  updated: {result['updated']}", flush=True)
    print(f"  unchanged: {result['unchanged']}", flush=True)
    print(f"  no_match: {result['no_match']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
