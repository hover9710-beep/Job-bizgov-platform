# -*- coding: utf-8 -*-
"""
auto_run.bat wrapper 5단계 — 자동 daily 크롤 fail 알림.

용도:
  bizplnner Task → auto_run.bat 의 wrapper 가 run_all 종료 후 exit code != 0 일 때
  본 스크립트를 호출 → SMTP 메일 발송. silent fail 재발 방지 (5/2~5/7 5일 stale 사고 chain).

사용:
  py scripts/send_alert.py --exit-code 1 --log logs/auto_run.log
  py scripts/send_alert.py --exit-code 1 --log logs/auto_run.log --dry-run

환경변수 (.env, run_all.py 와 동일):
  SMTP_USER  — Gmail 주소 (필수)
  SMTP_PASS  — Gmail 앱 비밀번호 (필수)
  MAIL_TO    — 수신자 (생략 시 SMTP_USER 자기 자신)

dry-run:
  환경변수 없으면 자동 dry-run (코드 변경 없이 동작 확인 가능). 실 발송은 사용자가 .env 셋업 후.
"""
from __future__ import annotations

import argparse
import os
import smtplib
import socket
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False


ROOT = Path(__file__).resolve().parent.parent


def _exit_label(code: int) -> str:
    if code == 0:
        return "OK"
    if code == 1:
        return "run_all FAIL"
    if code == 2:
        return "proxy startup TIMEOUT"
    return f"unknown exit ({code})"


def _read_log_tail(log_path: Path, n: int) -> str:
    if not log_path.is_file():
        return f"(log file missing: {log_path})"
    try:
        with log_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 200 * 1024)
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        if len(lines) <= n:
            return "\n".join(lines)
        return "\n".join(lines[-n:])
    except OSError as exc:
        return f"(log read failed: {exc})"


def _build_body(exit_code: int, log_tail: str) -> str:
    label = _exit_label(exit_code)
    host = socket.gethostname()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"[BizGovPlanner ALERT] auto_run.bat exit={exit_code} ({label})\n"
        f"\n"
        f"host: {host}\n"
        f"time: {ts}\n"
        f"\n"
        f"--- auto_run.log tail ---\n"
        f"{log_tail}\n"
        f"--- end ---\n"
        f"\n"
        f"trigger: bizplnner Task (Daily 20:37, Run As=custo)\n"
        f"action:  cmd.exe /c auto_run.bat\n"
        f"\n"
        f"확인 후 수동 트리거: schtasks /run /tn \\bizplnner\n"
    )


def send_alert(exit_code: int, log_path: Path, tail_lines: int, dry_run: bool) -> int:
    load_dotenv(ROOT / ".env")

    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_pass = (os.getenv("SMTP_PASS") or "").strip()
    mail_to = (os.getenv("MAIL_TO") or smtp_user).strip()

    log_tail = _read_log_tail(log_path, tail_lines)
    body = _build_body(exit_code, log_tail)
    label = _exit_label(exit_code)
    subject = f"[BizGov] auto_run FAIL exit={exit_code} ({label})"

    if dry_run or not smtp_user or not smtp_pass:
        reason = "dry-run" if dry_run else "SMTP_USER/PASS missing"
        print(f"[send_alert] {reason} — body preview only:")
        print("=" * 60)
        print(f"To: {mail_to}")
        print(f"Subject: {subject}")
        print()
        print(body)
        print("=" * 60)
        return 0

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, local_hostname="localhost") as smtp:
            smtp.login(smtp_user, smtp_pass)
            smtp.send_message(msg)
        print(f"[send_alert] sent to {mail_to} subject={subject!r}")
        return 0
    except Exception as exc:
        print(f"[send_alert] SMTP send failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description="auto_run wrapper fail alert")
    parser.add_argument("--exit-code", type=int, required=True, help="auto_run.bat exit code")
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "logs" / "auto_run.log",
        help="log file to tail (default: logs/auto_run.log)",
    )
    parser.add_argument("--tail-lines", type=int, default=50, help="number of log lines to include (default 50)")
    parser.add_argument("--dry-run", action="store_true", help="print body without sending")
    args = parser.parse_args()

    return send_alert(args.exit_code, args.log, args.tail_lines, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
