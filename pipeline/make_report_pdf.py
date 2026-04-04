# -*- coding: utf-8 -*-
"""
pipeline/make_report_pdf.py
추천 결과 PDF 리포트 생성기
사용: py pipeline/make_report_pdf.py
"""

import sqlite3
from datetime import datetime
from pathlib import Path

# ── 경로 설정 ──────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "biz.db"
OUT_DIR = ROOT / "reports"
COMPANY_ID = "1"


# ── DB 조회 ────────────────────────────
def load_recommendations(company_id: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT
            p.title,
            p.ministry,
            p.executing_agency,
            p.organization,
            p.start_date,
            p.end_date,
            p.url,
            r.score,
            r.reason
        FROM recommendations r
        JOIN biz_projects p ON r.project_id = p.id
        WHERE r.company_id = ?
        ORDER BY r.score DESC
    """, (company_id,))
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


# ── PDF 생성 ───────────────────────────
def make_pdf(company_id: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"recommend_report_company_{company_id}.pdf"

    # ── 한글 폰트 등록 (있으면 사용, 없으면 기본) ──
    font_name = "Helvetica"
    font_candidates = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("KorFont", fp))
                font_name = "KorFont"
                break
            except Exception:
                pass

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title2",
        fontName=font_name,
        fontSize=18,
        leading=24,
        spaceAfter=6,
        textColor=colors.HexColor("#1a3a5c"),
    )
    sub_style = ParagraphStyle(
        "Sub",
        fontName=font_name,
        fontSize=10,
        leading=14,
        textColor=colors.grey,
    )
    body_style = ParagraphStyle(
        "Body2",
        fontName=font_name,
        fontSize=9,
        leading=13,
    )
    label_style = ParagraphStyle(
        "Label",
        fontName=font_name,
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#444444"),
    )

    rows = load_recommendations(company_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    story = []

    story.append(Paragraph("BizGovPlanner 추천 리포트", title_style))
    story.append(Paragraph(f"회사 ID: {company_id}　|　생성 일시: {now}", sub_style))
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#1a3a5c"), spaceAfter=8))

    story.append(Paragraph(f"총 추천 건수: {len(rows)}건", body_style))
    story.append(Spacer(1, 6 * mm))

    if not rows:
        story.append(Paragraph("추천 결과가 없습니다.", body_style))
    else:
        for i, r in enumerate(rows, 1):
            period = f"{r.get('start_date', '') or '-'} ~ {r.get('end_date', '') or '-'}"
            agency = r.get('executing_agency') or r.get('organization') or '-'

            tdata = [
                ["항목", "내용"],
                ["공고명", Paragraph(r.get('title', '') or '-', label_style)],
                ["소관부처", r.get('ministry', '') or '-'],
                ["수행기관", agency],
                ["기간", period],
                ["점수", str(r.get('score', ''))],
                ["추천 이유", Paragraph(r.get('reason', '') or '-', label_style)],
                ["URL", Paragraph(r.get('url', '') or '-', label_style)],
            ]

            table = Table(tdata, colWidths=[30 * mm, 140 * mm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f0f4f8")),
                ("ROWBACKGROUNDS", (1, 1), (-1, -1),
                 [colors.white, colors.HexColor("#f9f9f9")]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))

            story.append(Paragraph(f"[{i}]", body_style))
            story.append(table)
            story.append(Spacer(1, 5 * mm))

    doc.build(story)
    return out_path


# ── 진입점 ─────────────────────────────
def main():
    print("[make_report_pdf] START")
    print(f"[make_report_pdf] company_id={COMPANY_ID}")

    rows = load_recommendations(COMPANY_ID)
    print(f"[make_report_pdf] rows={len(rows)}")

    out = make_pdf(COMPANY_ID)
    print(f"[make_report_pdf] saved={out}")
    print("[make_report_pdf] END")


if __name__ == "__main__":
    main()
