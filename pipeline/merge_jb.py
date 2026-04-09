"""
IMPORTANT:
This file MUST NOT perform any HTTP request.
All crawling must be completed in connectors.
This file only merges JSON outputs.

루트(data/) 아래 JSON을 병합 → data/all_jb/all_jb.json
병합 성공 시 data/today.json 갱신(기존 today → yesterday).

실행(프로젝트 루트):
  py pipeline\\merge_jb.py
"""
from __future__ import annotations

import inspect
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

# 커서앱통합_v1 루트 (pipeline/ 의 부모)
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipeline.fields_normalize import enrich_dates_and_status


def assert_no_network_calls() -> None:
    """merge 단계에 HTTP 클라이언트 호출 패턴이 없어야 함.

    참고: getsource(assert_no_network_calls) + banned 리터럴에 "requests.get"를 넣으면
    소스 문자열 자체에 패턴이 포함되어 항상 실패하므로 merge_jb_json 본문만 검사함.
    """
    src = inspect.getsource(merge_jb_json)
    banned = ["requests.get", "sess.get"]
    for b in banned:
        if b in src:
            raise RuntimeError("Network call detected in merge stage")


def validate_item(item: Dict[str, Any]) -> bool:
    required = ["title", "url"]
    for r in required:
        if not item.get(r):
            return False
    return True


def _ensure_canonical_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """title, organization, status, start_date, end_date, url — 없으면 빈 str."""
    out = dict(item)
    for k in ("title", "organization", "status", "start_date", "end_date", "url"):
        out[k] = str(out.get(k) or "").strip()
    return out


DATA_DIR = ROOT_DIR / "data"
OUT_DIR = DATA_DIR / "all_jb"
OUT_PATH = OUT_DIR / "all_jb.json"

JBEXPORT_NEW_JSON = DATA_DIR / "jbexport_new.json"
# 전체 수집 커넥터 출력 (우선)
BIZINFO_ALL_JSON = DATA_DIR / "bizinfo" / "json" / "bizinfo_all.json"
# 레거시 자동 커넥터 경로 (있으면 추가 병합)
BIZINFO_LEGACY_JSON = (
    ROOT_DIR
    / "reports"
    / "blueprints"
    / "data"
    / "www_bizinfo_go_kr"
    / "json"
    / "www_bizinfo_go_kr_all.json"
)
BIZINFO_DAILY_SNAPSHOT = DATA_DIR / "daily_run_bizinfo_snapshot.json"


def _promote_today_to_yesterday(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    today = data_dir / "today.json"
    yesterday = data_dir / "yesterday.json"
    if today.exists():
        yesterday.write_text(today.read_text(encoding="utf-8"), encoding="utf-8")


def _save_today_snapshot(items: List[Any], data_dir: Path) -> Path:
    _promote_today_to_yesterday(data_dir)
    today = data_dir / "today.json"
    today.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return today


def _safe_load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_list_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "rows", "data", "list", "new_items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _pick(item: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _extract_org_from_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    patterns = (
        r"(?:주관기관|수행기관|담당기관|지원기관)\s*[:：]\s*([^\n\r]+)",
        r"(?:기관명|기관)\s*[:：]\s*([^\n\r]+)",
    )
    for pat in patterns:
        m = re.search(pat, raw)
        if not m:
            continue
        val = m.group(1).strip()
        if val:
            return val
    return ""


def _pick_organization(item: Dict[str, Any], default: str) -> str:
    org = _pick(
        item,
        (
            "organization",
            "org",
            "insttNm",
            "excInsttNm",
            "jrsdInsttNm",
            "sprvInsttNm",
            "기관",
            "기관명",
            "주관기관",
            "수행기관",
        ),
        "",
    )
    if org:
        return org
    from_text = _extract_org_from_text(
        _pick(item, ("description", "content", "지원내용", "본문", "summary", "body"), "")
    )
    return from_text or default


def _normalize_item(
    item: Dict[str, Any],
    source_hint: str = "",
    source: str = "",
    period_unparsed_log: Optional[List[str]] = None,
) -> Dict[str, str]:
    title = _pick(item, ("title", "공고제목", "사업명", "js_title"))
    url = _pick(item, ("url", "상세URL", "detail_url", "detailUrl"))
    hint = source_hint.lower()
    is_bizinfo = (
        "bizinfo.go.kr" in url
        or "bizinfo" in hint
        or ("seq" in item and "date" in item and "상세URL" not in item)
    )
    default_org = "기업마당" if is_bizinfo else "전북수출통합지원시스템"
    organization = _pick_organization(item, default_org)
    description = _pick(item, ("description", "content", "지원내용", "본문", "summary"))
    body_fb = _pick(item, ("description", "content", "body", "지원내용", "본문", "summary"))

    extra = enrich_dates_and_status(
        item,
        body_for_fallback=body_fb,
        period_unparsed_log=period_unparsed_log,
    )

    src = (source or "").strip().lower()
    if src not in ("jbexport", "bizinfo"):
        src = "jbexport"

    ministry = _pick(item, ("ministry",))
    executing_agency = _pick(item, ("executing_agency",))
    site = _pick(item, ("site",))
    collected_at = _pick(item, ("collected_at",))

    return {
        "title": title,
        "organization": organization,
        "status": extra["status"],
        "url": url,
        "description": description,
        "start_date": extra["start_date"],
        "end_date": extra["end_date"],
        "source": src,
        "ministry": ministry,
        "executing_agency": executing_agency,
        "site": site,
        "collected_at": collected_at,
    }


def _looks_like_project(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    has_title = any(k in item for k in ("title", "공고제목", "사업명", "js_title"))
    has_url = any(k in item for k in ("url", "상세URL", "detail_url", "detailUrl"))
    return has_title or has_url


def collect_json_files() -> List[Path]:
    files: List[Path] = []
    if not DATA_DIR.exists():
        return files

    for p in DATA_DIR.rglob("*.json"):
        if OUT_DIR in p.parents:
            continue
        if p.name in ("today.json", "yesterday.json"):
            continue
        files.append(p)

    files.sort()
    return files


def _source_for_path(path: Path) -> str:
    """파일 경로로 수집 출처(jbexport | bizinfo) 판별."""
    norm = str(path).replace("\\", "/")
    low = norm.lower()
    if "bizinfo_all.json" in low and "bizinfo" in low:
        return "bizinfo"
    try:
        if BIZINFO_ALL_JSON.exists() and path.resolve() == BIZINFO_ALL_JSON.resolve():
            return "bizinfo"
        if BIZINFO_LEGACY_JSON.exists() and path.resolve() == BIZINFO_LEGACY_JSON.resolve():
            return "bizinfo"
    except OSError:
        pass
    if "www_bizinfo_go_kr" in norm and norm.endswith(".json"):
        return "bizinfo"
    return "jbexport"


def _dedup_key_title_source(item: Dict[str, str]) -> str:
    """동일 출처 내에서만 중복 판단: (정규화 제목/식별자 + source)."""
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip()
    # 제목이 비어 있으면 URL로 식별(동일 출처 내 중복만 제거)
    identity = title or url or ""
    source = str(item.get("source") or "jbexport").strip().lower()
    if source not in ("jbexport", "bizinfo"):
        source = "jbexport"
    return f"{identity}\x00{source}"


def merge_jb_json() -> Path:
    assert_no_network_calls()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    merged: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    duplicates_removed = 0
    candidates_seen = 0
    period_unparsed_log: List[str] = []

    source_files = collect_json_files()
    _seen = {p.resolve() for p in source_files}
    if BIZINFO_LEGACY_JSON.exists() and BIZINFO_LEGACY_JSON.resolve() not in _seen:
        source_files.append(BIZINFO_LEGACY_JSON)

    for path in source_files:
        payload = _safe_load_json(path)
        rows = _extract_list_payload(payload)
        if not rows:
            continue

        file_source = _source_for_path(path)
        for raw in rows:
            if not _looks_like_project(raw):
                continue
            item = _normalize_item(
                raw,
                source_hint=str(path),
                source=file_source,
                period_unparsed_log=period_unparsed_log,
            )
            if not item["title"] and not item["url"]:
                continue
            candidates_seen += 1
            key = _dedup_key_title_source(item)
            if key in seen_keys:
                duplicates_removed += 1
                continue
            seen_keys.add(key)
            merged.append(item)

    merged = [_ensure_canonical_fields(x) for x in merged]
    merged = [x for x in merged if validate_item(x)]

    jbexport_n = sum(1 for x in merged if x.get("source") == "jbexport")
    bizinfo_n = sum(1 for x in merged if x.get("source") == "bizinfo")

    print(f"[merge_jb] total items: {len(merged)}")
    sample = merged[0] if merged else {}
    print("[merge_jb sample keys]:", list(sample.keys()))

    OUT_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[merge_jb] saved: {OUT_PATH} ({len(merged)}건)")

    root_all_jb = DATA_DIR / "all_jb.json"
    try:
        shutil.copy2(OUT_PATH, root_all_jb)
        print(f"[merge_jb] copied: {OUT_PATH} -> {root_all_jb}")
    except OSError as e:
        print(f"[merge_jb] copy to {root_all_jb} failed: {e}")
    print(f"[merge_jb] jbexport: {jbexport_n}건, bizinfo: {bizinfo_n}건, merged 총: {len(merged)}건")
    print(
        f"[merge_jb] 중복 제거: {duplicates_removed}건 "
        f"(기준: title+source, 동일 출처·동일 제목·동일 식별자)"
    )
    _print_merge_field_stats(merged)
    if period_unparsed_log:
        shown = period_unparsed_log[:15]
        print(f"[merge_jb] 기간 원문 샘플(분리 실패·부분만 추출 등, 최대 {len(shown)}건):")
        for line in shown:
            print(f"  - {line}")

    if merged:
        snap = _save_today_snapshot(merged, DATA_DIR)
        print(f"[merge_jb] snapshot: {snap}")
    else:
        print("[merge_jb] snapshot: 병합 결과가 비어 있어 today.json 은 갱신하지 않습니다.")

    return OUT_PATH


def _print_merge_field_stats(merged: List[Dict[str, str]]) -> None:
    n = len(merged)
    if n == 0:
        print("[merge_jb] 통계: 병합 0건")
        return
    sd_ok = sum(1 for x in merged if str(x.get("start_date") or "").strip())
    ed_ok = sum(1 for x in merged if str(x.get("end_date") or "").strip())
    both = sum(
        1
        for x in merged
        if str(x.get("start_date") or "").strip() and str(x.get("end_date") or "").strip()
    )
    st_ok = sum(1 for x in merged if x.get("status") in ("진행", "마감"))
    st_need = sum(1 for x in merged if x.get("status") == "확인 필요")
    print(
        f"[merge_jb] 통계: 시작일 있음 {sd_ok}/{n}, 마감일 있음 {ed_ok}/{n}, "
        f"시작+마감 모두 {both}/{n}"
    )
    print(
        f"[merge_jb] 통계: 상태(진행/마감) {st_ok}/{n}, "
        f"확인 필요 {st_need}/{n}, "
        f"시작일 비어 있음 {n - sd_ok}건, 마감일 비어 있음 {n - ed_ok}건"
    )


def _normalize_jb_new_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    title = str(raw.get("공고제목") or raw.get("title") or "").strip()
    url = str(raw.get("상세URL") or raw.get("url") or "").strip()
    period = str(raw.get("기간") or "").strip()
    status = str(raw.get("상태") or "").strip()
    org = _pick_organization(raw, "전북수출통합지원시스템")
    parts = [p for p in (period, status, org) if p]
    description = "\n".join(parts) if parts else ""
    synthetic: Dict[str, Any] = {
        **raw,
        "title": title or url or "제목없음",
        "url": url,
        "기간": period,
        "period": period,
        "상태": status,
        "status": status,
        "description": description,
    }
    extra = enrich_dates_and_status(synthetic, body_for_fallback=description)
    return {
        "title": title or url or "제목없음",
        "organization": org,
        "description": description,
        "url": url,
        "source": "jbexport",
        "start_date": extra["start_date"],
        "end_date": extra["end_date"],
        "status": extra["status"],
    }


def _normalize_bizinfo_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    body = str(raw.get("body") or "").strip()
    org = _pick_organization(raw, "기업마당")
    synthetic: Dict[str, Any] = {**raw, "title": title or url or "제목없음", "url": url, "body": body}
    extra = enrich_dates_and_status(synthetic, body_for_fallback=body)
    return {
        "title": title or url or "제목없음",
        "organization": org,
        "description": body,
        "url": url,
        "source": "bizinfo",
        "start_date": extra["start_date"],
        "end_date": extra["end_date"],
        "status": extra["status"],
    }


def merge_jb_biz_new() -> List[Dict[str, Any]]:
    """daily_run: jbexport_new + 기업마당 신규(URL 스냅샷 대비)."""
    jb_payload = _safe_load_json(JBEXPORT_NEW_JSON)
    jb_rows = _extract_list_payload(jb_payload) if jb_payload is not None else []

    biz_payload = _safe_load_json(BIZINFO_ALL_JSON)
    current_biz = _extract_list_payload(biz_payload) if biz_payload is not None else []

    prev_payload = _safe_load_json(BIZINFO_DAILY_SNAPSHOT)
    prev_biz = _extract_list_payload(prev_payload) if prev_payload is not None else []

    prev_urls: Set[str] = {
        str(x.get("url") or "").strip()
        for x in prev_biz
        if isinstance(x, dict) and str(x.get("url") or "").strip()
    }

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for raw in jb_rows:
        if not isinstance(raw, dict):
            continue
        n = _normalize_jb_new_item(raw)
        key = str(n.get("url") or "").strip() or _dedup_key_title_source(n)
        if key in seen:
            continue
        seen.add(key)
        out.append(n)

    for raw in current_biz:
        if not isinstance(raw, dict):
            continue
        n = _normalize_bizinfo_row(raw)
        u = n["url"]
        if not u or u in prev_urls:
            continue
        key = str(u).strip() or _dedup_key_title_source(n)
        if key in seen:
            continue
        seen.add(key)
        out.append(n)

    return out


def save_bizinfo_snapshot() -> None:
    if not BIZINFO_ALL_JSON.exists():
        return
    payload = _safe_load_json(BIZINFO_ALL_JSON)
    if not isinstance(payload, list):
        return
    BIZINFO_DAILY_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    BIZINFO_DAILY_SNAPSHOT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    merge_jb_json()
