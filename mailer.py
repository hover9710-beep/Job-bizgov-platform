# -*- coding: utf-8 -*-
"""
recommended.json 기반 이메일 발송 (BizGovPlanner).
사용: py mailer.py [--dry-run]
"""
from __future__ import annotations

from dotenv import load_dotenv
import os
load_dotenv()

import argparse
import json
import re
import smtplib
import sqlite3
import sys
from email.message import EmailMessage
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.policy import SMTP as SMTP_POLICY
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
RECOMMENDED_JSON = ROOT / "data" / "filtered" / "recommended.json"
LIST_PREVIEW_MAX = 20
MAIL_BODY_FILE = Path("data/mail/mail_body.txt")


def _build_mime_text(content: str) -> MIMEText:
    """본문 문자열을 UTF-8 MIMEText로 생성 (HTML 감지 시 html subtype)."""
    text = str(content or "")
    is_html = bool(re.search(r"<(?:html|body|div|p|br|table|span|a)\b", text, re.I))
    if is_html:
        return MIMEText(text, "html", "utf-8")
    return MIMEText(text, "plain", "utf-8")


def _utf8_stdio() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def load_email_recipients_from_users(db_path: str = "db/biz.db") -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT email, name, company_name, region, industry
        FROM users
        WHERE email_enabled = 1
          AND consent_accepted = 1
          AND email IS NOT NULL
          AND email != ''
        ORDER BY id DESC
    """
    ).fetchall()
    conn.close()

    recipients: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        email = str(r["email"] or "").strip()
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        recipients.append(dict(r))
    return recipients


def load_recommended() -> List[Dict[str, Any]]:
    if not RECOMMENDED_JSON.is_file():
        return []
    try:
        data = json.loads(RECOMMENDED_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[mailer] [경고] JSON 읽기 실패: {exc}", file=sys.stderr)
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def build_subject_and_body(
    company_name: str,
    items: List[Dict[str, Any]],
) -> Tuple[str, str, int]:
    matched_count = len(items)
    show = items[:LIST_PREVIEW_MAX]

    body_lines = [
        f"회사명: {company_name}",
        f"matched_count: {matched_count}",
        "",
    ]
    for i, it in enumerate(show, 1):
        title = str(
            it.get("title")
            or it.get("공고제목")
            or ""
        ).strip()
        org = str(
            it.get("organization")
            or it.get("기관")
            or ""
        ).strip()
        sd = str(it.get("start_date") or "").strip()
        ed = str(it.get("end_date") or "").strip()
        url = str(it.get("url") or "").strip()
        body_lines.append(f"{i}. 공고명: {title}")
        body_lines.append(f"   기관: {org}")
        body_lines.append(f"   시작일: {sd}")
        body_lines.append(f"   마감일: {ed}")
        body_lines.append(f"   URL: {url}")
        body_lines.append("")

    if matched_count > LIST_PREVIEW_MAX:
        body_lines.append(
            f"(표시는 최대 {LIST_PREVIEW_MAX}건이며, 전체 {matched_count}건이 매칭되었습니다.)"
        )

    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"[전북지원사업 메일자동알림서비스] 신규·마감임박·전체 접수중 공고 안내 ({today})"
    built_body = "\n".join(body_lines).strip()
    return subject, built_body, matched_count


def send_gmail_plain(
    *,
    mail_to: str,
    smtp_user: str,
    smtp_pass: str,
    subject: str,
    body: str,
    smtp_server: str,
    smtp_port: int,
) -> None:
    msg = MIMEMultipart()
    msg["Subject"] = str(Header(str(subject), "utf-8"))
    msg["From"] = smtp_user
    msg["To"] = mail_to
    msg.attach(_build_mime_text(body))

    with smtplib.SMTP(
        smtp_server,
        smtp_port,
        timeout=60,
        local_hostname="localhost",
    ) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(
            smtp_user,
            [mail_to],
            msg.as_bytes(policy=SMTP_POLICY),
        )


def send_email(to_email, subject, content, file_path):
    """레거시: Gmail SSL + 첨부. 환경 변수가 있으면 발신 계정에 반영."""
    msg = MIMEMultipart()
    user = os.getenv("SMTP_USER") or os.getenv("GMAIL_USER") or "hover9710@gmail.com"
    pwd = os.getenv("SMTP_PASS") or os.getenv("GMAIL_APP_PASSWORD") or ""
    msg["From"] = user
    msg["To"] = str(to_email)
    msg["Subject"] = str(Header(str(subject), "utf-8"))
    msg.attach(_build_mime_text(str(content)))

    if file_path and os.path.exists(file_path):
        with open(file_path, "rb") as f:
            file_data = f.read()
            file_name = os.path.basename(file_path)
        msg.add_attachment(
            file_data,
            maintype="application",
            subtype="pdf",
            filename=file_name,
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, local_hostname="localhost") as smtp:
        smtp.login(user, pwd)
        smtp.sendmail(user, [str(to_email)], msg.as_string())

    print("이메일 발송 완료:", to_email)


def main() -> int:
    _utf8_stdio()

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        load_dotenv()
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="recommended.json 기반 메일 발송")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="발송 없이 제목·본문 미리보기만",
    )
    args = parser.parse_args()

    smtp_user = (os.environ.get("SMTP_USER") or "").strip()
    smtp_pass = (os.environ.get("SMTP_PASS") or "").strip()
    smtp_server = (os.environ.get("SMTP_SERVER") or "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")

    stats = {
        "sent": 0,
        "failed": 0,
        "skipped_no_recipients": 0,
        "dry_run": 0,
    }

    print("[mailer] BizGovPlanner 알림 (users DB 수신자)", flush=True)

    recipients = load_email_recipients_from_users(str(ROOT / "db" / "biz.db"))

    subject = "정부지원사업 추천 서비스 안내"
    body = """안녕하세요.
정부지원사업 추천 서비스를 안내드립니다.

아래 링크에서 회사정보를 입력하면 맞춤 공고를 확인할 수 있습니다.

서비스 바로가기:
https://barista-raging-fraction.ngrok-free.dev

[주의]
AI 추천은 참고용이며, 최종 신청 여부와 공고 원문 확인은 사용자 책임입니다.
"""

    if args.dry_run:
        stats["dry_run"] = 1
        print("", flush=True)
        print("--- [미리보기] 수신자 ---", flush=True)
        for user in recipients:
            print(f"  - {user.get('email')} ({user.get('name') or ''})", flush=True)
        print("--- [미리보기] 제목 ---", flush=True)
        print(subject, flush=True)
        print("--- [미리보기] 본문 ---", flush=True)
        print(body, flush=True)
        print("", flush=True)
        _print_summary(stats)
        return 0

    if not recipients:
        stats["skipped_no_recipients"] = 1
        print(
            "[mailer] [경고] users DB에서 발송 대상 없음(email_enabled·consent) → 중단",
            file=sys.stderr,
            flush=True,
        )
        _print_summary(stats)
        return 1

    if not smtp_user or not smtp_pass:
        print(
            "[mailer] [경고] SMTP_USER 또는 SMTP_PASS 없음 → 실제 발송 금지",
            file=sys.stderr,
            flush=True,
        )
        stats["failed"] = 1
        _print_summary(stats)
        return 1

    print("[SMTP DEBUG]", flush=True)
    print("SMTP_USER:", smtp_user, flush=True)
    print("SMTP_PASS exists:", bool(smtp_pass), flush=True)
    print("SMTP_SERVER:", smtp_server, flush=True)
    print("SMTP_PORT:", smtp_port, flush=True)

    for user in recipients:
        email = str(user["email"] or "").strip()
        name = user.get("name") or ""
        try:
            send_gmail_plain(
                mail_to=email,
                smtp_user=smtp_user,
                smtp_pass=smtp_pass,
                subject=subject,
                body=body,
                smtp_server=smtp_server,
                smtp_port=smtp_port,
            )
            stats["sent"] += 1
            print(f"[MAIL] sent to {email}", flush=True)
        except Exception as e:
            stats["failed"] += 1
            print(f"[MAIL ERROR] {email}: {e}", file=sys.stderr, flush=True)

    _print_summary(stats)
    return 0 if stats["failed"] == 0 else 1


def _print_summary(stats: Dict[str, int]) -> None:
    print("[mailer] --- 요약 ---", flush=True)
    print(f"  성공(발송): {stats['sent']}", flush=True)
    print(f"  실패: {stats['failed']}", flush=True)
    print(f"  생략(수신자 없음): {stats['skipped_no_recipients']}", flush=True)
    print(f"  dry-run 미리보기: {stats['dry_run']}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
