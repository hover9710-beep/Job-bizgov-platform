# -*- coding: utf-8 -*-
"""Presenter·JB 파서 검증 로그 (python -m pipeline.verify_period_layers)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.jbexport_enrich import _parse_meta_from_html, fetch_jbexport_detail_html
from pipeline.presenter import extract_biz_period, extract_receipt_period, normalize_display_item
from pipeline.ui_list import sqlite_row_to_item

JB_SAMPLE_LIMIT = 20
BIZ_SAMPLE_LIMIT = 20

_JB_SQL = """
SELECT id, title, source, url,
       receipt_start, receipt_end, biz_start, biz_end,
       start_date, end_date, description
FROM biz_projects
WHERE LOWER(TRIM(COALESCE(source,''))) = 'jbexport'
   OR LOWER(COALESCE(url,'')) LIKE '%jbexport.or.kr%'
ORDER BY id
LIMIT ?
"""


def _row_to_item(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def _jb_meta_counts(meta: dict) -> tuple[int, int]:
    rs, re_ = str(meta.get("receipt_start") or "").strip(), str(
        meta.get("receipt_end") or ""
    ).strip()
    bs, be = str(meta.get("biz_start") or "").strip(), str(meta.get("biz_end") or "").strip()
    pr = 1 if rs and re_ else 0
    pb = 1 if bs and be else 0
    return pr, pb


def main() -> None:
    print("=== JBEXPORT HTML 파서: 정규 청크 보강 전·후(동일 HTML) ===")
    fixtures = [
        (
            "표 th/td",
            """<table><tr><th>접수기간</th><td>2024-01-01 ~ 2024-01-31</td></tr>
<tr><th>사업기간</th><td>2024-02-01 ~ 2024-11-30</td></tr></table>""",
        ),
        (
            "평문 라벨(한 줄)",
            "<div>접수기간 : 2025-03-01 ~ 2025-04-30 사업기간 2025-05-01 ~ 2025-12-31</div>",
        ),
        (
            "td.th 4열 한 행",
            """<table><tr>
<td class="th">접수기간</td><td>2024-01-01 00:00 ~ 2024-01-31 00:00</td>
<td class="th">사업기간</td><td>2024-02-01 ~ 2024-11-30</td>
</tr></table>""",
        ),
    ]
    sum_before_r = sum_before_b = 0
    sum_after_r = sum_after_b = 0
    for name, html in fixtures:
        b = _parse_meta_from_html(html, use_regex_chunks=False)
        a = _parse_meta_from_html(html, use_regex_chunks=True)
        br, bb = _jb_meta_counts(b)
        ar, ab = _jb_meta_counts(a)
        sum_before_r += br
        sum_before_b += bb
        sum_after_r += ar
        sum_after_b += ab
        print(f"  [{name}] 전 receipt={br} biz={bb} | 후 receipt={ar} biz={ab}")
    print(
        f"  합계 parsed_receipt: 전={sum_before_r} 후={sum_after_r} | "
        f"parsed_biz: 전={sum_before_b} 후={sum_after_b}"
    )

    db_path = _ROOT / "db" / "biz.db"
    print("\n=== DB biz_projects (있을 때만) ===")
    if not db_path.is_file():
        print("  (biz.db 없음 — DB 샘플·오염 검사 스킵)")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        biz_rows = conn.execute(
            """
            SELECT id, title, source, url,
                   receipt_start, receipt_end, biz_start, biz_end,
                   start_date, end_date, description
            FROM biz_projects
            WHERE LOWER(TRIM(COALESCE(source,''))) LIKE '%bizinfo%'
               OR LOWER(COALESCE(url,'')) LIKE '%bizinfo.go.kr%'
            ORDER BY id
            LIMIT ?
            """,
            (BIZ_SAMPLE_LIMIT,),
        ).fetchall()
        jb_rows = conn.execute(_JB_SQL, (JB_SAMPLE_LIMIT,)).fetchall()
    finally:
        conn.close()

    print(f"\n--- Bizinfo 샘플 {len(biz_rows)}건 (presenter: receipt/biz 전용 파서) ---")
    biz_contam = 0
    pair_keys: dict[tuple[str, str], list[int]] = {}
    for row in biz_rows:
        it = _row_to_item(row)
        u = str(it.get("url") or "").lower()
        if "jbexport.or.kr" in u:
            biz_contam += 1
        rs, re_ = extract_receipt_period(it)
        bs, be = extract_biz_period(it)
        t = (it.get("title") or "")[:50]
        pk = (str(rs), str(re_))
        pair_keys.setdefault(pk, []).append(int(it.get("id") or 0))
        print(f"  id={it.get('id')} receipt={rs} ~ {re_} | biz={bs} ~ {be} | {t}")
    print(f"  source 오염(jbexport URL 혼입): {biz_contam}건")
    dup_pairs = {k: ids for k, ids in pair_keys.items() if len(ids) > 1 and k != ("-", "-")}
    if dup_pairs:
        print(
            f"  ⚠ 동일 receipt 쌍이 2건 이상: {len(dup_pairs)}그룹 "
            f"(파싱 실패·허위 반복 의심 시 확인)"
        )
        for k, ids in list(dup_pairs.items())[:5]:
            print(f"    {k} -> ids {ids}")
    else:
        print("  동일 receipt 쌍 중복(샘플 내): 없음 (또는 전부 '-/-'만)")

    print(
        f"\n--- JBEXPORT 샘플 {len(jb_rows)}건 DB→presenter (jbexport_display, 저장 필드만) ---"
    )
    jb_contam = 0
    pres_r_ok = pres_b_ok = 0
    for row in jb_rows:
        it = _row_to_item(row)
        src = str(it.get("source") or "").lower()
        u = str(it.get("url") or "").lower()
        if "bizinfo" in src and "jbexport" not in src:
            jb_contam += 1
        if "bizinfo.go.kr" in u:
            jb_contam += 1
        rs, re_ = extract_receipt_period(it)
        bs, be = extract_biz_period(it)
        t = (it.get("title") or "")[:50]
        print(f"  id={it.get('id')} receipt={rs} ~ {re_} | biz={bs} ~ {be} | {t}")
        ui_it = sqlite_row_to_item(row)
        norm = normalize_display_item(ui_it)
        drs = str(norm.get("display_receipt_start") or "")
        dre = str(norm.get("display_receipt_end") or "")
        dbs = str(norm.get("display_biz_start") or "")
        dbe = str(norm.get("display_biz_end") or "")
        if drs and dre and drs != "-" and dre != "-":
            pres_r_ok += 1
        if dbs and dbe and dbs != "-" and dbe != "-":
            pres_b_ok += 1
    print(f"  source/URL 오염(bizinfo로만 태깅된 혼입 추정): {jb_contam}건")
    njb = len(jb_rows)
    print(
        f"  presenter(sqlite_row→normalize) 샘플: "
        f"parsed_receipt={pres_r_ok}/{njb} parsed_biz={pres_b_ok}/{njb}"
    )

    print(
        f"\n=== JBEXPORT 상세 HTML 파서 실측 (GET, 최대 {JB_SAMPLE_LIMIT}건) ==="
    )
    n = len(jb_rows)
    ok_r = ok_b = 0
    for row in jb_rows:
        it = _row_to_item(row)
        url = str(it.get("url") or "").strip()
        pid = it.get("id")
        if not url:
            print(f"  id={pid} SKIP (no url)")
            continue
        h = fetch_jbexport_detail_html(url)
        if not h:
            print(f"  id={pid} FAIL (empty html)")
            continue
        meta = _parse_meta_from_html(h)
        pr, pb = _jb_meta_counts(meta)
        ok_r += pr
        ok_b += pb
        if not pr or not pb:
            print(
                f"  id={pid} partial receipt={meta.get('receipt_start')!r}~{meta.get('receipt_end')!r} "
                f"biz={meta.get('biz_start')!r}~{meta.get('biz_end')!r}"
            )
    print(f"  parsed_receipt: {ok_r}/{n}")
    print(f"  parsed_biz: {ok_b}/{n}")
    if ok_r == n and ok_b == n:
        print("  (상세 HTML 기준 receipt·biz 전부 양 끝 날짜 추출 성공)")
    else:
        print("  ※ 일부 건은 상세 표에 사업/접수 기간이 비어 있거나 날짜가 아닌 문구일 수 있음.")


if __name__ == "__main__":
    main()
