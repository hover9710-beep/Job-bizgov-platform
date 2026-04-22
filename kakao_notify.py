# -*- coding: utf-8 -*-
"""
Kakao Memo API (나에게 보내기) 발송 모듈.

.env 의 KAKAO_ACCESS_TOKEN 을 사용해 kapi.kakao.com/v2/api/talk/memo/default/send
엔드포인트로 텍스트 템플릿을 보낸다.

CLI
  py kakao_notify.py                  → data/kakao/kakao_body.txt 발송
  py kakao_notify.py --file path.txt  → 지정 파일 발송
  py kakao_notify.py --text "..."     → 텍스트 직접 발송
  py kakao_notify.py --dry-run        → 본문만 출력, 발송 없음
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

DEFAULT_BODY_PATH = _ROOT / "data" / "kakao" / "kakao_body.txt"
DEFAULT_LINK = "https://bizinfo.go.kr"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def send_kakao_message(message: str, link_url: str = DEFAULT_LINK) -> bool:
    """Kakao Memo API 호출. 성공 시 True, 실패 시 False(예외는 호출자에게 맡김)."""
    access_token = os.getenv("KAKAO_ACCESS_TOKEN")
    if not access_token:
        raise RuntimeError("KAKAO_ACCESS_TOKEN 없음 (.env 확인)")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    template = {
        "object_type": "text",
        "text": message,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
    }
    data = {"template_object": json.dumps(template, ensure_ascii=False)}

    print("[KAKAO] 요청 시작", flush=True)
    response = requests.post(KAKAO_MEMO_URL, headers=headers, data=data, timeout=20)
    print(f"[KAKAO] status_code={response.status_code}", flush=True)
    print(f"[KAKAO] response_text={response.text[:400]}", flush=True)

    if response.status_code != 200:
        raise RuntimeError(f"카카오 전송 실패: HTTP {response.status_code}")

    print("[KAKAO] 전송 성공", flush=True)
    return True


def send_kakao_memo(text: str, web_url: str = "", mobile_web_url: str = "") -> None:
    """legacy shim — text 만 Memo API 로 발송."""
    send_kakao_message(text, link_url=web_url or DEFAULT_LINK)


def build_recommend_kakao_text(company_name: str, company_id: str, items: list) -> str:
    lines = [f"[맞춤 추천] {company_name} 기준 상위 {len(items)}건"]
    for i, item in enumerate(items[:5], 1):
        title = item.get("title") or item.get("공고제목") or ""
        lines.append(f"{i}. {title[:30]}")
    return "\n".join(lines)


def _load_body(path: Path) -> Optional[str]:
    if not path.is_file():
        print(f"[KAKAO] body 파일 없음: {path}", flush=True)
        return None
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        print(f"[KAKAO] body 파일 비어 있음: {path}", flush=True)
        return None
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="Kakao Memo 발송 CLI")
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_BODY_PATH,
        help=f"발송할 본문 파일 (기본: {DEFAULT_BODY_PATH})",
    )
    parser.add_argument("--text", default="", help="파일 대신 직접 본문 텍스트 지정")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="발송 없이 본문만 출력",
    )
    parser.add_argument(
        "--link",
        default=DEFAULT_LINK,
        help="메시지 링크 URL (기본: bizinfo.go.kr)",
    )
    args = parser.parse_args()

    if args.text:
        body = args.text
    else:
        body = _load_body(args.file) or ""

    if not body:
        print("[KAKAO] skip: 본문 없음", flush=True)
        return 0

    if args.dry_run:
        print("[KAKAO] --dry-run, 본문 미리보기:", flush=True)
        print(body, flush=True)
        return 0

    try:
        send_kakao_message(body, link_url=args.link)
    except Exception as exc:
        print(f"[KAKAO] 실패: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
