# -*- coding: utf-8 -*-
"""
run_pipeline.py
BizGovPlanner 전체 파이프라인 실행기
사용: py run_pipeline.py
"""

from __future__ import annotations

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
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_short = datetime.now().strftime("%H:%M:%S")
    line = f"[{now_full}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"[{now_short}] {msg}")


def run_step(label: str, args: list[str]) -> bool:
    try:
        result = subprocess.run(
            [sys.executable] + args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        log(f"{label} FAIL - subprocess 예외: {e}")
        return False

    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())

    if result.returncode == 0:
        log(f"{label} OK")
        return True

    err_lines = result.stderr.strip().splitlines() if result.stderr else []
    err_msg = err_lines[-1] if err_lines else f"exit code {result.returncode}"
    log(f"{label} FAIL - {err_msg}")
    return False


def get_recommend_count(company_id: int) -> int:
    if not DB_PATH.exists():
        return 0

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM recommendations WHERE company_id = ?",
            (company_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def load_recommend_rows(company_id: int, limit: int = 3) -> list[tuple[str, str]]:
    """
    카카오 메시지용 상위 추천 몇 건만 읽음
    return: [(title, reason), ...]
    """
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT p.title, COALESCE(r.reason, '')
            FROM recommendations r
            JOIN biz_projects p ON r.project_id = p.id
            WHERE r.company_id = ?
            ORDER BY r.score DESC, r.id DESC
            LIMIT ?
            """,
            (company_id, limit),
        )
        return [(str(t or ""), str(r or "")) for t, r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def load_company_name(company_id: int) -> str:
    if not DB_PATH.exists():
        return "회사"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("SELECT company_name FROM companies WHERE id = ?", (company_id,))
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
        return "회사"
    except Exception:
        return "회사"
    finally:
        conn.close()


def build_kakao_message(company_id: int, count: int) -> str:
    company_name = load_company_name(company_id)
    rows = load_recommend_rows(company_id, limit=3)

    lines = [
        "[BizGovPlanner 추천 알림]",
        "",
        f"회사: {company_name}",
        f"추천 공고: {count}건 생성",
        "",
    ]

    if not rows:
        lines.append("추천 결과 요약 없음")
    else:
        for idx, (title, _reason) in enumerate(rows, 1):
            lines.append(f"{idx}. {title}")

    return "\n".join(lines)


def main() -> None:
    # .env 로드
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        load_dotenv()
        log(".env loaded")
    except Exception as e:
        log(f".env load skipped - {e}")

    # 0) 카카오 토큰 갱신
    run_step("kakao_refresh", ["scripts/kakao_token_refresh.py"])

    log("START")

    company_id = 1

    # 1) connectors
    run_step("connectors", ["connectors/connector_bizinfo.py"])

    # 2) merge_all
    run_step("merge_all", ["pipeline/merge_all.py"])

    # 3) detect_new
    run_step("detect_new", ["pipeline/detect_new.py"])

    # 4) detect_deadline
    run_step("detect_deadline", ["pipeline/detect_deadline.py"])

    run_step(
        "recommend_projects",
        ["pipeline/recommend_projects.py", "--company-id", str(company_id), "--top", "10"],
    )

    count = get_recommend_count(company_id)
    log(f"추천 결과 {count}건")

    if count > 0:
        run_step("make_report_pdf", ["pipeline/make_report_pdf.py"])

    # 5) make_mail
    run_step("make_mail", ["pipeline/make_mail.py"])

    # 6) 이메일 (mailer)
    email_ok = run_step("email", ["mailer.py"])
    if email_ok:
        print("email OK")
        print(">>> email 직후 통과")

    # 7) 카카오
    try:
        print(">>> kakao 호출 직전")

        import kakao_notify
        print("KAKAO FILE =", kakao_notify.__file__)

        from kakao_notify import send_kakao_message

        kakao_message = build_kakao_message(company_id, count)
        result = send_kakao_message(kakao_message)

        print("kakao OK")
        print(">>> kakao result =", result)
        log("kakao OK")
    except Exception as e:
        print("kakao ERROR:", e)
        log(f"kakao FAIL - {e}")

    log("END")


if __name__ == "__main__":
    main()