import os
from typing import Any, Dict, Optional

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from schemas.notice_schema import NOTICE_SCHEMA  # noqa: F401 — 표준 스키마 참조용

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

FONT_NAME = "MalgunGothic"
FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"


def _notice_block(notice: Dict[str, Any]) -> str:
    title = str(notice.get("title") or "").strip()
    ministry = str(notice.get("ministry") or "").strip()
    executing = str(notice.get("executing_agency") or "").strip()
    org = str(notice.get("organization") or "").strip()
    sd = str(notice.get("start_date") or "").strip()
    ed = str(notice.get("end_date") or "").strip()
    url = str(notice.get("url") or "").strip()
    period = ""
    if sd or ed:
        period = f"{sd or '—'} ~ {ed or '—'}"
    else:
        period = "—"
    lines = [
        "【1. 공고 기본정보】",
        f"공고명: {title or '—'}",
        f"소관부처: {ministry or '—'}",
        f"사업수행기관: {executing or '—'}",
        f"지원기관: {org or '—'}",
        f"접수기간: {period}",
        f"공고URL: {url or '—'}",
        "",
    ]
    return "\n".join(lines)


def _company_analysis_block(
    company: Dict[str, Any],
    *,
    score: int,
    reason: str,
) -> str:
    lines = [
        "【2. 회사 기준 분석】",
        f"회사명: {str(company.get('company_name') or '—')}",
        f"업종: {str(company.get('industry') or '—')}",
        f"지역: {str(company.get('region') or '—')}",
        f"수출 여부: {str(company.get('export_flag') or '—')}",
        f"추천 점수: {score}",
        f"추천 이유: {reason or '—'}",
        "",
    ]
    return "\n".join(lines)


def _next_actions_block() -> str:
    return "\n".join(
        [
            "【3. 다음 액션】",
            "- 신청 검토: 공고 요건·기한을 확인한 뒤 신청 가능 여부를 판단합니다.",
            "- 문의 필요: 사업수행기관·지원기관 담당자에게 문의합니다.",
            "- 보류 가능: 조건이 맞지 않으면 다음 공고를 검토합니다.",
            "",
        ]
    )


def create_pdf(
    title: str,
    result: Any,
    notice: Optional[Dict[str, Any]] = None,
) -> str:
    """AI 분석 결과 PDF (기존 동작 유지). notice가 있으면 상단에 공고 요약 블록."""
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

    safe_title = title.replace("/", "_").replace("\\", "_").replace(":", "_")
    file_path = os.path.join(REPORTS_DIR, f"{safe_title}.pdf")

    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))

    c = canvas.Canvas(file_path, pagesize=A4)
    _, height = A4

    text = c.beginText(40, height - 40)
    text.setFont(FONT_NAME, 11)

    parts: list[str] = []
    if notice:
        parts.append(_notice_block(notice))
    parts.append(str(result))
    full_text = "\n".join(parts)

    lines = full_text.split("\n")
    line_count = 0

    for line in lines:
        text.textLine(line)
        line_count += 1

        if line_count >= 45:
            c.drawText(text)
            c.showPage()
            text = c.beginText(40, height - 40)
            text.setFont(FONT_NAME, 11)
            line_count = 0

    c.drawText(text)
    c.save()

    return file_path


def create_recommendation_report_pdf(
    *,
    notice: Dict[str, Any],
    company: Dict[str, Any],
    score: int,
    reason: str,
    safe_basename: str,
) -> str:
    """
    추천 리포트 PDF: 공고 기본정보 + 회사 분석 + 다음 액션.
    기존 create_pdf()와 별도 파일명 규칙(추천_ prefix).
    """
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

    safe = safe_basename.replace("/", "_").replace("\\", "_").replace(":", "_")
    file_path = os.path.join(REPORTS_DIR, f"추천_{safe}.pdf")

    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
    c = canvas.Canvas(file_path, pagesize=A4)
    _, height = A4

    text = c.beginText(40, height - 40)
    text.setFont(FONT_NAME, 11)

    full_text = "\n\n".join(
        [
            _notice_block(notice),
            _company_analysis_block(company, score=score, reason=reason),
            _next_actions_block(),
        ]
    )

    line_count = 0
    for line in full_text.split("\n"):
        text.textLine(line)
        line_count += 1
        if line_count >= 45:
            c.drawText(text)
            c.showPage()
            text = c.beginText(40, height - 40)
            text.setFont(FONT_NAME, 11)
            line_count = 0

    c.drawText(text)
    c.save()
    return file_path
