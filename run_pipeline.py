# -*- coding: utf-8 -*-
"""
run_pipeline.py
BizGovPlanner 전체 파이프라인 실행기
사용: py run_pipeline.py
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "pipeline.log"
DB_PATH = ROOT / "db" / "biz.db"


def log(msg: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    now_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_short = datetime.now().strftime("%H:%M:%S")
    line = f"[{now_full}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"[{now_short}] {msg}")


def run_step(label: str, args: list[str]) -> bool:
    result = subprocess.run(
        [sys.executable] + args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode == 0:
        log(f"{label} OK")
        return True

    err_lines = result.stderr.strip().splitlines()
    out_lines = result.stdout.strip().splitlines()
    last_err = err_lines[-1] if err_lines else (out_lines[-1] if out_lines else "(unknown)")
    log(f"{label} FAIL - {last_err}")
    return False


def get_recommend_count() -> int:
    if not DB_PATH.exists():
        return 0

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM recommendations")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def main() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        load_dotenv()
        log(".env loaded")
    except Exception:
        log(".env skipped")

    log("START")

    # STEP 1: 추천 생성
    recommend_ok = run_step(
        "recommend_projects",
        ["pipeline/recommend_projects.py", "--company-id", "1", "--top", "10"],
    )

    if not recommend_ok:
        log("추천 생성 실패 → 후속 알림 중단")
        log("END")
        return

    # STEP 2: 추천 결과 확인
    count = get_recommend_count()
    log(f"추천 결과 {count}건")

    if count == 0:
        log("추천 없음 → 알림 생략")
        log("END")
        return

    # STEP 3: PDF 리포트
    run_step("make_report_pdf", ["pipeline/make_report_pdf.py"])

    # STEP 4: 이메일
    notify_path = ROOT / "pipeline" / "notify_dispatch.py"
    if notify_path.exists():
        run_step("email", [str(notify_path.relative_to(ROOT))])
    else:
        log("email SKIPPED - pipeline/notify_dispatch.py 없음")

    # STEP 5: 카카오
    kakao_token = os.environ.get("KAKAO_ACCESS_TOKEN", "").strip()
    kakao_path = ROOT / "pipeline" / "kakao_notify.py"
    if not kakao_path.exists():
        kakao_path = ROOT / "kakao_notify.py"

    if not kakao_path.exists():
        log("kakao SKIPPED - kakao_notify.py 없음")
    elif not kakao_token:
        log("kakao SKIPPED - KAKAO_ACCESS_TOKEN 없음")
    else:
        run_step("kakao", [str(kakao_path.relative_to(ROOT))])

    log("END")


if __name__ == "__main__":
    main()
