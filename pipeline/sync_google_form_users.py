import csv
import sqlite3
from datetime import datetime
import sys
import os

DB_PATH = "db/biz.db"


def find_col(headers, keywords):
    for i, h in enumerate(headers):
        h_str = str(h)
        for kw in keywords:
            if kw in h_str:
                return i
    return -1


def normalize_bool(v):
    if v is None:
        return 0
    v = str(v).strip().lower()
    if v in ["예", "y", "yes", "true", "1", "동의"]:
        return 1
    return 0


def upsert_user(conn, user):
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (user["email"],))
    row = cur.fetchone()

    if row:
        cur.execute(
            """
        UPDATE users SET
            name=?, company_name=?, region=?, industry=?,
            phone=?, kakao_enabled=?, consent_accepted=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE email=?
        """,
            (
                user["name"],
                user["company_name"],
                user["region"],
                user["industry"],
                user["phone"],
                user["kakao_enabled"],
                user["consent_accepted"],
                user["email"],
            ),
        )
        return "updated"
    else:
        cur.execute(
            """
        INSERT INTO users
        (email, name, company_name, region, industry,
         phone, kakao_enabled, consent_accepted)
        VALUES (?,?,?,?,?,?,?,?)
        """,
            (
                user["email"],
                user["name"],
                user["company_name"],
                user["region"],
                user["industry"],
                user["phone"],
                user["kakao_enabled"],
                user["consent_accepted"],
            ),
        )
        return "inserted"


def sync_from_csv(csv_path):
    if not os.path.exists(csv_path):
        print("[ERROR] CSV 파일 없음:", csv_path)
        return

    conn = sqlite3.connect(DB_PATH)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 2:
        print("[INFO] 데이터 없음")
        conn.close()
        return

    headers = rows[0]

    email_idx = find_col(headers, ["이메일"])
    name_idx = find_col(headers, ["이름"])
    company_idx = find_col(headers, ["회사"])
    region_idx = find_col(headers, ["지역"])
    industry_idx = find_col(headers, ["업종"])
    phone_idx = find_col(headers, ["휴대", "전화"])
    kakao_idx = find_col(headers, ["카카오"])  # 핵심 수정
    consent_idx = find_col(headers, ["개인정보"])  # 핵심 수정

    if email_idx == -1:
        print("[ERROR] 이메일 컬럼 없음")
        conn.close()
        return

    inserted = updated = skipped = 0

    for r in rows[1:]:
        email = str(r[email_idx]).strip()
        if not email or "@" not in email:
            skipped += 1
            continue

        user = {
            "email": email,
            "name": r[name_idx] if name_idx != -1 else "",
            "company_name": r[company_idx] if company_idx != -1 else "",
            "region": r[region_idx] if region_idx != -1 else "",
            "industry": r[industry_idx] if industry_idx != -1 else "",
            "phone": r[phone_idx] if phone_idx != -1 else "",
            "kakao_enabled": normalize_bool(r[kakao_idx]) if kakao_idx != -1 else 0,
            "consent_accepted": normalize_bool(r[consent_idx]) if consent_idx != -1 else 0,
        }

        result = upsert_user(conn, user)
        if result == "inserted":
            inserted += 1
        else:
            updated += 1

    conn.commit()
    conn.close()

    print(
        f"[DONE] imported {len(rows)-1}건 → inserted {inserted}, updated {updated}, skipped {skipped}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: py pipeline/sync_google_form_users.py data/google_form/users.csv")
    else:
        sync_from_csv(sys.argv[1])
