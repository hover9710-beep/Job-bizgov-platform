# -*- coding: utf-8 -*-
"""
프로젝트 루트에서 실행: py run_server.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_PY = ROOT / "app.py"
REQ_TXT = ROOT / "requirements.txt"
NEW_JSON = ROOT / "data" / "merged" / "new.json"

HOST = "127.0.0.1"
PORT = 5000


def _print_requirements_hint() -> None:
    if not REQ_TXT.is_file():
        print(f"⚠️ {REQ_TXT.name} 이(가) 없습니다. 의존성을 확인할 수 없습니다.")
        return
    print(f"📦 의존성 파일: {REQ_TXT}")
    print("   미설치 시 프로젝트 루트에서 다음을 실행하세요:")
    print(f"   {sys.executable} -m pip install -r requirements.txt")
    print()


def _check_flask_import() -> bool:
    try:
        import flask  # noqa: F401
    except ImportError as e:
        print("❌ Flask import 오류:", e)
        print("   해결: pip install Flask   또는   pip install -r requirements.txt")
        return False
    return True


def _check_app_import() -> bool:
    """appy 및 하위 의존성 로드 (Flask 외 모듈 누락 시 여기서 구분)."""
    try:
        import appy  # noqa: F401
    except ImportError as e:
        print("❌ 앱 모듈 import 오류 (appy 또는 의존 패키지):", e)
        print("   해결: pip install -r requirements.txt")
        return False
    return True


def _port_in_use() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((HOST, PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _check_port() -> bool:
    if _port_in_use():
        print(f"❌ 포트 사용 중: {HOST}:{PORT}")
        print("   다른 프로세스가 이미 이 포트를 쓰고 있을 수 있습니다.")
        print(f"   Windows: netstat -ano | findstr :{PORT}")
        print("   해당 PID의 프로세스를 종료하거나, app.py 의 포트를 변경하세요.")
        return False
    return True


def _check_new_json() -> None:
    if not NEW_JSON.is_file():
        return
    try:
        with open(NEW_JSON, encoding="utf-8") as f:
            json.load(f)
    except json.JSONDecodeError as e:
        print("❌ JSON 로딩 오류:", NEW_JSON)
        print("   /new 페이지는 서버는 뜨지만, 이 파일이 깨져 있으면 목록에서 오류가 납니다.")
        print(f"   상세: {e}")
        print()


def main() -> int:
    os.chdir(ROOT)

    print("🚀 Flask 서버 시작 중...")
    print()

    _print_requirements_hint()

    print(
        """
접속 주소:
http://127.0.0.1:5000/new
"""
    )

    if not APP_PY.is_file():
        print("❌ app.py 를 찾을 수 없습니다:", APP_PY)
        return 1

    if not _check_flask_import():
        return 1

    if not _check_app_import():
        return 1

    _check_new_json()

    if not _check_port():
        return 1

    try:
        result = subprocess.run(
            [sys.executable, "app.py"],
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            print(f"❌ 서버 프로세스 비정상 종료 (코드 {result.returncode})")
            return result.returncode or 1
    except OSError as e:
        print("❌ 서버 실행 실패 (프로세스 시작 오류):", e)
        return 1
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
