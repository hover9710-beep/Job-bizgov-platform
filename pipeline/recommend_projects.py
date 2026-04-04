# -*- coding: utf-8 -*-
"""
회사(companies) ↔ 공고(biz_projects) 규칙 기반 점수 산출 후 recommendations 테이블에 저장.

실행(프로젝트 루트):
  py pipeline/recommend_projects.py
  py pipeline/recommend_projects.py --company-id 1
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "biz.db"


def ensure_recommendations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id, project_id)
        )
        """
    )


def _export_flag_on(raw: Optional[str]) -> bool:
    s = str(raw or "").strip().lower()
    return s in ("예", "y", "yes", "1", "true", "o")


def _industry_parts(industry_raw: str) -> List[str]:
    raw = str(industry_raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,，/|]", raw) if p.strip()]
    return parts if parts else [raw]


def build_reason(matched: dict) -> str:
    """
    Build human-readable reason string from matched flags.
    matched keys: export_match, industry_match, region_match, agency_match
    """
    parts = []

    if matched.get("export_match"):
        parts.append(
            "귀사가 수출기업이며 공고가 수출·무역 지원 성격과 맞습니다"
        )
    if matched.get("industry_match"):
        parts.append(
            "귀사의 업종 키워드와 공고 내용이 연관됩니다"
        )
    if matched.get("region_match"):
        parts.append(
            "귀사 지역과 공고의 지역 조건 또는 본문 내용이 일부 일치합니다"
        )
    if matched.get("agency_match"):
        parts.append(
            "소관부처 또는 수행기관이 중소·수출 지원 성격과 맞습니다"
        )

    if not parts:
        return "기본 조건 일부가 일치하여 추천되었습니다."

    return " / ".join(parts) + "."


def score_company_project(
    company: Dict[str, Any],
    proj: Dict[str, Any],
) -> Tuple[int, str]:
    """규칙 기반 점수(+30/+40/+10/+20) 및 사람이 읽기 쉬운 reason."""
    score = 0
    matched: Dict[str, bool] = {
        "export_match": False,
        "industry_match": False,
        "region_match": False,
        "agency_match": False,
    }

    title = str(proj.get("title") or "")
    description = str(proj.get("description") or "")
    organization = str(proj.get("organization") or "")
    ministry = str(proj.get("ministry") or "")
    executing_agency = str(proj.get("executing_agency") or "")

    # +30 export (export_flag ≈ export_target)
    export_keywords = ["수출", "무역", "해외", "글로벌", "FTA", "KOTRA", "aT"]
    me = ministry + executing_agency
    if _export_flag_on(company.get("export_flag")) and any(
        k in me for k in export_keywords
    ):
        score += 30
        matched["export_match"] = True

    # +40 industry keyword (keywords ← industry 파트 또는 company["keywords"])
    keywords = company.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        keywords = _industry_parts(str(company.get("industry") or ""))
    for kw in keywords:
        kw_s = str(kw).strip()
        if len(kw_s) < 2:
            continue
        fields = title + organization + ministry + executing_agency
        if kw_s in fields:
            score += 40
            matched["industry_match"] = True
            break

    # +10 region
    region = str(company.get("region") or "").strip()
    if region and region in (title + description + organization):
        score += 10
        matched["region_match"] = True

    # +20 agency type
    agency_keywords = ["지역", "업종", "중소", "지원", "전북", "바우처"]
    if any(k in me for k in agency_keywords):
        score += 20
        matched["agency_match"] = True

    reason = build_reason(matched)
    return score, reason


def run_recommendations(
    conn: sqlite3.Connection,
    *,
    company_id: Optional[int] = None,
    top_per_company: int = 80,
) -> Dict[str, Any]:
    ensure_recommendations_table(conn)
    cur = conn.cursor()

    if company_id is not None:
        companies = cur.execute(
            "SELECT id, company_name, industry, region, employee_count, revenue, export_flag FROM companies WHERE id = ?",
            (int(company_id),),
        ).fetchall()
    else:
        companies = cur.execute(
            "SELECT id, company_name, industry, region, employee_count, revenue, export_flag FROM companies ORDER BY id"
        ).fetchall()

    projects = cur.execute(
        """
        SELECT id, title, organization, ministry, executing_agency, description,
               start_date, end_date, status, url
        FROM biz_projects
        """
    ).fetchall()

    total_upsert = 0
    for co in companies:
        cid = int(co["id"])
        cur.execute("DELETE FROM recommendations WHERE company_id = ?", (cid,))
        company_dict = dict(co)
        pairs: List[Tuple[int, int, str]] = []
        for pr in projects:
            pd = dict(pr)
            pid = int(pd["id"])
            sc, reason_text = score_company_project(company_dict, pd)
            pairs.append((sc, pid, reason_text))

        pairs.sort(key=lambda x: (-x[0], -x[1]))
        kept = 0
        for sc, pid, reason_text in pairs:
            if sc <= 0:
                continue
            cur.execute(
                """
                INSERT OR REPLACE INTO recommendations
                    (company_id, project_id, score, reason)
                VALUES (?, ?, ?, ?)
                """,
                (cid, pid, sc, reason_text),
            )
            total_upsert += 1
            kept += 1
            if kept >= top_per_company:
                break

    conn.commit()
    return {
        "companies": len(companies),
        "projects": len(projects),
        "rows_upserted": total_upsert,
    }


def main() -> int:
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:
                pass

    ap = argparse.ArgumentParser(description="추천 점수 계산 후 recommendations 저장")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--company-id", type=int, default=None)
    ap.add_argument("--top", type=int, default=80, help="회사당 저장 최대 건수(점수>0만)")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[recommend_projects] ERROR: DB 없음 → {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        stats = run_recommendations(
            conn,
            company_id=args.company_id,
            top_per_company=args.top,
        )
        print(
            f"[recommend_projects] 완료: 회사 {stats['companies']}개, "
            f"공고 {stats['projects']}건 기준, 저장 {stats['rows_upserted']}행",
            flush=True,
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
