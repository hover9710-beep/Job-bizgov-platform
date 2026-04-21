# -*- coding: utf-8 -*-
"""
DB/JSON → presenter → 상태·목록일·정렬 모두 receipt_start/receipt_end만 사용.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.presenter import normalize_display_items
from pipeline.project_quality import canonical_notice_source


def sqlite_row_to_item(row: Any) -> dict:
    d = dict(row)
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
    return d


def _parse_iso(s: str) -> date | None:
    if not s or s == "-" or len(s) < 10:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _status_bucket(st: str) -> int:
    if st == "접수중":
        return 0
    if st == "공고중":
        return 1
    if st == "마감":
        return 2
    return 3


def _receipt_complete(r: dict) -> bool:
    ds = r.get("display_receipt_start")
    de = r.get("display_receipt_end")
    return bool(ds and de and ds != "-" and de != "-")


def build_sort_key(item: dict) -> tuple:
    """상태(접수기간 기준) → 소스 → (접수 시작·종료 불완이면 뒤) → receipt_end↑ → receipt_start↑ → 제목."""
    st = item.get("display_status") or ""
    status_pri = _status_bucket(st)

    sb = item.get("source_badge") or ""
    if sb == "jbexport":
        src_pri = 0
    elif sb == "bizinfo":
        src_pri = 1
    else:
        src_pri = 9

    complete = _receipt_complete(item)
    sort_incomplete = 1 if not complete else 0

    de = item.get("display_receipt_end") or "-"
    ds = item.get("display_receipt_start") or "-"
    if de != "-":
        e = _parse_iso(de)
        e_ord = e.toordinal() if e else 10**9
    else:
        e_ord = 10**9
    if ds != "-":
        s = _parse_iso(ds)
        s_ord = s.toordinal() if s else 10**9
    else:
        s_ord = 10**9

    title = str(item.get("title") or "")
    return (status_pri, src_pri, sort_incomplete, e_ord, s_ord, title)


def sort_items_for_ui(items: list[dict]) -> list[dict]:
    return sorted(items, key=build_sort_key)


def _has_receipt(r: dict) -> bool:
    return _receipt_complete(r)


def _has_biz(r: dict) -> bool:
    a = r.get("display_biz_start")
    b = r.get("display_biz_end")
    return bool(a and b and a != "-" and b != "-")


def _log_bizinfo_check(rows: list[dict]) -> None:
    biz = [r for r in rows if r.get("source_badge") == "bizinfo"]
    total = len(biz)
    receipt_parsed = sum(1 for r in biz if _has_receipt(r))
    receipt_missing = total - receipt_parsed
    ignored_registered_at = 0
    for r in biz:
        reg = r.get("display_registered_at") or ""
        has_reg = bool(reg and reg != "-")
        if has_reg and not _has_receipt(r):
            ignored_registered_at += 1
    print("[bizinfo-check]")
    print(f"[bizinfo-check] receipt_parsed={receipt_parsed}")
    print(f"[bizinfo-check] receipt_missing={receipt_missing}")
    print(f"[bizinfo-check] ignored_registered_at={ignored_registered_at}")


def _log_jbexport_check(rows: list[dict]) -> None:
    jb = [r for r in rows if r.get("source_badge") == "jbexport"]
    total = len(jb)
    receipt_parsed = sum(1 for r in jb if _has_receipt(r))
    biz_parsed = sum(1 for r in jb if _has_biz(r))
    both_parsed = sum(1 for r in jb if _has_receipt(r) and _has_biz(r))
    biz_missing = sum(1 for r in jb if _has_receipt(r) and not _has_biz(r))
    receipt_missing = total - receipt_parsed
    print("[jbexport-check]")
    print(f"[jbexport-check] receipt_parsed={receipt_parsed}")
    print(f"[jbexport-check] biz_parsed={biz_parsed}")
    print(f"[jbexport-check] both_parsed={both_parsed}")
    print(f"[jbexport-check] biz_missing={biz_missing}")
    print(f"[jbexport-check] receipt_missing={receipt_missing}")


def _log_status_check(rows: list[dict]) -> None:
    print("[status-check]")
    for r in rows[:15]:
        print(
            f"[status-check] source={r.get('source_badge')} "
            f"title={(r.get('title') or '')[:50]!r} "
            f"receipt_start={r.get('display_receipt_start')} "
            f"receipt_end={r.get('display_receipt_end')} "
            f"final_status={r.get('display_status')}"
        )


def _log_top10(rows: list[dict]) -> None:
    print("[top10-check]")
    for r in rows[:10]:
        print(
            f"- source={r.get('source_badge')} title={(r.get('title') or '')[:40]!r} "
            f"st={r.get('display_status')} "
            f"r={r.get('display_receipt_start')}-{r.get('display_receipt_end')}"
        )


def _log_source_mismatch_samples(sorted_rows: list[dict], limit: int = 5) -> None:
    """DB 스냅샷과 canonical_notice_source 불일치 샘플(데이터 점검용)."""
    n = 0
    print("[source mismatch sample] db_snapshot vs canonical (최대 5건)", flush=True)
    for r in sorted_rows:
        snap = str(
            r.get("db_source_snapshot") or r.get("_db_source_snapshot") or ""
        ).strip().lower()
        c = str(canonical_notice_source(dict(r)) or "").strip().lower()
        if snap and c and snap != c:
            print(
                f"  id={r.get('id')} snapshot={snap!r} canonical={c!r} "
                f"url={(r.get('url') or '')[:72]!r}",
                flush=True,
            )
            n += 1
            if n >= limit:
                break
    if n == 0:
        print("  (불일치 0건)", flush=True)


def _log_parser_route_audit(sorted_rows: list[dict]) -> None:
    """DB source 스냅샷과 receipt 파서 라벨이 교차하지 않는지 확인."""
    from pipeline.presenter import persisted_source_key, receipt_parser_label

    bad = 0
    cross = 0
    for r in sorted_rows:
        pk = persisted_source_key(r)
        pl = receipt_parser_label(r)
        u = str(r.get("url") or "").lower()
        if pk == "bizinfo" and pl == "jbexport_parser":
            bad += 1
            if bad <= 5:
                print(
                    f"  [!] snapshot=bizinfo → jbexport 파서 분기 id={r.get('id')} "
                    f"url={(r.get('url') or '')[:80]!r}",
                    flush=True,
                )
        if pk == "jbexport" and pl == "bizinfo_parser":
            bad += 1
            if bad <= 5:
                print(
                    f"  [!] snapshot=jbexport → bizinfo 파서 분기 id={r.get('id')} "
                    f"url={(r.get('url') or '')[:80]!r}",
                    flush=True,
                )
        if pk == "bizinfo" and "jbexport.or.kr" in u and pl != "bizinfo_parser":
            cross += 1
            if cross <= 5:
                print(
                    f"  [!] bizinfo DB + jbexport URL 파서={pl!r} id={r.get('id')}",
                    flush=True,
                )
    if bad == 0 and cross == 0:
        print(
            "[parser-route] bizinfo↔jbexport 파서 교차 없음 (스냅샷 기준)",
            flush=True,
        )
    elif bad == 0:
        print(
            f"[parser-route] URL·스냅샷 불일치 참고 로그 {cross}건 (샘플 최대 5)",
            flush=True,
        )
    else:
        print(f"[parser-route] 교차 분기 의심 {bad}건 (샘플 최대 5)", flush=True)


def _log_source_separation_samples(sorted_rows: list[dict]) -> None:
    """canonical source·파서 경로 검증용 샘플(각 5건)."""
    print("[source-separation] 샘플 (URL 우선 canonical, presenter receipt/biz)", flush=True)

    def dump(label: str, rows: list[dict]) -> None:
        print(f"  --- {label} (최대 {len(rows)}건) ---", flush=True)
        for r in rows:
            sid = r.get("id", "")
            src = r.get("source") or ""
            sb = r.get("source_badge") or ""
            t = (r.get("title") or "")[:55]
            org = (r.get("organization") or "")[:40]
            u = (r.get("url") or "")[:70]
            rs = r.get("display_receipt_start") or "-"
            re_ = r.get("display_receipt_end") or "-"
            bs = r.get("display_biz_start") or "-"
            be = r.get("display_biz_end") or "-"
            print(
                f"    id={sid} source={src!r} badge={sb!r} receipt={rs}~{re_} biz={bs}~{be}",
                flush=True,
            )
            print(f"      title={t!r}", flush=True)
            print(f"      org={org!r} url={u!r}", flush=True)

    biz = [r for r in sorted_rows if r.get("source_badge") == "bizinfo"][:5]
    jb = [r for r in sorted_rows if r.get("source_badge") == "jbexport"][:5]
    dump("bizinfo", biz)
    dump("jbexport", jb)

    cross = 0
    for r in sorted_rows:
        u = str(r.get("url") or "").lower()
        sb = r.get("source_badge") or ""
        if sb == "bizinfo" and "jbexport.or.kr" in u:
            cross += 1
        if sb == "jbexport" and "bizinfo.go.kr" in u:
            cross += 1
    if cross:
        print(
            f"  [!] badge↔URL 교차 의심: {cross}건 (canonical 적용 후에도 남으면 데이터 점검)",
            flush=True,
        )
    else:
        print("  [OK] badge·URL jbexport/bizinfo 교차 0건", flush=True)


def _log_all_checks(sorted_rows: list[dict]) -> None:
    _log_source_mismatch_samples(sorted_rows)
    _log_parser_route_audit(sorted_rows)
    _log_source_separation_samples(sorted_rows)
    _log_bizinfo_check(sorted_rows)
    _log_jbexport_check(sorted_rows)
    _log_status_check(sorted_rows)
    _log_top10(sorted_rows)


def prepare_db_rows_for_ui(rows: list) -> list[dict]:
    rows = [dict(r) if not isinstance(r, dict) else r for r in rows]
    items = [sqlite_row_to_item(r) for r in rows]
    items = [dict(r) if not isinstance(r, dict) else r for r in items]
    items = normalize_display_items(items)
    items = sort_items_for_ui(items)
    _log_all_checks(items)
    for i, it in enumerate(items, start=1):
        it["display_idx"] = i
    return items


def prepare_json_items_for_ui(raw_items: list[dict]) -> list[dict]:
    copies: list[dict] = []
    for x in raw_items:
        if not isinstance(x, dict):
            continue
        copies.append(sqlite_row_to_item(x))
    copies = normalize_display_items(copies)
    copies = sort_items_for_ui(copies)
    _log_all_checks(copies)
    for i, it in enumerate(copies, start=1):
        it["display_idx"] = i
    return copies
