import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = DATA_DIR / "all_jb"
OUT_PATH = OUT_DIR / "all_jb.json"


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


def _normalize_item(item: Dict[str, Any]) -> Dict[str, str]:
    title = _pick(item, ("title", "공고제목", "사업명", "js_title"))
    organization = _pick(item, ("organization", "기관", "org"), "전북수출통합지원시스템")
    status = _pick(item, ("status", "상태", "STS_TXT"))
    url = _pick(item, ("url", "상세URL", "detail_url", "detailUrl"))
    description = _pick(item, ("description", "content", "지원내용", "본문", "summary"))
    period = _pick(item, ("period", "기간"))

    start_date = ""
    end_date = ""
    if "~" in period:
        left, right = period.split("~", 1)
        start_date = left.strip()
        end_date = right.strip()

    return {
        "title": title,
        "organization": organization,
        "status": status,
        "url": url,
        "description": description,
        "start_date": start_date,
        "end_date": end_date,
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
        files.append(p)

    files.sort()
    return files


def merge_jb_json() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    merged: List[Dict[str, str]] = []
    seen_urls = set()

    for path in collect_json_files():
        payload = _safe_load_json(path)
        rows = _extract_list_payload(payload)
        if not rows:
            continue

        for raw in rows:
            if not _looks_like_project(raw):
                continue
            item = _normalize_item(raw)
            if not item["title"] and not item["url"]:
                continue
            key = item["url"] or f"{item['title']}|{item['organization']}"
            if key in seen_urls:
                continue
            seen_urls.add(key)
            merged.append(item)

    OUT_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[merge_jb] saved: {OUT_PATH} ({len(merged)}건)")
    return OUT_PATH


if __name__ == "__main__":
    merge_jb_json()
