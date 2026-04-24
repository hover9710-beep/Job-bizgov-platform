# AI 요약 모듈 - OpenAI GPT 사용.
# summarize_project() 내부만 교체하면 다른 AI로 전환 가능.

from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI

_ROOT = Path(__file__).resolve().parent.parent
TEXT_ROOT = _ROOT / "data" / "text"


def load_attachment_text(source: str, attachment_filename: str) -> str:
    """data/text/<source>/files/*.txt 중 첨부 파일명과 매칭되는 추출본 일부."""
    if not attachment_filename or not str(attachment_filename).strip():
        return ""
    src = (source or "unknown").strip().lower() or "unknown"
    stem = Path(attachment_filename).stem
    if not stem:
        return ""
    for base in (TEXT_ROOT / src / "files", TEXT_ROOT / src):
        if not base.is_dir():
            continue
        for p in sorted(base.glob(f"*{stem}.txt")):
            if p.is_file():
                try:
                    return p.read_text(encoding="utf-8", errors="ignore")[:2000]
                except OSError:
                    continue
    return ""


def summarize_project(title: str, description: str, attachment_text: str) -> str:
    """
    OpenAI GPT로 공고 1줄 요약.
    API 키 없거나 실패하면 빈 문자열 반환 (전체 파이프라인 중단 없음).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""

    content = attachment_text or description or title
    if not content:
        return ""

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "정부 지원사업 공고를 한 줄로 요약해라. 핵심 지원 내용과 대상을 포함해서 50자 이내로.",
                },
                {
                    "role": "user",
                    "content": f"공고명: {title}\n\n내용: {content[:1500]}",
                },
            ],
            max_tokens=100,
            temperature=0.3,
        )
        msg = response.choices[0].message.content
        return (msg or "").strip()
    except Exception as e:
        print(f"[ai_summary] GPT 요약 실패: {e}")
        return ""


def get_project_summary(item: dict) -> str:
    title = item.get("title", "")
    description = item.get("description", "") or ""
    source = item.get("source", "")

    attachment_text = ""
    attach_names = item.get("attachment_names") or []
    if isinstance(attach_names, list) and attach_names:
        attachment_text = load_attachment_text(source, str(attach_names[0]))

    return summarize_project(title, description, attachment_text)
