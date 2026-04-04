# pipeline/daily_run.py
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.jbexport_daily import run_daily as run_jb
from connectors.connector_bizinfo import run as run_bizinfo

from pipeline.merge_jb import merge_jb_biz_new, save_bizinfo_snapshot
from pipeline.compare import compare_title_snapshots

from ai_analyzer import analyze_project
from pdf_generator import create_pdf
from mailer import send_email


def _ensure_description(item: dict) -> dict:
    """compare_title_snapshots 결과에 description 이 없을 때 보강."""
    if item.get("description"):
        return item
    desc = item.get("content") or item.get("지원내용") or ""
    org = item.get("organization") or item.get("기관") or ""
    if org and str(desc).strip():
        return {**item, "description": f"{org}\n{desc}".strip()}
    if org:
        return {**item, "description": str(org)}
    return {**item, "description": str(desc or "")}


def daily_run() -> None:
    print("===== DAILY RUN START =====")

    # 1. 전북 수집
    print("1. JBEXPORT 수집")
    run_jb()

    # 2. 기업마당 수집
    print("2. BIZINFO 수집")
    # 일일 실행: 페이지·상세 제한(전체 수집은 run_pipeline 또는 커넥터 단독 실행)
    run_bizinfo(max_pages=3, no_detail=True, verify_ssl=False)

    # 3. 신규 공고 찾기
    print("3. 신규 공고 비교")
    new_items = merge_jb_biz_new()

    if not new_items:
        print("신규 공고 없음 → today/yesterday 비교 실행")
        new_items = compare_title_snapshots()
        new_items = [_ensure_description(dict(x)) for x in new_items if isinstance(x, dict)]

    print(f"신규 공고 수: {len(new_items)}")

    # 4. AI → PDF → EMAIL
    for item in new_items:
        title = item.get("title", "") or ""
        content = item.get("description", "") or ""

        print(f"AI 분석: {title}")
        result = analyze_project(title, content)

        print("PDF 생성")
        pdf_path = create_pdf(title, result)

        mail_to = os.getenv("MAIL_TO")

        if mail_to:
            print("이메일 발송")
            send_email(
                to_email=mail_to,
                subject=f"[지원사업 분석] {title}",
                content=result,
                file_path=pdf_path,
            )
        else:
            print("MAIL_TO 없음 → 이메일 생략")

    save_bizinfo_snapshot()
    print("===== DAILY RUN END =====")


if __name__ == "__main__":
    daily_run()
