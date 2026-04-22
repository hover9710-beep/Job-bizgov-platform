# -*- coding: utf-8 -*-
"""
JBEXPORT 접수중 공고: dedupe + related_group 파이프라인 (make_mail 기준 필터).

- 완전 중복만 dedupe (follow-up 제목은 절대 합치지 않음)
- 같은 사업 계열은 related_groups 로 묶음
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline import make_mail as m
from pipeline.data_paths import ALL_SITES_JSON
from pipeline.jbexport_pipeline import process_jbexport_rows

ALL_FILE = ALL_SITES_JSON


def load_active_jbexport() -> list[dict]:
    items = m.load_json(ALL_FILE)
    out = []
    for x in items:
        if not isinstance(x, dict):
            continue
        if not m.is_jbexport_item(x):
            continue
        if not m.is_active(x) or not m.passes_bizinfo_relevance(x):
            continue
        out.append(x)
    return out


def main():
    rows = load_active_jbexport()
    n = len(rows)

    print("=" * 72)
    print("[1] 현재 접수중 JBEXPORT (make_mail 기준)")
    print(f"    총 개수: {n}")
    print()
    for i, x in enumerate(rows, 1):
        print(f"  {i:2}. {x.get('title')}")
        print(
            f"      기관: {x.get('organization')} | "
            f"기간: {m._effective_start_date_str(x)}|{m._effective_end_date_str(x)} | "
            f"status: {x.get('status')}"
        )
    print()

    result = process_jbexport_rows(rows, related_sim_threshold=0.8)
    dbg = result.get("_debug") or {}

    print("=" * 72)
    print("[2] 파이프라인 요약 (디버그)")
    print(f"    총 공고 수:           {dbg.get('total')}")
    print(f"    dedupe 제거 수:       {dbg.get('dedupe_removed')}  (완전 동일만)")
    print(f"    follow-up 유지(원본): {dbg.get('followup_in_source')}  (제목 키워드)")
    print(f"    dedupe 후 건수:       {dbg.get('items_after_dedupe')}")
    print(f"    related_group 수:     {dbg.get('related_group_count')}")
    print()

    print("=" * 72)
    print("[3] related_groups")
    for block in result.get("related_groups") or []:
        print(f"  {block.get('group_id')}")
        r = block.get("representative") or {}
        print(f"    대표: {r.get('title')}")
        for rel in block.get("related_items") or []:
            print(f"    related: {rel.get('title')}")
    if not result.get("related_groups"):
        print("  (없음)")
    print()

    print("=" * 72)
    print("[4] 최종 JSON (items + related_groups)")
    out_json = {"items": result["items"], "related_groups": result["related_groups"]}
    print(json.dumps(out_json, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
