# -*- coding: utf-8 -*-
"""
KakaoTalk 나에게 보내기(기본 텍스트 템플릿) — BizGovPlanner 추천 알림.

환경 변수(.env):
  KAKAO_ACCESS_TOKEN
  APP_BASE_URL
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, List

import requests

_ROOT = Path(__file__).resolve().parent
_ENV_PATH = _ROOT / ".env"

try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_PATH)
except Exception:
    pass


KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def send_kakao_memo(text: str, web_url: str = "", mobile_web_url: str = "") -> bool:
    """
    Send KakaoTalk memo to my own Kakao account.
    Returns True/False.
    """
    token = (os.getenv("KAKAO_ACCESS_TOKEN") or "").strip()
    if not token:
        print(
            "[kakao] skipped: token missing (set KAKAO_ACCESS_TOKEN in .env)",
            flush=True,
        )
        return False

    template_obj: dict[str, Any] = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": web_url or "",
            "mobile_web_url": mobile_web_url or "",
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    }
    data = {"template_object": json.dumps(template_obj, ensure_ascii=False)}

    try:
        r = requests.post(
            KAKAO_MEMO_URL,
            headers=headers,
            data=data,
            timeout=15,
        )
        if r.status_code == 200:
            print("[kakao] memo send OK", flush=True)
            return True
        print(
            f"[kakao] memo send failed: HTTP {r.status_code} {r.text[:500]}",
            flush=True,
        )
        return False
    except requests.RequestException as exc:
        print(f"[kakao] memo send error: {exc}", flush=True)
        return False
    except Exception as exc:
        print(f"[kakao] memo unexpected error: {exc}", flush=True)
        return False


def build_recommend_kakao_text(
    company_name: str, company_id: str, rows: List[dict]
) -> str:
    """
    Build short readable Kakao message.
    rows = top recommended projects
    """
    lines: List[str] = [
        "[BizGovPlanner 추천 알림]",
        "",
        f"회사: {company_name or '(이름 없음)'}",
    ]

    if not rows:
        lines.append("이번 추천 결과가 없습니다.")
        return "\n".join(lines)

    n = len(rows)
    lines.append(f"추천 공고: {n}건 생성")
    lines.append("")

    for i, row in enumerate(rows[:3], start=1):
        title = str(row.get("title") or "").strip() or "(제목 없음)"
        lines.append(f"{i}. {title}")

    base = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    if base:
        lines.append("")
        lines.append("확인:")
        lines.append(f"{base}/recommend/{company_id}")

    return "\n".join(lines)


if __name__ == "__main__":
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:
                pass

    sample_rows = [
        {"title": "수출바우처 지원사업"},
        {"title": "해외전시회 참가 지원"},
        {"title": "수출물류비 지원"},
    ]
    text = build_recommend_kakao_text("TestCo", "1", sample_rows)
    print(text)
    ok = send_kakao_memo(
        text,
        web_url="http://127.0.0.1:5000/recommend/1",
        mobile_web_url="http://127.0.0.1:5000/recommend/1",
    )
    print("result:", ok)
