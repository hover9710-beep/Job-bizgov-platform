# AI 언어 통역 모듈 - OpenAI GPT 사용 (백로그 066 Phase 2-Alpha).
# 정부 지원사업 공고의 행정 언어를 사용자 친화 언어로 통역.
# generate_project_friendly() 만 교체하면 다른 AI로 전환 가능 (ai_summary.py 와 동일 패턴).

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

_ROOT = Path(__file__).resolve().parent.parent
TEXT_ROOT = _ROOT / "data" / "text"

# 통역 prompt 정책:
#  - 제목: 핵심만 15자 이내, 행정 공식 명칭 왜곡 X
#  - 요약: 한 줄 30자 이내, 누가/뭘/언제까지
#  - JSON 응답 강제 (response_format=json_object)
#  - hallucination 방지: 본문에 없는 내용 X
_SYSTEM_PROMPT = (
    "정부 지원사업 공고를 사용자 친화 언어로 통역한다. 다음 규칙 엄수:\n"
    "1. friendly_title: 핵심만 15자 이내. 행정 기관 공식 명칭이 핵심이면 유지 (예: '전북' 줄이지 마라).\n"
    "2. friendly_summary: 누가/뭘/언제까지를 한 줄 30자 이내로. 본문에 없는 내용 추측 금지.\n"
    "3. 부정 표현 (사기/의심/위험 등) 절대 사용 금지.\n"
    "4. JSON 형식만 응답: {\"friendly_title\": \"...\", \"friendly_summary\": \"...\"}"
)


def load_attachment_text(source: str, attachment_filename: str) -> str:
    """data/text/<source>/files/*.txt 중 첨부 파일명과 매칭되는 추출본 일부 (ai_summary.py 와 동일)."""
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
                    return p.read_text(encoding="utf-8", errors="ignore")[:3000]
                except OSError:
                    continue
    return ""


def generate_project_friendly(item: dict, text: str = "") -> dict:
    """
    OpenAI GPT로 공고 친화 통역 (제목 + 요약).
    성공: {"friendly_title": str, "friendly_summary": str}
    API 키 없거나 실패: {} (호출자에서 NULL 유지 → 위젯이 원본 fallback).
    입력 본문은 최대 3000자.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {}

    title = str(item.get("title") or "").strip()
    org = str(item.get("organization") or "").strip()
    body = (text or "").strip()
    if not body:
        body = f"{title}\n{org}".strip()
    if not body:
        return {}
    body = body[:3000]

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"공고명: {title}\n기관: {org}\n\n내용:\n{body}",
                },
            ],
            max_tokens=150,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        msg = response.choices[0].message.content or "{}"
        data = json.loads(msg)
    except Exception as e:
        print(f"[ai_translate] GPT 통역 실패: {e}")
        return {}

    ft = str(data.get("friendly_title") or "").strip()
    fs = str(data.get("friendly_summary") or "").strip()
    if not ft and not fs:
        return {}
    return {"friendly_title": ft, "friendly_summary": fs}
