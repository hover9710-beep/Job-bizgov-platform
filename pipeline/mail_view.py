# -*- coding: utf-8 -*-
"""
pipeline/mail_view.py
=====================

DB row → 메일 전용 가공 레이어.

책임
  - biz_projects/projects 로부터 공고 목록을 로드
  - infer_status()로 상태를 단일화 (접수중 / 마감 / 확인 필요)
  - 메일 3섹션 필터 제공: 신규공고 / 마감임박 / 접수중
  - 본문이 너무 길면 상한까지 안전 절단

UI 가공(정렬·디버그·빈값 허용)과는 별도 모듈.
실행 시 data/mail/mail_body.txt 파일로 바로 본문 저장.
"""
from __future__ import annotations

import argparse
import calendar
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.normalize_project import infer_status

DB_PATH = _ROOT / "db" / "biz.db"
OUT_FILE = _ROOT / "data" / "mail" / "mail_body.txt"

# 메일 본문 최대 길이 (Gmail/일반 SMTP 본문 안전선)
MAX_BODY_CHARS = 60_000
# 섹션당 최대 항목 수 (가독성)
NEW_LIMIT = 40
ENDING_LIMIT = 40
ACTIVE_LIMIT = 60

SECTION_SEP = "-" * 40

# 섹션별 소스 다양성 보장: 각 소스가 섹션 내 최소 이 건수는 차지하도록 쿼터 확보.
SOURCE_MIN_QUOTA = 5
# 메일 표시용 URL 치환 (직접 링크가 JS 렌더링에 의존해 빈 화면이 되는 소스는 목록 페이지로).
_KSTARTUP_FALLBACK_URL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"


# ---------------------------------------------------------------------------
# 날짜 정규화 (jbexport 의 한국어 기간 문자열 → ISO)
# ---------------------------------------------------------------------------

_RE_ISO_DAY = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
_RE_ISO_MONTH = re.compile(r"(\d{4})[-./](\d{1,2})")
_RE_KOR_YM = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?")
_RE_KOR_MONTH_ONLY = re.compile(r"(?<!\d)(\d{1,2})\s*월")


def _end_of_month(y: int, m: int) -> int:
    try:
        return calendar.monthrange(y, m)[1]
    except ValueError:
        return 28


def normalize_date(raw: str, kind: str = "end", *, year_hint: Optional[int] = None) -> str:
    """
    자유 형식 날짜 문자열 → 'YYYY-MM-DD' (kind='start' 이면 월초, 'end' 면 월말).
    파싱 불가하면 "" 반환. 연도 없는 '12월' 은 year_hint(기본 올해) 로 보강.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""

    # 1) 일단위 ISO/점/슬래시
    m = _RE_ISO_DAY.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # 2) 한국어 'YYYY년 M월 [D일]'
    m = _RE_KOR_YM.search(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        d_str = m.group(3)
        if 1 <= mo <= 12:
            if d_str:
                d = int(d_str)
                if 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            d = 1 if kind == "start" else _end_of_month(y, mo)
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # 3) 월단위 ISO 'YYYY-MM', '2026. 11.', '2026/11'
    m = _RE_ISO_MONTH.search(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            d = 1 if kind == "start" else _end_of_month(y, mo)
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # 4) '12월' 같이 연도 없는 한국어 월 — year_hint 보강
    m = _RE_KOR_MONTH_ONLY.search(s)
    if m:
        mo = int(m.group(1))
        if 1 <= mo <= 12:
            y = year_hint if year_hint is not None else date.today().year
            d = 1 if kind == "start" else _end_of_month(y, mo)
            return f"{y:04d}-{mo:02d}-{d:02d}"

    return ""


# ---------------------------------------------------------------------------
# DB 로드
# ---------------------------------------------------------------------------

def _ensure_period_text_column(conn: sqlite3.Connection) -> bool:
    cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()}
    return "period_text" in cols


def load_db_rows(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """biz_projects 전체 행을 dict 리스트로 반환. period_text 컬럼 유무 자동 대응."""
    if not db_path.exists():
        print(f"[mail_view] DB 없음: {db_path}", flush=True)
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        has_pt = _ensure_period_text_column(conn)
        pt_expr = "COALESCE(period_text, '') AS period_text" if has_pt else "'' AS period_text"
        sql = f"""
            SELECT
                id, title, organization, source,
                start_date, end_date, status, url, description,
                {pt_expr}
            FROM biz_projects
        """
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({k: (r[k] if r[k] is not None else "") for k in r.keys()})
    return out


# ---------------------------------------------------------------------------
# 메일 item 변환 + 상태
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return date.today().isoformat()


def to_mail_item(row: Dict[str, Any], today: Optional[str] = None) -> Dict[str, Any]:
    """DB row → 메일에서 쓰는 최소 필드 dict. infer_status()로 상태 단일화.

    start_date/end_date 는 jbexport 의 한국어 기간 문자열('2026년 11월', '2026. 1.')도
    ISO로 정규화. infer_status, 섹션 필터, 정렬 모두 같은 기준으로 돌게 된다.
    원본은 raw_start_date/raw_end_date 에 보존.

    kstartup 상세(`bizpbanc-view.do?pbancSn=...`) 는 로그인·세션 없이는
    렌더 불가이므로 `url` 을 아예 목록 페이지(`bizpbanc-ongoing.do`) 로 치환한다.
    원본은 `raw_url` 에 보존.
    """
    t = today or _today_str()
    period_text = str(row.get("period_text") or "").strip()
    raw_start = str(row.get("start_date") or "").strip()
    raw_end = str(row.get("end_date") or "").strip()

    start_date = normalize_date(raw_start, kind="start")
    end_date = normalize_date(raw_end, kind="end")

    src = str(row.get("source") or "").strip().lower() or "unknown"
    raw_url = str(row.get("url") or "").strip()
    url = _KSTARTUP_FALLBACK_URL if src == "kstartup" else raw_url

    return {
        "id": row.get("id"),
        "title": str(row.get("title") or "").strip(),
        "organization": str(row.get("organization") or "").strip(),
        "source": src,
        "start_date": start_date,
        "end_date": end_date,
        "raw_start_date": raw_start,
        "raw_end_date": raw_end,
        "period_text": period_text,
        "url": url,
        "raw_url": raw_url,
        "description": str(row.get("description") or "").strip(),
        "status": infer_status(period_text, start_date, end_date, t),
    }


def _parse_iso(s: str) -> Optional[date]:
    if not s or len(s) < 10:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 필터
# ---------------------------------------------------------------------------

def filter_new(items: Iterable[Dict[str, Any]], days: int = 7, today: Optional[str] = None) -> List[Dict[str, Any]]:
    """start_date 가 최근 N일 이내. 날짜 없으면 제외."""
    t = _parse_iso(today or _today_str())
    if t is None:
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        s = _parse_iso(it.get("start_date") or "")
        if s is None:
            continue
        if 0 <= (t - s).days <= days:
            out.append(it)
    return out


def filter_ending_soon(
    items: Iterable[Dict[str, Any]],
    days: int = 7,
    today: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """end_date 가 오늘로부터 N일 이내(오늘 포함). 이미 지난 건 제외."""
    t = _parse_iso(today or _today_str())
    if t is None:
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        e = _parse_iso(it.get("end_date") or "")
        if e is None:
            continue
        delta = (e - t).days
        if 0 <= delta <= days:
            out.append(it)
    return out


def filter_active(
    items: Iterable[Dict[str, Any]],
    today: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """infer_status()가 '접수중' 인 항목. '확인 필요'는 제외(메일 노이즈 방지)."""
    return [it for it in items if it.get("status") == "접수중"]


# ---------------------------------------------------------------------------
# 포맷팅
# ---------------------------------------------------------------------------

def _fmt_period(it: Dict[str, Any]) -> str:
    sd = it.get("start_date") or ""
    ed = it.get("end_date") or ""
    if sd and ed:
        return f"{sd} ~ {ed}"
    if sd or ed:
        return sd or ed
    pt = it.get("period_text") or ""
    return pt[:60] if pt else "-"


def _dedupe_by_url_title(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """URL 기준 중복 제거.

    kstartup 처럼 표시 URL 을 목록 페이지로 통일해 `url` 이 모두 동일한 소스는
    `raw_url` (원본 상세 URL) 로 중복을 식별한다. 그래도 없으면 title+기관.
    """
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        key = (
            it.get("raw_url")
            or it.get("url")
            or f"{it.get('title')}|{it.get('organization')}"
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def display_url(it: Dict[str, Any]) -> str:
    """메일/카카오 표시용 URL.

    kstartup 은 `to_mail_item()` 단계에서 이미 목록 페이지 URL 로 치환되어 있으므로
    여기서는 단순히 `url` 을 그대로 반환. 방어적으로 source=kstartup 인데 원본
    상세 URL 이 들어온 케이스도 치환한다 (과거 데이터 호환).
    """
    url = (it.get("url") or "").strip()
    src = (it.get("source") or "").lower()
    if src == "kstartup" and "bizpbanc-view.do" in url:
        return _KSTARTUP_FALLBACK_URL
    return url


def _take_with_source_quota(
    items: List[Dict[str, Any]],
    limit: int,
    min_per_source: int = SOURCE_MIN_QUOTA,
) -> List[Dict[str, Any]]:
    """
    상위 limit 건을 뽑되, 각 소스가 최소 min_per_source 건씩 포함되도록 쿼터 보장.
    items 는 이미 원하는 순서로 정렬되어 있어야 함(예: end_date 임박 순).
    """
    if limit <= 0 or not items:
        return []

    by_src: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by_src.setdefault(it.get("source") or "unknown", []).append(it)

    picked: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for src, bucket in by_src.items():
        for it in bucket[:min_per_source]:
            key = id(it)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            picked.append(it)
            if len(picked) >= limit:
                break
        if len(picked) >= limit:
            break

    if len(picked) < limit:
        for it in items:
            key = id(it)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            picked.append(it)
            if len(picked) >= limit:
                break

    picked.sort(
        key=lambda x: (
            0 if x.get("end_date") else 1,
            x.get("end_date") or "9999-12-31",
        )
    )
    return picked[:limit]


def format_section(
    title: str,
    icon: str,
    items: List[Dict[str, Any]],
    limit: int,
    show_dday: bool = False,
    today: Optional[str] = None,
) -> str:
    """한 섹션 본문. 비어 있으면 '해당 공고 없음'.

    - 중복 제거 후 소스별 최소 쿼터(SOURCE_MIN_QUOTA)로 다양성 보장
    - URL 은 display_url() 로 치환 (kstartup 상세 → 목록 페이지)
    """
    lines: List[str] = [f"{icon} {title} ({len(items)}건)"]
    if not items:
        lines.append("  해당 공고 없음")
        return "\n".join(lines)

    items = _dedupe_by_url_title(items)
    picked = _take_with_source_quota(items, limit=limit)

    # 섹션 소스 구성 디버그 로그
    from collections import Counter

    counts = Counter((x.get("source") or "unknown") for x in picked)
    print(f"[mail_view] section={title!r} picked={len(picked)} by_source={dict(counts)}", flush=True)

    t = _parse_iso(today or _today_str())

    for i, it in enumerate(picked, start=1):
        src = (it.get("source") or "unknown").upper()
        ttl = it.get("title") or "(제목없음)"
        org = it.get("organization") or "-"
        url = display_url(it) or "-"
        period = _fmt_period(it)

        dday_txt = ""
        if show_dday and t is not None:
            e = _parse_iso(it.get("end_date") or "")
            if e is not None:
                d = (e - t).days
                dday_txt = f" (D-{d})" if d >= 0 else f" (마감 {abs(d)}일 지남)"

        lines.append(f"{i}. [{src}] {ttl}")
        lines.append(f"   기관: {org}")
        lines.append(f"   기간: {period}{dday_txt}")
        lines.append(f"   링크: {url}")
        lines.append("")

    leftover = len(items) - len(picked)
    if leftover > 0:
        lines.append(f"… 외 {leftover}건 (전체 목록은 사이트에서 확인)")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# 본문 빌더 + 안전 절단
# ---------------------------------------------------------------------------

def truncate_body(body: str, max_chars: int = MAX_BODY_CHARS) -> str:
    """상한을 넘으면 잘라내고 '[본문 길이 제한으로 절단됨]' 꼬리 추가."""
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars].rstrip()
    return cut + f"\n\n… [본문 길이 제한으로 절단됨: {len(body)-max_chars:,}자 생략]\n"


def _count_by_source(items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """단계별 진단을 위한 소스별 카운트. 빈 소스는 'unknown'."""
    out: Dict[str, int] = {}
    for it in items:
        src = (it.get("source") or "unknown").lower() or "unknown"
        out[src] = out.get(src, 0) + 1
    return out


def build_mail_body(
    rows: Optional[List[Dict[str, Any]]] = None,
    today: Optional[str] = None,
    *,
    new_days: int = 7,
    ending_days: int = 7,
) -> str:
    """
    3개 섹션(신규/마감임박/접수중)을 이어 붙여 본문 문자열 반환.
    rows 미지정 시 DB에서 직접 로드.

    단계별 소스 카운트를 [stage*] 프리픽스로 로그에 남겨
    어느 단계에서 소스가 사라지는지 추적 가능.
    """
    t = today or _today_str()
    if rows is None:
        rows = load_db_rows()

    # stage1: load_db_rows 직후 — 소스별 원본 카운트
    print(f"[mail_view] today={t} rows={len(rows)} items(raw)={len(rows)}", flush=True)
    print(f"[mail_view][stage1 load_db_rows] by_source={_count_by_source(rows)}", flush=True)

    items = [to_mail_item(r, today=t) for r in rows]
    print(f"[mail_view][stage2 to_mail_item] by_source={_count_by_source(items)}", flush=True)

    new_items = filter_new(items, days=new_days, today=t)
    print(f"[mail_view][stage3 filter_new] by_source={_count_by_source(new_items)}", flush=True)

    ending_items = filter_ending_soon(items, days=ending_days, today=t)
    print(f"[mail_view][stage4 filter_ending_soon] by_source={_count_by_source(ending_items)}", flush=True)

    active_items = filter_active(items, today=t)
    print(f"[mail_view][stage5 filter_active] by_source={_count_by_source(active_items)}", flush=True)

    # 접수중은 end_date 임박 순 (없으면 뒤로).
    def _end_sort_key(x: Dict[str, Any]) -> tuple:
        e = _parse_iso(x.get("end_date") or "")
        return (0, e.toordinal()) if e is not None else (1, 10**9)

    new_items.sort(key=_end_sort_key)
    ending_items.sort(key=_end_sort_key)
    active_items.sort(key=_end_sort_key)

    print(
        f"[mail_view] sections: new={len(new_items)} "
        f"ending_soon={len(ending_items)} active={len(active_items)}",
        flush=True,
    )

    parts: List[str] = []
    parts.append("전북지원사업 메일자동알림서비스입니다.\n")

    parts.append(
        format_section(
            "신규 공고 (최근 7일)", "🔥", new_items, limit=NEW_LIMIT, today=t
        )
    )
    parts.append(SECTION_SEP)

    parts.append(
        format_section(
            "마감 임박 공고 (7일 이내)", "⚠", ending_items, limit=ENDING_LIMIT,
            show_dday=True, today=t,
        )
    )
    parts.append(SECTION_SEP)

    parts.append(
        format_section(
            "전체 접수중 공고", "📌", active_items, limit=ACTIVE_LIMIT, today=t
        )
    )

    body = "\n\n".join(parts).rstrip() + "\n"
    return truncate_body(body)


# ---------------------------------------------------------------------------
# CLI 진입점
# ---------------------------------------------------------------------------

def write_mail_body(out_path: Path = OUT_FILE) -> Path:
    body = build_mail_body()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"[mail_view] 저장: {out_path} ({len(body):,}자)", flush=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="DB → 메일 본문 생성 (mail_view)")
    parser.add_argument("--out", type=Path, default=OUT_FILE, help="출력 파일")
    parser.add_argument("--today", default=None, help="기준 날짜 (YYYY-MM-DD, 기본: 오늘)")
    args = parser.parse_args()

    if args.today:
        body = build_mail_body(today=args.today)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
        print(f"[mail_view] 저장: {args.out} ({len(body):,}자)", flush=True)
    else:
        write_mail_body(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
