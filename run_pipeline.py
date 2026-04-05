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


def _load_kakao_recommend_rows(company_id: int) -> tuple[str, list[dict]]:
    """카카오 메시지용: 회사명 + 추천 공고 title 목록 (recommendations + biz_projects)."""
    if not DB_PATH.exists():
        return "", []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT company_name FROM companies WHERE id = ?",
        (company_id,),
    )
    crow = cur.fetchone()
    if not crow:
        conn.close()
        return "", []
    cname = str(crow["company_name"] or "").strip()
    cur.execute(
        """
        SELECT p.title
        FROM recommendations r
        JOIN biz_projects p ON r.project_id = p.id
        WHERE r.company_id = ?
        ORDER BY r.score DESC
        LIMIT 80
        """,
        (company_id,),
    )
    rows = [{"title": r["title"] or ""} for r in cur.fetchall()]
    conn.close()
    return cname, rows


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

    run_step("kakao_refresh", ["scripts/kakao_token_refresh.py"])
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        load_dotenv()
    except Exception:
        pass

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
    email_ok = False
    notify_path = ROOT / "pipeline" / "notify_dispatch.py"
    if notify_path.exists():
        email_ok = run_step("email", [str(notify_path.relative_to(ROOT))])
    else:
        log("email SKIPPED - pipeline/notify_dispatch.py 없음")

    if email_ok:
        print("email OK")
        print(">>> email 직후 통과")

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
        print(">>> kakao 호출 직전")
        try:
            from kakao_notify import build_recommend_kakao_text, send_kakao_message

            pipeline_company_id = 1
            company_name, rec_rows = _load_kakao_recommend_rows(pipeline_company_id)
            kakao_message = build_recommend_kakao_text(
                company_name or "회사",
                str(pipeline_company_id),
                rec_rows,
            )
            base = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
            rec_url = f"{base}/recommend/{pipeline_company_id}" if base else ""
            result = send_kakao_message(
                kakao_message,
                web_url=rec_url,
                mobile_web_url=rec_url,
            )
            print("kakao OK")
            print(">>> kakao result =", result)
            log("kakao OK")
        except Exception as e:
            print("kakao ERROR:", e)
            log(f"kakao FAIL - {e}")

    log("END")


if __name__ == "__main__":
    main()
