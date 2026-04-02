import argparse
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv


def load_env() -> Tuple[str, str]:
    load_dotenv()
    gmail_user = os.getenv("GMAIL_USER", "").strip()
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not gmail_user or not gmail_app_password:
        raise RuntimeError("Missing GMAIL_USER or GMAIL_APP_PASSWORD in .env")
    return gmail_user, gmail_app_password


def normalize_email_address(value: str) -> str:
    _, addr = parseaddr(str(value).strip())
    return addr.strip()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_latest_export_file(base_dir: Path) -> Path:
    files = list(base_dir.rglob("jbexport_2*.json"))
    if not files:
        raise FileNotFoundError("jbexport_2*.json 파일을 찾을 수 없습니다.")
    return max(files, key=lambda p: p.stat().st_mtime)


def normalize_companies(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        if isinstance(raw.get("companies"), list):
            raw = raw["companies"]
        else:
            raw = [raw]
    if not isinstance(raw, list):
        return []

    companies: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("company") or item.get("name") or item.get("company_name") or "Unknown Company"
        to_email = item.get("email") or item.get("to") or item.get("recipient") or ""
        keywords = item.get("keywords", item.get("keyword", []))
        if isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, list):
            keywords = []

        companies.append(
            {
                "name": str(name).strip(),
                "email": str(to_email).strip(),
                "keywords": [str(k).strip() for k in keywords if str(k).strip()],
            }
        )
    return companies


def normalize_postings(raw: Any) -> List[Dict[str, str]]:
    postings: List[Dict[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            title = (
                node.get("공고제목")
                or node.get("title")
                or node.get("subject")
                or node.get("name")
                or ""
            )
            url = (
                node.get("상세URL")
                or node.get("url")
                or node.get("link")
                or node.get("href")
                or node.get("detail_url")
                or ""
            )
            if title or url:
                postings.append(
                    {
                        "공고제목": str(title).strip(),
                        "상세URL": str(url).strip(),
                        "raw_text": json.dumps(node, ensure_ascii=False),
                    }
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(raw)
    return postings


def send_email(gmail_user: str, gmail_app_password: str, to_email: str, body: str) -> None:
    from_addr = normalize_email_address(gmail_user)
    recv_addr = normalize_email_address(to_email)
    if not from_addr or not recv_addr:
        raise ValueError("Invalid sender or recipient email address")

    # SMTP envelope addresses should be ASCII unless SMTPUTF8 is negotiated.
    from_addr.encode("ascii")
    recv_addr.encode("ascii")

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = from_addr
    msg["To"] = recv_addr
    msg["Subject"] = "[BizGov] New Support Programs"
    raw_bytes = msg.as_bytes()

    with smtplib.SMTP("smtp.gmail.com", 587, local_hostname="localhost") as smtp:
        smtp.starttls()
        smtp.login(from_addr, gmail_app_password)
        smtp.sendmail(from_addr, recv_addr, raw_bytes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Send only first company")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    companies_path = base_dir / "data" / "companies.json"
    if not companies_path.exists():
        raise FileNotFoundError(f"companies.json 파일 없음: {companies_path}")

    latest_export = find_latest_export_file(base_dir)
    print(f"[FILE] {latest_export}")

    companies = normalize_companies(load_json(companies_path))
    if args.test:
        companies = companies[:1]
        print("[TEST MODE]")

    postings = normalize_postings(load_json(latest_export))

    companies_total = len(companies)
    emails_sent = 0
    matched_total = 0

    gmail_user, gmail_app_password = load_env()

    for company in companies:
        name = company["name"]
        to_email = company["email"]
        keywords = [k.lower() for k in company["keywords"]]

        if not to_email or not keywords:
            print(f"[SKIP] {name}")
            continue

        matched: List[Dict[str, str]] = []
        for m in postings:
            raw_text = m.get("raw_text", "").lower()
            title_text = m.get("공고제목", "").lower()
            if any(kw in raw_text or kw in title_text for kw in keywords):
                matched.append(m)

        matched_count = len(matched)
        matched_total += matched_count
        print(f"[MATCH] {name}: {matched_count}")

        if matched_count == 0:
            print(f"[SKIP] {name}")
            continue

        body = f"Hello {name},\n\nNew support programs matched your keywords:\n\n"
        for m in matched:
            body += f"- {m['공고제목']}\n{m['상세URL']}\n\n"

        try:
            send_email(gmail_user, gmail_app_password, to_email, body)
            emails_sent += 1
            print(f"[SUCCESS] {to_email}")
        except Exception as exc:
            print(f"[SKIP] {name} ({type(exc).__name__}: {exc})")

    print(
        f"[RESULT] companies_total={companies_total}, "
        f"emails_sent={emails_sent}, matched_total={matched_total}"
    )


if __name__ == "__main__":
    main()