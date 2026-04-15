# -*- coding: utf-8 -*-
"""
카카오 알림용 짧은 본문 → data/kakao/kakao_body.txt

입력: merged/all_sites.json, merged/new.json (make_mail과 동일 기준)
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline import make_mail as mm
from pipeline.data_paths import ALL_SITES_JSON, KAKAO_BODY_TXT, NEW_JSON, ensure_pipeline_dirs

LINK_PREVIEW_MAX = 5


def get_item_key(x: dict) -> str:
    if not isinstance(x, dict):
        return ""
    url = str(x.get("url") or x.get("detail_url") or x.get("link") or "").strip()
    if url:
        return url
    src = str(x.get("source") or x.get("_source") or "").strip().lower()
    title = str(x.get("title") or "").strip()
    org = str(x.get("organization") or x.get("org") or "").strip()
    end_date = str(x.get("end_date") or x.get("receipt_end") or "").strip()
    if src or title or org or end_date:
        return "|".join([src, title, org, end_date])
    return ""


def passes_bizinfo_relevance(x: dict) -> bool:
    fn = getattr(mm, "passes_bizinfo_relevance", None)
    if callable(fn):
        return bool(fn(x))
    return True


def _url(x: dict) -> str:
    return str(x.get("url") or x.get("detail_url") or "").strip()


def _title(x: dict) -> str:
    return str(x.get("title") or "")[:80]


def main():
    ensure_pipeline_dirs()
    all_items = mm.load_json(ALL_SITES_JSON)
    new_raw = mm.load_json(NEW_JSON)

    new_items = [
        x for x in new_raw if mm.is_new(x) and passes_bizinfo_relevance(x)
    ]
    ending_items = [
        x
        for x in all_items
        if mm.is_ending_soon(x) and passes_bizinfo_relevance(x)
    ]

    lines: list[str] = []
    lines.append("[전북지원사업 알림]\n")
    lines.append(f"신규 공고: {len(new_items)}건\n")
    lines.append(f"마감 임박: {len(ending_items)}건\n")
    lines.append("\n[대표 링크]\n")

    preview: list[dict] = []
    seen: set[str] = set()

    def _take_from(items: list) -> None:
        for x in items:
            if len(preview) >= LINK_PREVIEW_MAX:
                return
            k = get_item_key(x)
            if not k or k in seen or not _url(x):
                continue
            seen.add(k)
            preview.append(x)

    _take_from(new_items)
    _take_from(ending_items)

    for i, x in enumerate(preview, 1):
        src = str(x.get("_source") or x.get("source") or "")
        lines.append(f"{i}. [{src}] {_title(x)}\n")
        lines.append(f"   {_url(x)}\n")

    lines.append("\n상세·전체 목록은 메일 본문을 확인해 주세요.\n")

    body = "".join(lines)
    KAKAO_BODY_TXT.parent.mkdir(parents=True, exist_ok=True)
    KAKAO_BODY_TXT.write_text(body, encoding="utf-8")
    print(f"[make_kakao] 저장: {KAKAO_BODY_TXT}")


if __name__ == "__main__":
    main()
