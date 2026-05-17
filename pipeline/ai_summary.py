# AI 요약 모듈 - OpenAI GPT 사용.
# generate_project_summary() 내부만 교체하면 다른 AI로 전환 가능.

from __future__ import annotations

import json
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
                    return p.read_text(encoding="utf-8", errors="ignore")[:3000]
                except OSError:
                    continue
    return ""


def generate_project_summary(item: dict, text: str = "") -> str:
    """
    OpenAI GPT로 공고 1줄 요약.
    API 키 없거나 실패하면 빈 문자열 (파이프라인 중단 없음).
    입력 본문은 최대 3000자로 잘라서 전송.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""

    title = str(item.get("title") or "").strip()
    org = str(item.get("organization") or "").strip()
    body = (text or "").strip()
    if not body:
        body = f"{title}\n{org}".strip()
    if not body:
        return ""
    body = body[:3000]

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
                    "content": f"공고명: {title}\n기관: {org}\n\n내용:\n{body}",
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


_BATCH_SYSTEM_PROMPT = (
    "여러 정부 지원사업 공고를 각각 한 줄로 요약한다. 규칙:\n"
    "1. 각 summary 는 핵심 지원 내용과 대상을 포함해 50자 이내.\n"
    "2. 본문에 없는 내용 추측 금지 (input 이 짧으면 title 기반으로만 작성).\n"
    "3. 부정 표현 (사기/의심/위험 등) 절대 사용 금지.\n"
    "4. 입력의 idx 를 결과에 그대로 보존하여 순서 매칭.\n"
    "5. JSON 형식만 응답: {\"results\": [{\"idx\": 0, \"summary\": \"...\"}, ...]}"
)


def batch_generate_summary(items: list, texts: list) -> dict:
    """N건 공고를 한 번의 GPT 호출로 요약 (백로그 069 Phase 2, 5/17 EOD).

    items[i]: {id, title, organization, ...}
    texts[i]: 본문 (각 최대 3000자, 호출자가 잘라 전달)
    Returns: {idx: summary_str, ...} — 성공한 항목만.
    실패 시 빈 dict.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or not items:
        return {}

    blocks = []
    for idx, (item, text) in enumerate(zip(items, texts)):
        title = str(item.get("title") or "").strip()
        org = str(item.get("organization") or "").strip()
        body = (text or "").strip()
        if not body:
            body = f"{title}\n{org}".strip()
        body = body[:3000]
        blocks.append(
            f"=== idx {idx} ===\n공고명: {title}\n기관: {org}\n내용:\n{body}"
        )
    user_msg = "\n\n".join(blocks)

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _BATCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=150 * len(items) + 100,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        msg = response.choices[0].message.content or "{}"
        data = json.loads(msg)
    except Exception as e:
        print(f"[ai_summary.batch] GPT 호출 실패 (n={len(items)}): {e}")
        return {}

    results = data.get("results")
    if not isinstance(results, list):
        return {}

    out: dict = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r.get("idx", -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(items)):
            continue
        summary = str(r.get("summary") or "").strip()
        if not summary:
            continue
        out[idx] = summary
    return out
