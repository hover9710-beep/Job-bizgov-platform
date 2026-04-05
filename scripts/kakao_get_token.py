# -*- coding: utf-8 -*-
"""
scripts/kakao_get_token.py
카카오 최초 토큰 발급 (최초 1회)
사용: py scripts/kakao_get_token.py
"""

import os
import re
import webbrowser
import requests
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT      = Path(__file__).resolve().parent.parent
ENV_FILE  = ROOT / ".env"
REDIRECT  = "https://example.com"


def update_env(key: str, value: str):
    import stat
    try:
        os.chmod(ENV_FILE, stat.S_IREAD | stat.S_IWRITE)
    except Exception:
        pass
    if ENV_FILE.exists():
        content = ENV_FILE.read_text(encoding="utf-8")
    else:
        content = ""
    pattern = rf"^{re.escape(key)}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content = content.rstrip() + f"\n{key}={value}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    try:
        os.chmod(ENV_FILE, stat.S_IREAD)
    except Exception:
        pass


def main():
    print("=" * 50)
    print("카카오 최초 토큰 발급")
    print("=" * 50)

    rest_api_key = input("KAKAO REST API 키 입력: ").strip()
    if not rest_api_key:
        print("ERROR: REST API 키를 입력하세요.")
        return

    update_env("KAKAO_REST_API_KEY", rest_api_key)

    auth_url = (
        f"https://kauth.kakao.com/oauth/authorize"
        f"?client_id={rest_api_key}"
        f"&redirect_uri={REDIRECT}"
        f"&response_type=code"
    )

    print()
    print("브라우저가 열립니다. 로그인 후 리다이렉트된 전체 URL을 복사하세요.")
    webbrowser.open(auth_url)

    print()
    redirected = input("리다이렉트된 전체 URL 붙여넣기: ").strip()

    parsed = urlparse(redirected)
    params = parse_qs(parsed.query)
    code_list = params.get("code", [])
    if not code_list:
        print("ERROR: URL에서 code를 찾지 못했습니다.")
        return
    code = code_list[0]
    print(f"인가 코드 확인: {code[:20]}...")

    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type":   "authorization_code",
            "client_id":    rest_api_key,
            "redirect_uri": REDIRECT,
            "code":         code,
        },
        timeout=10,
    )

    if resp.status_code != 200:
        print(f"ERROR: {resp.status_code} / {resp.text}")
        return

    result = resp.json()
    access_token  = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")

    if not access_token:
        print(f"ERROR: access_token 없음 → {result}")
        return

    update_env("KAKAO_ACCESS_TOKEN",  access_token)
    update_env("KAKAO_REFRESH_TOKEN", refresh_token)

    print()
    print("Saved tokens to .env ✅")
    print("이제 py run_pipeline.py 실행 가능합니다.")


if __name__ == "__main__":
    main()
