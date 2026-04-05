# -*- coding: utf-8 -*-
"""
Kakao OAuth access_token 갱신 (refresh_token 사용).
.env의 KAKAO_ACCESS_TOKEN(및 필요 시 KAKAO_REFRESH_TOKEN) 갱신.

필요 환경 변수(예):
  KAKAO_REST_API_KEY 또는 KAKAO_CLIENT_ID
  KAKAO_REFRESH_TOKEN
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def _bootstrap_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        load_dotenv()
    except Exception:
        pass


def main() -> int:
    _bootstrap_env()

    client_id = (
        os.getenv("KAKAO_REST_API_KEY") or os.getenv("KAKAO_CLIENT_ID") or ""
    ).strip()
    refresh = (os.getenv("KAKAO_REFRESH_TOKEN") or "").strip()

    if not client_id or not refresh:
        print(
            "[kakao_token_refresh] skip: KAKAO_REST_API_KEY/KAKAO_CLIENT_ID "
            "또는 KAKAO_REFRESH_TOKEN 없음",
            flush=True,
        )
        return 0

    try:
        import requests
    except ImportError:
        print("[kakao_token_refresh] requests 미설치", flush=True)
        return 1

    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(
            f"[kakao_token_refresh] HTTP {resp.status_code}: {resp.text[:800]}",
            flush=True,
        )
        return 1

    try:
        body = resp.json()
    except Exception as exc:
        print(f"[kakao_token_refresh] JSON 오류: {exc}", flush=True)
        return 1

    access = (body.get("access_token") or "").strip()
    if not access:
        print(f"[kakao_token_refresh] access_token 없음: {body}", flush=True)
        return 1

    new_refresh = (body.get("refresh_token") or "").strip()

    try:
        from dotenv import set_key
    except ImportError:
        print("[kakao_token_refresh] python-dotenv set_key 필요", flush=True)
        return 1

    if not ENV_PATH.is_file():
        print(f"[kakao_token_refresh] .env 없음: {ENV_PATH}", flush=True)
        return 1

    set_key(str(ENV_PATH), "KAKAO_ACCESS_TOKEN", access)
    if new_refresh:
        set_key(str(ENV_PATH), "KAKAO_REFRESH_TOKEN", new_refresh)

    os.environ["KAKAO_ACCESS_TOKEN"] = access
    if new_refresh:
        os.environ["KAKAO_REFRESH_TOKEN"] = new_refresh

    print("[kakao_token_refresh] OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
