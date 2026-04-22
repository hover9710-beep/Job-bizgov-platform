# -*- coding: utf-8 -*-
"""
pipeline/ui_view.py
===================

DB row → UI 전용 가공 레이어.

책임
  - biz_projects/projects 로부터 UI 전체 목록을 dict로 로드
  - 빈값(start_date, end_date, status, url…)을 그대로 허용 (필터는 UI 선택)
  - infer_status()로 상태 단일화 후 display_status 필드로 노출
  - 정렬(status / deadline / title / source / newest) + 다중 필터 제공
  - 각 단계마다 카운트·샘플 디버그 로그

메일 뷰(pipeline/mail_view.py)와 짝을 이루는 "UI 뷰" 계층 — status 단일 진입점은
pipeline/normalize_project.infer_status() 이며 presenter 의 display_* 포맷팅과 합류한다.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.normalize_project import infer_status
from pipeline.project_quality import canonical_notice_source
from pipeline.presenter import normalize_display_items
from pipeline.mail_view import display_url as _mail_display_url

DB_PATH = _ROOT / "db" / "biz.db"

# 정렬 우선순위: 접수중(0) > 확인 필요(1) > 마감(2)
_STATUS_ORDER = {"접수중": 0, "확인 필요": 1, "마감": 2}
_SOURCE_ORDER = {"jbexport": 0, "bizinfo": 1, "kstartup": 2}


# ---------------------------------------------------------------------------
# DB 로드
# ---------------------------------------------------------------------------

def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cols = {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    return col in cols


def load_db_rows(
    db_path: Path = DB_PATH,
    table: str = "biz_projects",
) -> List[Dict[str, Any]]:
    """projects/biz_projects 전체 행을 dict 리스트로. period_text 부재시 빈값 주입."""
    if not db_path.exists():
        print(f"[ui_view] DB 없음: {db_path}", flush=True)
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        has_pt = _has_column(conn, table, "period_text")
        has_site = _has_column(conn, table, "site")
        has_ca = _has_column(conn, table, "collected_at")
        has_ministry = _has_column(conn, table, "ministry")
        has_ea = _has_column(conn, table, "executing_agency")

        select_parts = [
            "id", "title", "organization",
            "source", "start_date", "end_date",
            "status", "url", "description",
        ]
        if has_site:
            select_parts.append("site")
        if has_ca:
            select_parts.append("collected_at")
        if has_ministry:
            select_parts.append("ministry")
        if has_ea:
            select_parts.append("executing_agency")
        select_parts.append(
            "COALESCE(period_text, '') AS period_text"
            if has_pt
            else "'' AS period_text"
        )

        sql = f"SELECT {', '.join(select_parts)} FROM {table}"
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = {k: (r[k] if r[k] is not None else "") for k in r.keys()}
        out.append(d)
    print(f"[ui_view] DB 로드: table={table} rows={len(out)}", flush=True)
    return out


# ---------------------------------------------------------------------------
# item 변환 (DB → UI dict)
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return date.today().isoformat()


def sqlite_row_to_item(row: Any) -> Dict[str, Any]:
    """
    DB row 또는 일반 dict → UI 표시용 dict.
    appy.py 호환 (dict·sqlite3.Row 모두 허용).
    url 은 mail_view.display_url() 규칙으로 치환 (kstartup 상세 → 목록 페이지).
    원본은 `raw_url` 로 보존.
    """
    d = dict(row) if not isinstance(row, dict) else dict(row)
    aj = d.get("attachments_json")
    if aj and not d.get("attachments"):
        try:
            parsed = json.loads(str(aj))
            if isinstance(parsed, list):
                d["attachments"] = parsed
        except Exception:
            pass
    d.setdefault("url", d.get("url") or "")
    d.setdefault("detail_url", d.get("detail_url") or "")
    snap = str(d.get("source") or "").strip()
    d["_db_source_snapshot"] = snap.lower()
    d["source"] = snap
    d["_source"] = (
        snap.upper()
        if snap
        else (canonical_notice_source(d) or "unknown").upper()
    )
    _apply_display_url(d)
    return d


def _apply_display_url(it: Dict[str, Any]) -> None:
    """
    UI 표시 URL 치환.
      - kstartup 상세(`bizpbanc-view.do?pbancSn=...`) 는 JS 렌더링에 의존해
        대부분 환경에서 빈 화면이 되므로 `bizpbanc-ongoing.do` 목록 페이지로 대체.
      - 원본 URL 은 `raw_url` 에 보존하여 DB/디버깅 용도로 유지.
      - mail_view.display_url() 과 동일 규칙 — 메일/UI 링크 표기를 통일.
    """
    raw = str(it.get("url") or "").strip()
    it.setdefault("raw_url", raw)
    it["url"] = _mail_display_url(it)


def to_ui_item(row: Dict[str, Any], today: Optional[str] = None) -> Dict[str, Any]:
    """
    DB row → UI dict. 빈값 허용.
    display_status 는 infer_status()로 결정, DB의 status 는 raw_status 로 보존.
    url 은 mail_view.display_url() 규칙으로 치환 (kstartup → 목록 페이지).
    """
    t = today or _today_str()
    d = sqlite_row_to_item(row)
    period_text = str(d.get("period_text") or "").strip()
    sd = str(d.get("start_date") or "").strip()
    ed = str(d.get("end_date") or "").strip()

    d["start_date"] = sd
    d["end_date"] = ed
    d["period_text"] = period_text
    d["raw_status"] = str(d.get("status") or "").strip()
    d["display_status"] = infer_status(period_text, sd, ed, t)
    d["source_badge"] = (d.get("_db_source_snapshot") or "").lower() or "unknown"
    _apply_display_url(d)
    return d


# ---------------------------------------------------------------------------
# 정렬
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> Optional[date]:
    if not s or len(s) < 10:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _sort_key_status(it: Dict[str, Any]) -> Tuple:
    st = _STATUS_ORDER.get(it.get("display_status") or "", 9)
    src = _SOURCE_ORDER.get((it.get("source_badge") or "").lower(), 9)
    e = _parse_iso(it.get("end_date") or "")
    e_ord = e.toordinal() if e else 10**9
    return (st, src, e_ord, it.get("title") or "")


def _sort_key_deadline(it: Dict[str, Any]) -> Tuple:
    e = _parse_iso(it.get("end_date") or "")
    # end_date 없는 항목은 가장 뒤로
    return (0 if e else 1, e.toordinal() if e else 10**9, it.get("title") or "")


def _sort_key_title(it: Dict[str, Any]) -> Tuple:
    return (str(it.get("title") or ""),)


def _sort_key_source(it: Dict[str, Any]) -> Tuple:
    src = _SOURCE_ORDER.get((it.get("source_badge") or "").lower(), 9)
    return (src, str(it.get("title") or ""))


def _sort_key_newest(it: Dict[str, Any]) -> Tuple:
    s = _parse_iso(it.get("start_date") or "")
    # 최신(시작일 큰) 순 = 시작일 역순. 없으면 뒤로.
    return (0 if s else 1, -(s.toordinal() if s else 0), it.get("title") or "")


_SORT_KEYS = {
    "status": _sort_key_status,
    "deadline": _sort_key_deadline,
    "title": _sort_key_title,
    "source": _sort_key_source,
    "newest": _sort_key_newest,
}


def sort_items(
    items: List[Dict[str, Any]],
    key: str = "status",
) -> List[Dict[str, Any]]:
    """UI용 정렬. 지원하지 않는 key는 'status'로 폴백."""
    fn = _SORT_KEYS.get(key) or _SORT_KEYS["status"]
    if key not in _SORT_KEYS:
        print(f"[ui_view] 미지원 sort key={key!r} → 'status' 폴백", flush=True)
    return sorted(items, key=fn)


# ---------------------------------------------------------------------------
# 필터 (빈값 허용 — 미지정 필드는 통과)
# ---------------------------------------------------------------------------

def filter_items(
    items: Iterable[Dict[str, Any]],
    *,
    source: str = "",
    status: str = "",
    q: str = "",
    only_has_deadline: bool = False,
) -> List[Dict[str, Any]]:
    """
    source, status, q(제목/기관 부분검색) 조건으로 필터.
    빈 값/미지정은 통과. only_has_deadline=True 이면 end_date 가 있는 항목만.
    """
    src_filter = (source or "").strip().lower()
    st_filter = (status or "").strip()
    q_norm = (q or "").strip().lower()

    out: List[Dict[str, Any]] = []
    for it in items:
        if src_filter and (it.get("source_badge") or "").lower() != src_filter:
            continue
        if st_filter and (it.get("display_status") or "") != st_filter:
            continue
        if q_norm:
            hay = f"{it.get('title') or ''} {it.get('organization') or ''}".lower()
            if q_norm not in hay:
                continue
        if only_has_deadline and not (it.get("end_date") or ""):
            continue
        out.append(it)
    return out


# ---------------------------------------------------------------------------
# 디버그 로그 (구간별 카운트 + 샘플)
# ---------------------------------------------------------------------------

def _log_status_counts(items: List[Dict[str, Any]]) -> None:
    by_st: Dict[str, int] = {}
    for it in items:
        st = it.get("display_status") or "(empty)"
        by_st[st] = by_st.get(st, 0) + 1
    print("[ui_view] status counts:", by_st, flush=True)


def _log_source_counts(items: List[Dict[str, Any]]) -> None:
    by_src: Dict[str, int] = {}
    for it in items:
        s = (it.get("source_badge") or "unknown")
        by_src[s] = by_src.get(s, 0) + 1
    print("[ui_view] source counts:", by_src, flush=True)


def _log_top_sample(items: List[Dict[str, Any]], n: int = 5) -> None:
    print(f"[ui_view] top {n} samples:", flush=True)
    for it in items[:n]:
        print(
            f"  - [{(it.get('source_badge') or '?').upper():8s}] "
            f"{(it.get('display_status') or '-'):6s} "
            f"{(it.get('start_date') or '-'):10s} ~ "
            f"{(it.get('end_date') or '-'):10s} "
            f"| {(it.get('title') or '')[:70]}",
            flush=True,
        )


# ---------------------------------------------------------------------------
# 공개 API (appy.py 호환 + 신규 UI 뷰)
# ---------------------------------------------------------------------------

def prepare_db_rows_for_ui(
    rows: Iterable[Any],
    *,
    sort: str = "status",
    today: Optional[str] = None,
    audit: bool = True,
) -> List[Dict[str, Any]]:
    """
    DB rows(sqlite.Row 또는 dict) → 정렬된 UI dict 리스트.
    appy.py 가 직접 호출하는 공개 API. UI 라우트에서 바로 사용.

    처리 순서
      1) sqlite_row_to_item 으로 기본 dict 화
      2) presenter.normalize_display_items 로 display_receipt_*/display_biz_* 생성
         (display_status 는 presenter 내부에서 infer_status 로 위임됨)
      3) 호출자 지정 today 기준 infer_status 재평가 — 일일 리빌드 안전망
      4) 정렬 + display_idx 부여
    """
    t = today or _today_str()
    dicts = [dict(r) if not isinstance(r, dict) else r for r in rows]
    items: List[Dict[str, Any]] = [sqlite_row_to_item(r) for r in dicts]
    items = normalize_display_items(items)
    for it in items:
        period_text = str(it.get("period_text") or "").strip()
        sd = str(it.get("start_date") or "").strip()
        ed = str(it.get("end_date") or "").strip()
        it["raw_status"] = str(it.get("status") or "").strip()
        it["display_status"] = infer_status(period_text, sd, ed, t)
        it.setdefault("source_badge", (it.get("_db_source_snapshot") or "").lower() or "unknown")
        _apply_display_url(it)
    # 4) 정렬
    items = sort_items(items, key=sort)
    for i, it in enumerate(items, start=1):
        it["display_idx"] = i

    if audit:
        print(f"[ui_view] prepared rows={len(items)} sort={sort!r} today={t}", flush=True)
        _log_status_counts(items)
        _log_source_counts(items)
        _log_top_sample(items, n=5)
    return items


def prepare_json_items_for_ui(
    raw_items: Iterable[Dict[str, Any]],
    *,
    sort: str = "status",
    today: Optional[str] = None,
    audit: bool = True,
) -> List[Dict[str, Any]]:
    """JSON(예: all_jb.json) 아이템 리스트 → UI dict 리스트."""
    dicts = [r for r in raw_items if isinstance(r, dict)]
    return prepare_db_rows_for_ui(dicts, sort=sort, today=today, audit=audit)


# ---------------------------------------------------------------------------
# CLI (샘플 덤프 확인용)
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="DB → UI 뷰 덤프 (ui_view)")
    parser.add_argument("--sort", default="status", help="정렬 키: status|deadline|title|source|newest")
    parser.add_argument("--source", default="", help="source 필터")
    parser.add_argument("--status", default="", help="display_status 필터")
    parser.add_argument("--q", default="", help="제목·기관 부분검색")
    parser.add_argument("--limit", type=int, default=10, help="표시 건수")
    args = parser.parse_args()

    rows = load_db_rows()
    items = prepare_db_rows_for_ui(rows, sort=args.sort)
    items = filter_items(items, source=args.source, status=args.status, q=args.q)
    print(f"[ui_view] 필터 후 {len(items)}건", flush=True)
    _log_top_sample(items, n=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
