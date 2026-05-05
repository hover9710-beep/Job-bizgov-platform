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
# UI pipeline transforms DB rows only.
# No crawling, downloading, or text extraction here.
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.normalize_project import infer_status
from pipeline.project_quality import canonical_notice_source
from pipeline.presenter import normalize_display_items

# kstartup 상세 URL(JS 렌더링 의존) 열림 실패 대비 — 보조 목록 페이지 URL.
# 메일뷰와 동일 상수를 사용해 표기 일관성 유지 (덮어쓰지 않고 병행 표시).
_KSTARTUP_LIST_URL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"

DB_PATH = _ROOT / "db" / "biz.db"

# 정렬 우선순위: 접수중(0) > 확인 필요(1) > 마감(2)
_STATUS_ORDER = {"접수중": 0, "확인 필요": 1, "마감": 2}
_SOURCE_ORDER = {"jbexport": 0, "bizinfo": 1, "kstartup": 2}

# UI 표기용 소스 한글 라벨. appy.SOURCE_LABELS 와 동기화 유지.
SOURCE_LABELS = {
    "jbexport": "전북수출",
    "bizinfo": "기업마당",
    "kstartup": "K-Startup",
    "jbtp": "전북TP",
    "jbbi": "전북바이오",
    "jbtp_related": "JBTP유관",
    "at_global": "aT글로벌",
}

# 마감임박 배지 임계값(일 단위). D-3 이하는 danger(빨강), D-7 이하는 warn(주황).
_DEADLINE_DANGER_DAYS = 3
_DEADLINE_WARN_DAYS = 7


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
        has_aj = _has_column(conn, table, "attachments_json")
        select_parts.append(
            "COALESCE(attachments_json, '') AS attachments_json"
            if has_aj
            else "'' AS attachments_json"
        )
        has_as = _has_column(conn, table, "ai_summary")
        has_as_at = _has_column(conn, table, "ai_summary_at")
        select_parts.append(
            "COALESCE(ai_summary, '') AS ai_summary"
            if has_as
            else "'' AS ai_summary"
        )
        select_parts.append(
            "COALESCE(ai_summary_at, '') AS ai_summary_at"
            if has_as_at
            else "'' AS ai_summary_at"
        )
        has_rl = _has_column(conn, table, "recommend_label")
        has_rl_at = _has_column(conn, table, "recommend_label_at")
        select_parts.append(
            "COALESCE(recommend_label, '') AS recommend_label"
            if has_rl
            else "'' AS recommend_label"
        )
        select_parts.append(
            "COALESCE(recommend_label_at, '') AS recommend_label_at"
            if has_rl_at
            else "'' AS recommend_label_at"
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
    kstartup 은 `url` 을 목록 페이지(`bizpbanc-ongoing.do`)로 치환하고
    원본은 `raw_url` 로 보존한다. 그 외 소스는 원본 그대로 유지.
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
    # presenter.normalize_display_item 이 ai_summary 를 덮어쓰므로 DB 원본 보존용
    d["_db_ai_summary"] = str(d.get("ai_summary") or "").strip()
    d["_db_ai_summary_at"] = str(d.get("ai_summary_at") or "").strip()
    return d


def build_recommend_reason(item: dict) -> str:
    try:
        label = item.get("recommend_label", "") or ""
        source = item.get("source", "") or ""
        ai_summary = item.get("ai_summary", "") or ""
        badge = item.get("deadline_badge", "") or ""

        parts: List[str] = []

        prefix = (
            "전북 수출기업 기준으로, "
            if str(source).strip().lower() == "jbexport"
            else ""
        )

        if str(label).strip():
            label_sentence = f"{str(label).strip()}이 검토할 만한 공고입니다."
            parts.append(prefix + label_sentence)
        elif str(ai_summary).strip():
            parts.append("AI 요약 기준으로 검토할 만한 공고입니다.")
        else:
            return ""

        if badge in ("D-0", "D-1", "D-2", "D-3", "D-Day"):
            parts.append("마감이 임박해 우선 확인이 필요합니다.")

        result = " ".join(parts)
        return result[:120]
    except Exception:
        return ""


def _apply_display_url(it: Dict[str, Any]) -> None:
    """
    UI 표시 URL 치환.
      - kstartup 상세(`bizpbanc-view.do?pbancSn=...`) 는 로그인/세션 없이는
        렌더링이 불가해 사실상 항상 빈 화면이 된다. → `url` 을 목록 페이지
        (`bizpbanc-ongoing.do`) 로 완전 치환. 원본은 `raw_url` 에 보존.
      - 비-kstartup 소스는 원본 URL 유지.
    """
    src = (it.get("source") or "").lower()
    raw = str(it.get("url") or "").strip()
    it.setdefault("raw_url", raw)
    if src == "kstartup":
        it["url"] = _KSTARTUP_LIST_URL


def to_ui_item(row: Dict[str, Any], today: Optional[str] = None) -> Dict[str, Any]:
    """
    DB row → UI dict. 빈값 허용.
    display_status 는 infer_status()로 결정, DB의 status 는 raw_status 로 보존.
    kstartup 의 `url` 은 목록 페이지로 치환(원본은 `raw_url`).
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
    asum = str(d.get("_db_ai_summary") or "").strip()
    asat = str(d.get("_db_ai_summary_at") or "").strip()
    d["ai_summary"] = asum
    d["ai_summary_at"] = asat
    d["has_ai_summary"] = bool(asum)
    rl = str(d.get("recommend_label") or "").strip()
    d["recommend_label"] = rl
    d["has_recommend_label"] = bool(rl)
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


def _source_label(source_key: str) -> str:
    """소스 키(소문자) → 한글 라벨. 미지정/미매핑은 원문 그대로."""
    key = (source_key or "").strip().lower()
    return SOURCE_LABELS.get(key, source_key or "")


def _compute_deadline_badge(
    display_status: str,
    end_date_s: str,
    today: date,
) -> Tuple[str, str]:
    """
    (deadline_badge, deadline_class) 계산.

    규칙
      - display_status == '마감' → ('마감', 'deadline-danger')
      - end_date 미지정 → ('', '')
      - 오늘 기준 잔여일 d:
          d <  0            → ('마감', 'deadline-danger')  # 방어적 처리
          d <= DANGER(3)    → ('D-{d}', 'deadline-danger')
          d <= WARN(7)      → ('D-{d}', 'deadline-warn')
          그 외             → ('', '')
    """
    if display_status == "마감":
        return ("마감", "deadline-danger")
    ed = _parse_iso(end_date_s or "")
    if ed is None:
        return ("", "")
    d = (ed - today).days
    if d < 0:
        return ("마감", "deadline-danger")
    if d <= _DEADLINE_DANGER_DAYS:
        return (f"D-{d}", "deadline-danger")
    if d <= _DEADLINE_WARN_DAYS:
        return (f"D-{d}", "deadline-warn")
    return ("", "")


def _parse_attachments_row(it: Dict[str, Any]) -> List[Any]:
    """DB/UI dict에서 첨부 메타 리스트. mail_view._parse_attachments 와 동일 규칙."""
    if not isinstance(it, dict):
        return []
    val = it.get("attachments_json")
    if val is None:
        val = it.get("attachments")
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    s = str(val).strip()
    if not s or s == "[]":
        return []
    try:
        parsed = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    return []


def _attachment_summary_for_ui(parsed: List[Any]) -> Tuple[int, str, bool]:
    if not parsed:
        return 0, "", False
    names: List[str] = []
    for x in parsed:
        if isinstance(x, dict):
            n = str(x.get("name") or "").strip()
            if n:
                names.append(n)
        elif isinstance(x, str):
            t = x.strip()
            if t:
                names.append(t)
    count = len(parsed)
    if not names:
        return count, "", True
    if len(names) == 1:
        return count, names[0], True
    return count, f"{names[0]} 외 {len(names) - 1}건", True


def _apply_ui_labels(it: Dict[str, Any], today: date) -> None:
    """
    UI 표시 전용 파생 필드 주입 (프레젠테이션 레이어 한정).
      - source_label    : 소스 키 → 한글 라벨
      - deadline_badge  : 'D-3' / 'D-7' / '마감' / ''
      - deadline_class  : CSS 클래스 ('deadline-danger' / 'deadline-warn' / '')

    status 및 url 은 건드리지 않는다 (각각 infer_status / _apply_display_url 담당).
    """
    src_key = (it.get("_db_source_snapshot") or it.get("source") or "").strip().lower()
    it["source_label"] = _source_label(src_key)
    badge, cls = _compute_deadline_badge(
        display_status=str(it.get("display_status") or "").strip(),
        end_date_s=str(it.get("end_date") or "").strip(),
        today=today,
    )
    it["deadline_badge"] = badge
    it["deadline_class"] = cls


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

_DEADLINE_URGENT_BADGE = re.compile(r"^D-[0-3]$")

# category= 키 → 본문 부분일치 키워드 (소문자 비교는 ASCII 구간만 변화, 한글은 그대로)
CATEGORY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "export": ("수출", "해외", "FTA", "바이어", "무역", "통상"),
    "marketing": ("마케팅", "홍보", "브랜딩", "판로", "시장개척"),
    "expo": ("전시", "박람회", "상담회", "사절단"),
    "consulting": ("컨설팅", "전문가", "애로", "자문"),
    "cert": ("인증", "시험", "규격", "검사", "CE", "FDA"),
    "logistics": ("물류", "특송", "운송", "샘플", "발송"),
    "startup": ("창업", "스타트업", "보육", "입주", "IR"),
    "education": ("교육", "세미나", "아카데미", "역량강화"),
}


def _norm_filter_str(val: Optional[str]) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _item_matches_urgent_deadline(it: Dict[str, Any], today_d: date) -> bool:
    if (it.get("display_status") or "") != "접수중":
        return False
    badge = str(it.get("deadline_badge") or "").strip()
    if _DEADLINE_URGENT_BADGE.match(badge):
        return True
    ed = _parse_iso(str(it.get("end_date") or ""))
    if ed is None:
        return False
    dleft = (ed - today_d).days
    return 0 <= dleft <= 3


def _item_matches_category(it: Dict[str, Any], cat_key: str) -> bool:
    keywords = CATEGORY_KEYWORDS.get(cat_key.lower())
    if not keywords:
        return True
    parts = [
        str(it.get("title") or ""),
        str(it.get("ai_summary") or ""),
        str(it.get("recommend_label") or ""),
        str(it.get("description") or ""),
    ]
    text = "".join(parts).lower()
    return any(k.lower() in text for k in keywords)


def filter_items(
    items: Iterable[Dict[str, Any]],
    *,
    source: str = "",
    status: str = "",
    q: str = "",
    only_has_deadline: bool = False,
    deadline: Optional[str] = None,
    recent: Optional[str] = None,
    has_ai_summary: Optional[str] = None,
    has_recommend_label: Optional[str] = None,
    has_attachments: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    source, status, q(제목/기관 부분검색) 조건으로 필터.
    빈 값/미지정은 통과. only_has_deadline=True 이면 end_date 가 있는 항목만.

    추가: deadline=urgent, recent=7, has_ai_summary=1, has_recommend_label=1,
    has_attachments=1, category=export|marketing|...
    """
    src_filter = (source or "").strip().lower()
    st_filter = (status or "").strip()
    q_norm = (q or "").strip().lower()
    dl = _norm_filter_str(deadline)
    rc = _norm_filter_str(recent)
    has_sum = _norm_filter_str(has_ai_summary)
    has_rec = _norm_filter_str(has_recommend_label)
    has_att = _norm_filter_str(has_attachments)
    cat = _norm_filter_str(category)

    today_d = date.today()

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
        if dl == "urgent" and not _item_matches_urgent_deadline(it, today_d):
            continue
        if rc == "7":
            sd = _parse_iso(str(it.get("start_date") or ""))
            if sd is None or sd < today_d - timedelta(days=7):
                continue
        if has_sum == "1" and not str(it.get("ai_summary") or "").strip():
            continue
        if has_rec == "1" and not str(it.get("recommend_label") or "").strip():
            continue
        if has_att == "1" and it.get("has_attachments") is not True:
            continue
        if cat and not _item_matches_category(it, cat):
            continue
        out.append(it)
    return dedupe_items_for_ui(out)


def normalize_text_for_dedupe(v: Any) -> str:
    """UI 목록 중복 제거용: 공백·대소문자·대괄호 등 사소한 차이 축소 (source는 키에 넣지 않음)."""
    s = str(v or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[\[\]]", "", s)
    s = s.replace(" ", "")
    return s


def dedupe_items_for_ui(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[Tuple[str, str, str, str]] = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        org = it.get("organization") or it.get("executing_agency")
        key = (
            normalize_text_for_dedupe(it.get("title")),
            normalize_text_for_dedupe(org),
            str(it.get("start_date") or ""),
            str(it.get("end_date") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def sort_recommend_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    추천 탭 정렬: 마감임박(D-0~3) → recommend_label → ai_summary → jbexport → end_date 빠른 순.
    """
    today_d = date.today()

    def sort_key(it: Dict[str, Any]) -> Tuple[int, int, int, int, date, int]:
        urgent = (
            0
            if _item_matches_urgent_deadline(it, today_d)
            or _DEADLINE_URGENT_BADGE.match(
                str(it.get("deadline_badge") or "").strip()
            )
            else 1
        )
        rl = 0 if str(it.get("recommend_label") or "").strip() else 1
        ai = 0 if str(it.get("ai_summary") or "").strip() else 1
        jb = 0 if (it.get("source_badge") or "").lower() == "jbexport" else 1
        ed = _parse_iso(str(it.get("end_date") or ""))
        ed_sort = ed if ed is not None else date(9999, 12, 31)
        iid = int(it.get("id") or 0)
        return (urgent, rl, ai, jb, ed_sort, iid)

    return sorted(items, key=sort_key)


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


def clean_display_title(title: Any, fallback: str = "공고 상세보기") -> str:
    s = str(title or "").strip()
    if not s:
        return fallback
    low = s.lower()
    if low.startswith("spseq="):
        return fallback
    if "spseq=" in low and len(s) < 80:
        return fallback
    return s


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
    t_date = datetime.strptime(t[:10], "%Y-%m-%d").date() if len(t) >= 10 else date.today()
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
        _apply_ui_labels(it, t_date)
        att_parsed = _parse_attachments_row(it)
        acount, asumm, has_att = _attachment_summary_for_ui(att_parsed)
        it["attachment_count"] = acount
        it["attachment_summary"] = asumm
        it["has_attachments"] = has_att
        asum = str(it.get("_db_ai_summary") or "").strip()
        asat = str(it.get("_db_ai_summary_at") or "").strip()
        it["ai_summary"] = asum
        it["ai_summary_at"] = asat
        it["has_ai_summary"] = bool(asum)
        rl = str(it.get("recommend_label") or "").strip()
        it["recommend_label"] = rl
        it["has_recommend_label"] = bool(rl)
        it["recommend_reason"] = build_recommend_reason(it)
        it["display_title"] = clean_display_title(it.get("title"))
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
