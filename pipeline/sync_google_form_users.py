import sqlite3
import csv
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = "db/biz.db"


def init_users_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT UNIQUE NOT NULL,
          name TEXT, company_name TEXT, phone TEXT,
          region TEXT, industry TEXT,
          email_enabled INTEGER DEFAULT 1,
          kakao_enabled INTEGER DEFAULT 0,
          consent_accepted INTEGER DEFAULT 0,
          consent_text TEXT,
          source TEXT DEFAULT 'google_form',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS google_form_import_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          imported_count INTEGER DEFAULT 0,
          inserted_count INTEGER DEFAULT 0,
          updated_count INTEGER DEFAULT 0,
          skipped_count INTEGER DEFAULT 0,
          status TEXT, message TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    conn.commit()


def normalize_bool(value):
    s = str(value or "").strip().lower()
    return 1 if s in ("예", "동의", "1", "true", "y", "yes", "동의함") else 0


def find_col(headers, keywords):
    for i, h in enumerate(headers):
        for kw in keywords:
            if kw in str(h):
                return i
    return -1


def upsert_user(conn, user):
    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", (user["email"],)
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE users SET
              name=?, company_name=?, phone=?, region=?, industry=?,
              email_enabled=?, kakao_enabled=?, consent_accepted=?,
              consent_text=?, updated_at=?
            WHERE email=?
        """,
            (
                user["name"],
                user["company_name"],
                user["phone"],
                user["region"],
                user["industry"],
                user["email_enabled"],
                user["kakao_enabled"],
                user["consent_accepted"],
                user["consent_text"],
                datetime.now().isoformat(),
                user["email"],
            ),
        )
        return "updated"
    else:
        conn.execute(
            """
            INSERT INTO users
            (email, name, company_name, phone, region, industry,
             email_enabled, kakao_enabled, consent_accepted, consent_text, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                user["email"],
                user["name"],
                user["company_name"],
                user["phone"],
                user["region"],
                user["industry"],
                user["email_enabled"],
                user["kakao_enabled"],
                user["consent_accepted"],
                user["consent_text"],
                user["source"],
            ),
        )
        return "inserted"


def sync_from_csv(csv_path):
    p = Path(csv_path)
    if not p.exists():
        print(f"[ERROR] 파일 없음: {csv_path}")
        return

    conn = sqlite3.connect(DB_PATH)
    init_users_tables(conn)

    imported = inserted = updated = skipped = 0

    with open(p, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)

        # 컬럼 인덱스 탐색
        idx = {
            "email": find_col(headers, ["이메일", "email"]),
            "name": find_col(headers, ["이름", "name"]),
            "company": find_col(headers, ["회사", "company"]),
            "phone": find_col(headers, ["휴대", "전화", "phone"]),
            "region": find_col(headers, ["지역", "region"]),
            "industry": find_col(headers, ["업종", "industry"]),
            "kakao": find_col(headers, ["카카오", "kakao"]),
            "consent": find_col(headers, ["동의", "consent"]),
        }

        print(f"[컬럼 매핑] {idx}")

        if idx["email"] == -1:
            print("[ERROR] 이메일 컬럼 없음")
            conn.close()
            return

        for row in reader:
            imported += 1
            email = row[idx["email"]].strip() if idx["email"] >= 0 else ""
            if not email or "@" not in email:
                skipped += 1
                continue

            def get(key):
                i = idx.get(key, -1)
                return row[i].strip() if i >= 0 and i < len(row) else ""

            user = {
                "email": email.lower(),
                "name": get("name"),
                "company_name": get("company"),
                "phone": get("phone"),
                "region": get("region"),
                "industry": get("industry"),
                "email_enabled": 1,
                "kakao_enabled": normalize_bool(get("kakao")),
                "consent_accepted": normalize_bool(get("consent")),
                "consent_text": "구글폼 수집·이용 동의",
                "source": "google_form",
            }

            result = upsert_user(conn, user)
            if result == "inserted":
                inserted += 1
            else:
                updated += 1

    conn.commit()

    # 로그 기록
    conn.execute(
        """
        INSERT INTO google_form_import_log
        (imported_count, inserted_count, updated_count, skipped_count, status, message)
        VALUES (?,?,?,?,?,?)
    """,
        (
            imported,
            inserted,
            updated,
            skipped,
            "SUCCESS",
            f"imported={imported} inserted={inserted} updated={updated} skipped={skipped}",
        ),
    )
    conn.commit()
    conn.close()

    print(
        f"[완료] imported={imported} inserted={inserted} updated={updated} skipped={skipped}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: py pipeline/sync_google_form_users.py data/google_form/users.csv")
        sys.exit(1)
    sync_from_csv(sys.argv[1])
