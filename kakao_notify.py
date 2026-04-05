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

try:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(_ROOT / ".env")
except Exception:
    pass

KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def send_kakao_message(
    message: str,
    web_url: str = "",
    mobile_web_url: str = "",
) -> dict[str, Any]:
    """
    카카오 메모 API 호출. HTTP 200 + result_code==0 이어야 성공.
    """
    access_token = os.getenv("KAKAO_ACCESS_TOKEN")
    if not (access_token or "").strip():
        raise ValueError("KAKAO_ACCESS_TOKEN 없음")

    template_object: dict[str, Any] = {
        "object_type": "text",
        "text": message,
        "link": {
            "web_url": web_url or "",
            "mobile_web_url": mobile_web_url or "",
        },
    }

    headers = {
        "Authorization": f"Bearer {access_token.strip()}",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    }
    data = {"template_object": json.dumps(template_object, ensure_ascii=False)}

    print("[KAKAO] 요청 시작", flush=True)
    print(f"[KAKAO] message = {message!r}", flush=True)

    resp = requests.post(
        KAKAO_MEMO_URL,
        headers=headers,
        data=data,
        timeout=15,
    )

    print(f"[KAKAO] status_code = {resp.status_code}", flush=True)
    print(f"[KAKAO] response_text = {resp.text!r}", flush=True)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Kakao HTTP {resp.status_code}: {resp.text[:800]!r}"
        )

    try:
        result = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Kakao 응답 JSON 파싱 실패: {resp.text[:800]!r}") from exc

    rc = result.get("result_code", 0)
    if rc != 0:
        raise RuntimeError(f"Kakao API 실패: {result}")

    print("[KAKAO] 전송 성공", flush=True)
    return result


def send_kakao_memo(text: str, web_url: str = "", mobile_web_url: str = "") -> bool:
    """
    Send KakaoTalk memo to my own Kakao account.
    Returns True/False (레거시 호출부 호환).
    """
    try:
        send_kakao_message(text, web_url=web_url, mobile_web_url=mobile_web_url)
        return True
    except Exception as exc:
        print(f"[kakao] memo send failed: {exc}", flush=True)
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
    try:
        base = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
        rec_url = f"{base}/recommend/1" if base else ""
        r = send_kakao_message(
            text,
            web_url=rec_url,
            mobile_web_url=rec_url,
        )
        print("result:", r)
    except Exception as exc:
        print("error:", exc)
