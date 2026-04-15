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

    mail_to = (os.environ.get("MAIL_TO") or "").strip()
    smtp_user = (os.environ.get("SMTP_USER") or "").strip()
    smtp_pass = (os.environ.get("SMTP_PASS") or "").strip()
    smtp_server = (os.environ.get("SMTP_SERVER") or "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    company_name = (os.environ.get("COMPANY_NAME") or "고객사").strip() or "고객사"

    stats = {
        "sent": 0,
        "failed": 0,
        "skipped_zero": 0,
        "skipped_no_mailto": 0,
        "dry_run": 0,
    }

    print("[mailer] BizGovPlanner 알림", flush=True)
    print(f"[mailer] recommended: {RECOMMENDED_JSON}", flush=True)

    items = load_recommended()
    matched_count = len(items)

    # ── 메일 본문: 파일 우선 (상대 경로는 프로젝트 루트 기준) ──────────────
    _mail_body_path = ROOT / MAIL_BODY_FILE
    if _mail_body_path.exists():
        body = _mail_body_path.read_text(encoding="utf-8")
        print(f"[mailer] 본문 파일 사용: {MAIL_BODY_FILE}")
    else:
        print("[mailer] 본문 파일 없음 → 기존 로직 사용")
        body = None

    if body is None:
        if matched_count == 0:
            stats["skipped_zero"] = 1
            print("[mailer] 매칭 0건 → 메일 생략", flush=True)
            _print_summary(stats)
            return 0
        subject, body, _n = build_subject_and_body(company_name, items)
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        subject = f"[전북지원사업 메일자동알림서비스] 신규·마감임박·전체 접수중 공고 안내 ({today})"

    if args.dry_run:
        stats["dry_run"] = 1
        print("", flush=True)
        print("--- [미리보기] 제목 ---", flush=True)
        print(subject, flush=True)
        print("--- [미리보기] 본문 ---", flush=True)
        print(body, flush=True)
        print("", flush=True)
        _print_summary(stats)
        return 0

    if not mail_to:
        stats["skipped_no_mailto"] = 1
        print(
            "[mailer] [경고] MAIL_TO 미설정 → 수신처 없음, 중단",
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

    try:
        send_gmail_plain(
            mail_to=mail_to,
            smtp_user=smtp_user,
            smtp_pass=smtp_pass,
            subject=subject,
            body=body,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
        )
        stats["sent"] = 1
        print(f"[mailer] 발송 완료 → {mail_to}", flush=True)
    except Exception as exc:
        stats["failed"] = 1
        print(f"[mailer] [실패] SMTP: {exc}", file=sys.stderr, flush=True)
        _print_summary(stats)
        return 1

    _print_summary(stats)
    return 0


def _print_summary(stats: Dict[str, int]) -> None:
    print("[mailer] --- 요약 ---", flush=True)
    print(f"  성공(발송): {stats['sent']}", flush=True)
    print(f"  실패: {stats['failed']}", flush=True)
    print(f"  생략(0건): {stats['skipped_zero']}", flush=True)
    print(f"  생략(MAIL_TO 없음): {stats['skipped_no_mailto']}", flush=True)
    print(f"  dry-run 미리보기: {stats['dry_run']}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
